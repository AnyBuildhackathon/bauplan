#!/usr/bin/env bash
# Install Isaac Sim and Isaac Lab on a RunPod RTX 4090, then smoke-test the quadcopter task.
# Run this on the pod, not on the demo Mac. Isaac Sim needs an NVIDIA RTX GPU.
# The backend expects the checkout at $HOME/IsaacLab and job logs under $HOME/pai-runs.
# Set RUN_ON_POD=1 to actually run it. Set PAI_ISAAC_FULL=1 to let the train finish.
# Without that flag the smoke stops after 900 seconds, which only proves the task started.

set -euo pipefail

if [[ "${RUN_ON_POD:-}" != "1" ]]; then
  echo "This script runs on the RunPod pod. Read the header, then set RUN_ON_POD=1." >&2
  exit 1
fi

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "Isaac Sim wheels need Linux with GLIBC 2.35 or newer." >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
  ca-certificates \
  cmake \
  curl \
  git \
  build-essential

if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  # shellcheck disable=SC1091
  source "$HOME/.local/bin/env" 2>/dev/null || true
  export PATH="$HOME/.local/bin:$PATH"
fi

if [[ ! -d "$HOME/IsaacLab/.git" ]]; then
  git clone --branch release/3.0.0 --depth 1 \
    https://github.com/isaac-sim/IsaacLab.git \
    "$HOME/IsaacLab"
fi

cd "$HOME/IsaacLab"
export OMNI_KIT_ACCEPT_EULA=YES

# Isaac Lab 3.0 installs Newton by default. The isaacsim extra pulls Isaac Sim 6.2.
# The first launch downloads extensions and can sit there for more than ten minutes.
# Driver 580 or newer, 16 GB VRAM, and an RTX 4090 match the pod this demo uses.

train=(
  uv run --extra isaacsim isaaclab train
  --rl_library rsl_rl
  --task Isaac-Quadcopter-Direct-v0
  --headless
  --video
  --video_length 200
)

if [[ "${PAI_ISAAC_FULL:-}" == "1" ]]; then
  "${train[@]}"
  exit 0
fi

set +e
timeout 900 "${train[@]}"
code=$?
set -e

if [[ "$code" -eq 0 ]]; then
  echo "Train finished inside the 900s smoke window."
elif [[ "$code" -eq 124 ]]; then
  echo "Smoke window ended after 900s. The task did start. A full train needs PAI_ISAAC_FULL=1."
else
  echo "Isaac smoke failed with exit ${code}." >&2
  exit "$code"
fi
