#!/usr/bin/env bash
# Installs SolidCraft's headless solidcraft-cli for solidcraft_part and export_urdf: bash agent/scripts/setup_solidcraft.sh
# Downloads the pinned release from github.com/tangency-labs/solidcraft, checks its SHA-256 and keeps only the CLI
# and its licence texts, outside the repository: ~/.cache/anybuild/solidcraft/<version> unless SOLIDCRAFT_DIR names
# another folder; agent/src/pai_agent/solidcraft.py looks in the same place. On macOS the universal binary is thinned
# to this Mac's architecture with lipo, which halves it. This is the only step that needs the network.
set -euo pipefail

version=0.23.0
release="https://github.com/tangency-labs/solidcraft/releases/download/v$version"
target="${SOLIDCRAFT_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/anybuild/solidcraft/$version}"

# The release asset for this machine, its SHA-256 from the release, and the folder inside it that holds the CLI.
case "$(uname -s)-$(uname -m)" in
  Darwin-*)
    asset="solidcraft-cli-$version-macos-universal.zip"
    sha256=cf2df85cc35f11c443ed5dd2ca480075e1224f2a73c947ecb1bb7cdd0eb82197
    inside="solidcraft-cli-$version-macos-universal"
    ;;
  Linux-x86_64)
    asset="solidcraft-$version-linux-x86_64.tar.gz"
    sha256=819d5de0943146968bf963f174f2fd371b4f41e6c5c8646afce691bc6bd0ea5e
    inside="solidcraft-$version-linux-x86_64/bin"
    ;;
  Linux-aarch64 | Linux-arm64)
    asset="solidcraft-$version-linux-aarch64.tar.gz"
    sha256=c096f2821eb6a0327ba48de72e2a7bde92172a07c4c00b5ddeba392e47624261
    inside="solidcraft-$version-linux-aarch64/bin"
    ;;
  *)
    echo "SolidCraft $version has no release build for $(uname -s) $(uname -m)." >&2
    echo "Build it from source (cargo build --release -p solidcraft-cli at tag v$version) and set SOLIDCRAFT_CLI to the binary." >&2
    exit 1
    ;;
esac

if [[ -x "$target/solidcraft-cli" ]] && [[ "$("$target/solidcraft-cli" --version 2>/dev/null)" == "solidcraft-cli $version" ]]; then
  echo "solidcraft-cli $version is ready in $target"
  exit 0
fi
if [[ -e "$target" ]]; then
  echo "$target exists but holds no working solidcraft-cli $version. Remove it and run this again." >&2
  exit 1
fi
for tool in curl unzip tar; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "$tool is missing: install it, then run this again." >&2
    exit 1
  fi
done

partial="$target.partial-$$"
trap 'rm -rf "$partial"' EXIT
rm -rf "$partial"
mkdir -p "$partial/download" "$partial/unpacked" "$partial/out"
curl -fsSL --retry 3 -o "$partial/download/$asset" "$release/$asset"
if command -v shasum >/dev/null 2>&1; then
  found="$(shasum -a 256 "$partial/download/$asset" | cut -d ' ' -f 1)"
else
  found="$(sha256sum "$partial/download/$asset" | cut -d ' ' -f 1)"
fi
if [[ "$found" != "$sha256" ]]; then
  echo "$asset has SHA-256 $found, not the release's $sha256. Nothing was installed." >&2
  exit 1
fi
case "$asset" in
  *.zip) unzip -q "$partial/download/$asset" -d "$partial/unpacked" ;;
  *) tar -xzf "$partial/download/$asset" -C "$partial/unpacked" ;;
esac

cli="$partial/unpacked/$inside/solidcraft-cli"
if [[ "$(uname -s)" == "Darwin" ]] && command -v lipo >/dev/null 2>&1; then
  lipo -thin "$(uname -m)" -output "$partial/out/solidcraft-cli" "$cli"
else
  cp "$cli" "$partial/out/solidcraft-cli"
fi
chmod 755 "$partial/out/solidcraft-cli"
# The licence texts travel with the binary: MIT or Apache-2.0, the NOTICE and every dependency's licence.
licences="$(find "$partial/unpacked" -type f \( -name 'LICENSE-*' -o -name NOTICE -o -name 'THIRD-PARTY-LICENSES.txt' \))"
if [[ -z "$licences" ]]; then
  echo "$asset holds no licence texts; it is not the release this script expects. Nothing was installed." >&2
  exit 1
fi
while IFS= read -r file; do
  cp "$file" "$partial/out/"
done <<< "$licences"

found="$("$partial/out/solidcraft-cli" --version)"
if [[ "$found" != "solidcraft-cli $version" ]]; then
  echo "The downloaded CLI says '$found', not solidcraft-cli $version. Nothing was installed." >&2
  exit 1
fi
mkdir -p "$(dirname "$target")"
mv "$partial/out" "$target"
echo "solidcraft-cli $version is ready in $target"
