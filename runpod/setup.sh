#!/usr/bin/env bash
# Run on Ubuntu 22.04+ RTX (RunPod, NVIDIA Brev or an Isaac Sim container):
# RUN_ON_POD=1 bash runpod/setup.sh
# Installs a pinned compatible Isaac stack. No training starts during setup.
set -euo pipefail
if [[ "${RUN_ON_POD:-}" != "1" || "$(uname -s)" != "Linux" ]]; then
  echo "Run this on the Linux RTX pod with RUN_ON_POD=1." >&2
  exit 1
fi
nvidia-smi
driver=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -n 1)
if [[ "$driver" == 595.* ]]; then
  echo "Isaac Sim 5.1 RTX cameras crash with driver $driver. Use a host with the validated Linux driver 580.65.06; a container cannot replace the host driver." >&2
  exit 1
fi
export DEBIAN_FRONTEND=noninteractive
privilege=()
if [[ "$(id -u)" != "0" ]]; then
  privilege=(sudo)
fi
"${privilege[@]}" apt-get update
"${privilege[@]}" apt-get install -y --no-install-recommends ca-certificates cmake curl git build-essential \
  ffmpeg libgl1 libglib2.0-0 libxrender1 libxi6 libxkbcommon0 libsm6 libice6 libegl1 libvulkan1 vulkan-tools \
  libglu1-mesa libx11-6 libxext6 libxt6 libxrandr2 libxinerama1 libxcursor1 libnss3 libfreetype6
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:$PATH"
venv="$HOME/.venvs/anybuild-isaac"
if [[ ! -x "$venv/bin/python" ]]; then
  uv venv --seed --python 3.11 "$venv"
fi
uv pip install --python "$venv/bin/python" pip
uv pip install --python "$venv/bin/python" 'isaacsim[all,extscache]==5.1.0' --extra-index-url https://pypi.nvidia.com
if [[ ! -d "$HOME/IsaacLab/.git" ]]; then
  git clone --branch v2.3.0 --depth 1 https://github.com/isaac-sim/IsaacLab.git "$HOME/IsaacLab"
fi
if [[ "$(git -C "$HOME/IsaacLab" describe --tags --exact-match)" != "v2.3.0" ]]; then
  echo 'Existing IsaacLab checkout must be v2.3.0; use a fresh pod or prepare that version.' >&2
  exit 1
fi
export VIRTUAL_ENV="$venv"
export PATH="$venv/bin:$PATH"
export OMNI_KIT_ACCEPT_EULA=YES
export ACCEPT_EULA=Y
# New TensorDict releases otherwise upgrade Torch beyond the supported Isaac stack.
constraints=$(mktemp)
build_constraints=$(mktemp)
trap 'rm -f "$constraints" "$build_constraints"' EXIT
cat > "$constraints" <<'EOF'
torch==2.7.0
torchvision==0.22.0
torchaudio==2.7.0
tensordict==0.8.3
EOF
# FlatDict 4.0.1's setup imports pkg_resources, removed by setuptools 81.
echo 'setuptools<81' > "$build_constraints"
# Install explicitly: the upstream shell installer can hide an extension build failure.
uv pip install --python "$venv/bin/python" --constraint "$constraints" \
  --build-constraint "$build_constraints" --extra-index-url https://download.pytorch.org/whl/cu128 \
  'torch==2.7.0+cu128' 'torchvision==0.22.0+cu128' 'torchaudio==2.7.0+cu128' \
  -e "$HOME/IsaacLab/source/isaaclab" -e "$HOME/IsaacLab/source/isaaclab_assets" \
  -e "$HOME/IsaacLab/source/isaaclab_tasks" -e "$HOME/IsaacLab/source/isaaclab_mimic" \
  -e "$HOME/IsaacLab/source/isaaclab_rl[rsl_rl]"
uv pip install --python "$venv/bin/python" 'imageio[ffmpeg]' tensorboard
# Initial Kit/extension startup is bounded, and errors are never reported as success.
timeout --kill-after=15s 600s "$venv/bin/python" -c \
  'from isaaclab.app import AppLauncher; app = AppLauncher(headless=True, enable_cameras=True).app; app.close()'
echo 'AnyBuild GPU environment ready. Set ISAAC_SSH_HOST, ISAAC_SSH_PORT and ISAAC_SSH_USER on the Mac.'
