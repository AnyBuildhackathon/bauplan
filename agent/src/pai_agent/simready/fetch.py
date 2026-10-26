"""Fetches one SimReady package into the local cache, license-checked and verified file by file.

A package is one folder of the Hugging Face dataset nvidia/simready-assets at the pinned
revision. Its `com.nvidia.simready.packaging.json` declares the license and the SHA-256 of the
bill of materials (`.metadata/com.nvidia.simready.packaging.bom.json`), which lists every file
under `simready_usd/` with its size and SHA-256. `fetch` reads the license before anything else
and refuses every license but CC-BY-4.0, checks the bill of materials against the packaging
file, then downloads only what a conversion needs (the root USD, its payloads and textures, one
thumbnail and the license text; not the MDL sources or the texture previews) and checks each
file against the bill of materials. The folder appears in the cache only when every file
passed, with a marker that lets the next fetch return it without a network call.

The cache lives outside the repository: PAI_SIMREADY_CACHE, else ~/.cache/anybuild/simready,
one folder per revision. PAI_SIMREADY_MIRROR points fetch at a local folder laid out like the
dataset (one folder per package) instead of Hugging Face, for machines without network and for
the tests. HF_TOKEN, or a token saved by `hf auth login`, raises Hugging Face's rate limit.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from pai_agent.simready import LICENSE, REPO_ID, REVISION

try:
    import fcntl
except ImportError:  # Windows: the thread lock alone guards the cache
    fcntl = None

PACKAGING = "com.nvidia.simready.packaging.json"
BOM = ".metadata/com.nvidia.simready.packaging.bom.json"
ROOTS = ".metadata/com.nvidia.simready.root_usds.json"
LICENSE_TEXT = ".metadata/LICENSE.txt"
MARKER = ".anybuild-fetch.json"
# Bumped when the marker or the choice of files changes, so an older cache entry is fetched again.
_MARKER_VERSION = 1

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")
_WORKERS = 6
# The thumbnail the dashboard shows: the render on a transparent background works on light and dark cards.
_THUMB_ORDER = ("_transparent.png", ".png", "_light.png")
THUMB_PX = 256


class SimReadyError(Exception):
    """A package AnyBuild cannot use; the message says why in one sentence."""


class LicenseError(SimReadyError):
    """The package is not under CC-BY-4.0."""


class IntegrityError(SimReadyError):
    """A file does not match the size or SHA-256 its package declares."""


class FetchError(SimReadyError):
    """The package is not in the cache and could not be downloaded."""


@dataclass(frozen=True)
class Package:
    """A verified package folder in the cache. Paths are relative to `folder`, with forward slashes."""

    asset_id: str
    revision: str
    folder: Path
    package_id: str
    license: str
    root: str
    thumbnail: str | None
    # Every file in the folder that a hash covers: {path: {"size": bytes, "sha256": hex}}.
    files: dict

    @property
    def root_usd(self) -> Path:
        return self.folder / self.root

    @property
    def thumbnail_path(self) -> Path | None:
        return self.folder / self.thumbnail if self.thumbnail else None

    def digest(self) -> str:
        """One hash over every file's hash: names this exact content in the conversion cache."""

        listing = sorted((path, info["sha256"]) for path, info in self.files.items())
        return hashlib.sha256(json.dumps([self.revision, listing]).encode("utf-8")).hexdigest()


def cache_root() -> Path:
    raw = os.environ.get("PAI_SIMREADY_CACHE", "").strip()
    if raw:
        return Path(raw).expanduser()
    base = os.environ.get("XDG_CACHE_HOME", "").strip()
    return (Path(base).expanduser() if base else Path.home() / ".cache") / "anybuild" / "simready"


def revision_dir(revision: str = REVISION) -> Path:
    return cache_root() / revision[:12]


def check_id(asset_id: str) -> str:
    """A package id is one folder name of the dataset; anything else (a path, '..') is refused."""

    if not isinstance(asset_id, str) or not _ID.fullmatch(asset_id) or ".." in asset_id:
        raise SimReadyError(f"Not a SimReady package id: {asset_id!r}")
    return asset_id


def package_dir(asset_id: str, revision: str = REVISION) -> Path:
    return revision_dir(revision) / "packages" / check_id(asset_id)


def normalize_license(value) -> str:
    """'CC BY 4.0', 'cc-by-4.0' and 'CC-BY-4.0' all read as CC-BY-4.0; any other license keeps its own name."""

    return re.sub(r"[\s_]+", "-", str(value or "").strip()).upper()


def check_license(packaging: dict, asset_id: str) -> str:
    found = normalize_license(packaging.get("license"))
    if found != LICENSE:
        shown = str(packaging.get("license") or "no license")
        raise LicenseError(f"{asset_id} is licensed {shown}, not CC-BY-4.0; AnyBuild only uses CC-BY-4.0 objects.")
    return LICENSE


def check_license_text(path: Path, asset_id: str) -> None:
    """The license file must be the CC BY 4.0 legal code, not a NonCommercial, ShareAlike or NoDerivatives one."""

    text = path.read_text(encoding="utf-8", errors="replace")
    if "Attribution 4.0 International" not in text or re.search(r"NonCommercial|ShareAlike|NoDerivatives", text):
        raise LicenseError(f"{asset_id} ships a license text that is not CC BY 4.0; AnyBuild only uses CC-BY-4.0 objects.")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(path: Path, size: int | None, sha256: str, label: str) -> None:
    actual_size = path.stat().st_size
    if size is not None and actual_size != int(size):
        raise IntegrityError(f"{label} is {actual_size} bytes, the package declares {size}.")
    if sha256_file(path) != str(sha256).lower():
        raise IntegrityError(f"{label} does not match the SHA-256 its package declares.")


def safe_relative(path: str) -> str:
    """A path from a package file, refused unless it stays inside the package folder."""

    pure = PurePosixPath(str(path))
    if not str(path) or "\\" in str(path) or pure.is_absolute() or any(part in ("", ".", "..") for part in pure.parts):
        raise IntegrityError(f"The package lists an unsafe path: {path!r}")
    return pure.as_posix()


def needed(path: str, thumbnail: str | None) -> bool:
    """What a conversion reads: no MDL sources, no texture previews, and one thumbnail of the several renders."""

    if path.startswith("simready_usd/source_assets/") or "/Textures/.thumbs/" in path:
        return False
    if "/.thumbs/" in path:
        return path == thumbnail
    return True


def pick_thumbnail(paths, root: str) -> str | None:
    """The 256 x 256 render of the root USD (on a transparent background when there is one), else any render."""

    paths = set(paths)
    name = PurePosixPath(root).name
    for suffix in _THUMB_ORDER:
        candidate = f"simready_usd/.thumbs/256x256/{name}{suffix}"
        if candidate in paths:
            return candidate
    renders = sorted(p for p in paths if p.startswith("simready_usd/.thumbs/") and p.endswith(".png"))
    plain = [p for p in renders if not re.search(r"_(dark|light)\.png$", p)]
    return (plain or renders or [None])[0]


def _bom_hash(packaging: dict, asset_id: str) -> str:
    for entry in packaging.get("metadata") or []:
        if isinstance(entry, dict) and entry.get("name") == PurePosixPath(BOM).name:
            sha = (entry.get("hash") or {}).get("sha256")
            if sha:
                return str(sha)
    raise IntegrityError(f"{asset_id}'s packaging file declares no hash for its bill of materials, so its files cannot be verified.")


def _bom_items(bom: dict) -> dict:
    items = {}
    for item in bom.get("items") or []:
        path = safe_relative(item["relative_path"])
        items[path] = {"size": int(item["size"]), "sha256": str((item.get("hash") or {})["sha256"]).lower()}
    return items


def _root(stage: Path, items: dict, get, asset_id: str) -> str:
    """The root USD that `.metadata/com.nvidia.simready.root_usds.json` names, else the one USD at the top of simready_usd/."""

    roots: list[str] = []
    try:
        get(ROOTS, stage / ROOTS)
        roots = [safe_relative(entry) for entry in json.loads((stage / ROOTS).read_text(encoding="utf-8")).get("entries") or []]
    except (FetchError, OSError, ValueError, AttributeError):
        roots = []
    roots = [r for r in roots if r in items]
    if not roots:
        roots = sorted(p for p in items if re.fullmatch(r"simready_usd/[^/]+\.usd[ac]?", p))
    if not roots:
        raise IntegrityError(f"{asset_id} has no root USD file.")
    return roots[0]


class HubSource:
    """Files of the pinned revision from Hugging Face's resolve endpoint, one GET each.

    The token (HF_TOKEN, else the one `hf auth login` saved) goes only to Hugging Face itself, never
    along a redirect to the CDN. Rate limits (HTTP 429) and server errors wait as Hugging Face asks
    (Retry-After, or the reset time in its RateLimit header) and try again.
    """

    def __init__(self, revision: str = REVISION) -> None:
        self.revision = revision

    def get(self, path: str, dest: Path) -> None:
        from http.client import HTTPException
        from urllib.error import HTTPError, URLError
        from urllib.parse import quote
        from urllib.request import Request, urlopen

        from pai_agent.currency import ssl_context

        endpoint = os.environ.get("HF_ENDPOINT", "").strip().rstrip("/") or "https://huggingface.co"
        url = f"{endpoint}/datasets/{REPO_ID}/resolve/{self.revision}/{quote(safe_relative(path))}"
        request = Request(url, headers={"User-Agent": "AnyBuild-SimReady/1"})
        token = hub_token()
        if token:
            request.add_unredirected_header("Authorization", "Bearer " + token)
        dest.parent.mkdir(parents=True, exist_ok=True)
        partial = dest.with_name(dest.name + f".download-{os.getpid()}-{threading.get_ident()}")
        try:
            for attempt in range(_ATTEMPTS):
                try:
                    with urlopen(request, timeout=_TIMEOUT_S, context=ssl_context()) as response, partial.open("wb") as out:
                        expected = response.headers.get("Content-Length")
                        shutil.copyfileobj(response, out, 1 << 20)
                    # http.client ends a body early without an error when the connection drops; that is a retry.
                    if expected and expected.isdigit() and partial.stat().st_size != int(expected):
                        if attempt == _ATTEMPTS - 1:
                            raise FetchError(f"Hugging Face sent {partial.stat().st_size} of {expected} bytes of {path}.")
                        time.sleep(1 + attempt)
                        continue
                    os.replace(partial, dest)
                    return
                except HTTPError as exc:
                    if exc.code == 404:
                        raise FetchError(f"{path} is not in {REPO_ID} at revision {self.revision[:12]}.") from exc
                    if exc.code not in (408, 429, 500, 502, 503, 504) or attempt == _ATTEMPTS - 1:
                        raise FetchError(f"Hugging Face answered HTTP {exc.code} for {path}.") from exc
                    time.sleep(min(_retry_after(exc.headers, attempt), _MAX_WAIT_S))
                except (URLError, OSError, HTTPException) as exc:
                    # No connection, a timeout, or a body cut off mid-way (reset, SSL error, incomplete read).
                    if attempt >= 2:
                        reason = getattr(exc, "reason", exc)
                        raise FetchError(f"Hugging Face is unreachable ({reason}); {path} is not in the cache.") from exc
                    time.sleep(1 + attempt)
        finally:
            partial.unlink(missing_ok=True)


_ATTEMPTS = 6
_TIMEOUT_S = 60
_MAX_WAIT_S = 300


def _retry_after(headers, attempt: int) -> float:
    """Seconds to wait before the next try: Retry-After, else the window reset of an exhausted RateLimit, else backoff."""

    value = (headers.get("Retry-After") or "").strip() if headers else ""
    if value.isdigit():
        return float(value)
    limit = (headers.get("RateLimit") or "") if headers else ""
    remaining, reset = re.search(r"\br=(\d+)", limit), re.search(r"\bt=(\d+)", limit)
    if remaining and reset and int(remaining.group(1)) == 0:
        return float(reset.group(1)) + 1
    return float(2 ** attempt)


def hub_token() -> str | None:
    """HF_TOKEN, else the token `hf auth login` saved (through huggingface_hub when it is installed)."""

    token = os.environ.get("HF_TOKEN", "").strip()
    if token:
        return token
    try:
        from huggingface_hub import get_token
    except ImportError:
        return None
    try:
        return get_token()
    except Exception:
        return None


class MirrorSource:
    """A local folder laid out like the dataset, one folder per package (PAI_SIMREADY_MIRROR)."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def get(self, path: str, dest: Path) -> None:
        source = self.root / safe_relative(path)
        if not source.is_file():
            raise FetchError(f"{path} is not in the SimReady mirror {self.root}.")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dest)


def default_source(revision: str = REVISION):
    mirror = os.environ.get("PAI_SIMREADY_MIRROR", "").strip()
    return MirrorSource(Path(mirror).expanduser()) if mirror else HubSource(revision)


def _scratch_dir() -> Path:
    folder = cache_root() / "tmp"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock(key: str) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.Lock())


@contextmanager
def _held(key: str, lock_file: Path):
    """One writer per package: a thread lock in this process, a file lock across the backends sharing the cache."""

    with _lock(key):
        lock_file.parent.mkdir(parents=True, exist_ok=True)
        with lock_file.open("a") as handle:
            if fcntl is not None:
                fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(handle, fcntl.LOCK_UN)


def cached_package(asset_id: str, revision: str = REVISION) -> Package | None:
    """The package when the cache holds all of it, checked by the marker and the file sizes; no network, no hashing."""

    folder = package_dir(asset_id, revision)
    try:
        marker = json.loads((folder / MARKER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if marker.get("version") != _MARKER_VERSION or marker.get("revision") != revision or marker.get("asset_id") != asset_id:
        return None
    files = marker.get("files") or {}
    for path, info in files.items():
        try:
            if (folder / path).stat().st_size != int(info["size"]):
                return None
        except (OSError, KeyError, TypeError, ValueError):
            return None
    return Package(asset_id, revision, folder, str(marker.get("package_id") or ""), str(marker["license"]), str(marker["root"]), marker.get("thumbnail"), files)


def fetch(asset_id: str, *, source=None, revision: str = REVISION) -> Package:
    """The verified package folder in the cache; downloads only when the cache does not hold all of it."""

    check_id(asset_id)
    cached = cached_package(asset_id, revision)
    if cached is not None:
        return cached
    with _held(revision + "/" + asset_id, revision_dir(revision) / "locks" / f"{asset_id}.lock"):
        # Another thread or backend may have finished the same download while this one waited.
        cached = cached_package(asset_id, revision)
        if cached is not None:
            return cached
        return _download(asset_id, source or default_source(revision), revision)


def _download(asset_id: str, source, revision: str) -> Package:
    packages = revision_dir(revision) / "packages"
    packages.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{asset_id}.partial-", dir=packages))

    def get(path: str, dest: Path) -> None:
        source.get(f"{asset_id}/{path}", dest)

    try:
        # The license comes first: a package under any other license is never downloaded.
        get(PACKAGING, stage / PACKAGING)
        packaging = _read_json(stage / PACKAGING, asset_id)
        license_id = check_license(packaging, asset_id)
        get(BOM, stage / BOM)
        verify(stage / BOM, None, _bom_hash(packaging, asset_id), f"{asset_id}'s bill of materials")
        items = _bom_items(_read_json(stage / BOM, asset_id))
        root = _root(stage, items, get, asset_id)
        thumbnail = pick_thumbnail(items, root)
        wanted = [path for path in items if needed(path, thumbnail)]

        def one(path: str) -> None:
            target = stage / path
            get(path, target)
            verify(target, items[path]["size"], items[path]["sha256"], f"{asset_id}/{path}")

        with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
            for _ in pool.map(one, wanted):
                pass
        try:
            get(LICENSE_TEXT, stage / LICENSE_TEXT)
        except FetchError:
            pass
        else:
            check_license_text(stage / LICENSE_TEXT, asset_id)
        files = {path: items[path] for path in wanted}
        # The packaging file is not in its own bill of materials; its hash is recorded for the cache key.
        files[PACKAGING] = {"size": (stage / PACKAGING).stat().st_size, "sha256": sha256_file(stage / PACKAGING)}
        marker = {
            "version": _MARKER_VERSION,
            "asset_id": asset_id,
            "revision": revision,
            "package_id": str(packaging.get("package_id") or ""),
            "license": license_id,
            "root": root,
            "thumbnail": thumbnail,
            "files": files,
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        (stage / MARKER).write_text(json.dumps(marker, indent=1), encoding="utf-8")
        final = packages / asset_id
        shutil.rmtree(final, ignore_errors=True)
        os.replace(stage, final)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return Package(asset_id, revision, final, marker["package_id"], license_id, root, thumbnail, files)


def _read_json(path: Path, asset_id: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise IntegrityError(f"{asset_id}/{path.name} is not valid JSON.") from exc
    if not isinstance(value, dict):
        raise IntegrityError(f"{asset_id}/{path.name} is not a JSON object.")
    return value


def fetch_file(asset_id: str, path: str, size: int | None, sha256: str, dest: Path, *, source=None, revision: str = REVISION) -> Path:
    """One verified file of a package, without the rest of it (the index builder, a thumbnail before the package)."""

    check_id(asset_id)
    path = safe_relative(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_name(dest.name + f".partial-{os.getpid()}-{threading.get_ident()}")
    try:
        (source or default_source(revision)).get(f"{asset_id}/{path}", partial)
        verify(partial, size, sha256, f"{asset_id}/{path}")
        os.replace(partial, dest)
    finally:
        partial.unlink(missing_ok=True)
    return dest


def thumbnail(asset_id: str, entry: dict | None = None, *, source=None, revision: str = REVISION) -> Path:
    """A 256 px WebP of the package's render, cached; from the fetched package, else the one file the index names.

    `entry` is the index row (its `thumb` is [path, size, sha256]); without it the package is fetched whole.
    """

    check_id(asset_id)
    target = revision_dir(revision) / "thumbnails" / f"{asset_id}.webp"
    if target.is_file():
        return target
    with _held("thumb/" + revision + "/" + asset_id, revision_dir(revision) / "locks" / f"{asset_id}.thumb.lock"):
        if target.is_file():
            return target
        package = cached_package(asset_id, revision)
        if package is not None and package.thumbnail_path is not None:
            original = package.thumbnail_path.read_bytes()
        elif entry and entry.get("thumb"):
            path, size, sha = entry["thumb"]
            scratch = Path(tempfile.mkdtemp(prefix="thumb-", dir=_scratch_dir()))
            try:
                original = fetch_file(asset_id, path, size, sha, scratch / "thumb.png", source=source, revision=revision).read_bytes()
            finally:
                shutil.rmtree(scratch, ignore_errors=True)
        else:
            package = fetch(asset_id, source=source, revision=revision)
            if package.thumbnail_path is None:
                raise FetchError(f"{asset_id} has no thumbnail.")
            original = package.thumbnail_path.read_bytes()
        _write_webp(original, target)
    return target


def _write_webp(png: bytes, target: Path) -> None:
    from PIL import Image

    image = Image.open(io.BytesIO(png))
    image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
    image.thumbnail((THUMB_PX, THUMB_PX), Image.Resampling.LANCZOS)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + f".partial-{os.getpid()}-{threading.get_ident()}")
    try:
        image.save(partial, "WEBP", quality=82, method=6)
        os.replace(partial, target)
    finally:
        partial.unlink(missing_ok=True)
