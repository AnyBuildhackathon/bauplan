#!/usr/bin/env bash
# Installs SparkBench for the circuit_design tool: bash agent/scripts/setup_sparkbench.sh
# Clones github.com/dennisonbertram/sparkbench at one pinned commit outside the repository,
# installs its npm packages without running their install scripts, then the bridge's own tsx.
# The checkout lands in ~/.cache/anybuild/sparkbench/<commit> unless SPARKBENCH_DIR names
# another folder; agent/src/pai_agent/sparkbench.py looks in the same place.
# This is the only step that needs the network; circuit_design and its tests run offline.
set -euo pipefail

commit=6dd92371aeb2ae6cc5c2dbe04a1fc84a448d315a
repo=https://github.com/dennisonbertram/sparkbench.git
bridge="$(cd "$(dirname "${BASH_SOURCE[0]}")/../sparkbench" && pwd)"
target="${SPARKBENCH_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/anybuild/sparkbench/$commit}"

if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
  echo "Node.js 20 or newer with npm is missing: install it (macOS: brew install node), then run this again." >&2
  exit 1
fi
major="$(node -p 'process.versions.node.split(".")[0]')"
if (( major < 20 )); then
  echo "Node.js $(node --version) is too old: SparkBench needs Node.js 20 or newer." >&2
  exit 1
fi
if ! command -v git >/dev/null 2>&1; then
  echo "git is missing: install it, then run this again." >&2
  exit 1
fi
if [[ -e "$target" && ! -d "$target/.git" ]]; then
  echo "$target exists but is not a SparkBench checkout. Remove it and run this again." >&2
  exit 1
fi

if [[ ! -d "$target/.git" ]]; then
  partial="$target.partial-$$"
  trap 'rm -rf "$partial"' EXIT
  rm -rf "$partial"
  mkdir -p "$partial"
  git -C "$partial" init -q
  git -C "$partial" remote add origin "$repo"
  git -C "$partial" fetch -q --depth 1 origin "$commit"
  git -C "$partial" -c advice.detachedHead=false checkout -q FETCH_HEAD
  mv "$partial" "$target"
  trap - EXIT
fi
found="$(git -C "$target" rev-parse HEAD)"
if [[ "$found" != "$commit" ]]; then
  echo "$target holds SparkBench $found, not the pinned $commit. Remove the folder and run this again." >&2
  exit 1
fi

# npm ci in a folder unless its packages already match its lockfile, so a second run leaves a working install alone.
install() {
  local folder="$1" stamp="$1/node_modules/.anybuild-lock" lock
  lock="$(node -e 'process.stdout.write(require("crypto").createHash("sha256").update(require("fs").readFileSync(process.argv[1])).digest("hex"))' "$folder/package-lock.json")"
  if [[ -f "$stamp" && "$(cat "$stamp")" == "$lock" ]]; then
    return
  fi
  npm ci --prefix "$folder" --ignore-scripts --no-audit --no-fund --loglevel=error
  printf '%s\n' "$lock" > "$stamp"
}
install "$target"
install "$bridge"
echo "SparkBench ${commit:0:7} is ready in $target"
