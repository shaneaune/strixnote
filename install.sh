#!/usr/bin/env bash
set -euo pipefail

# Prevent recursive sg docker loop
if [[ "${STRIXNOTE_DOCKER_OK:-}" != "1" ]]; then
  export STRIXNOTE_DOCKER_OK=1
else
  echo "Docker group applied."
fi

echo "=== StrixNote Install ==="

GPU_MODE=0
HELPER_MODE=0

for arg in "$@"; do
  case "$arg" in
    --gpu)
      GPU_MODE=1
      ;;
    --helper)
      HELPER_MODE=1
      ;;
    *)
      echo "Usage: $0 [--gpu] [--helper]"
      exit 1
      ;;
  esac
done

if [ "$GPU_MODE" -eq 1 ]; then
  echo "Installation mode: NVIDIA GPU"
else
  echo "Installation mode: CPU"
fi

if [ "$HELPER_MODE" -eq 1 ] && [ "$GPU_MODE" -ne 1 ]; then
  echo "ERROR: --helper may only be used together with --gpu."
  exit 1
fi

# Persistent installation progress
if [ "$GPU_MODE" -eq 1 ]; then
  INSTALL_MODE="gpu"
else
  INSTALL_MODE="cpu"
fi

INSTALL_STATE_VERSION=1
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/strixnote"
STATE_FILE="$STATE_DIR/install-state-$INSTALL_MODE"
INSTALL_STAGE="none"

mkdir -p "$STATE_DIR"

if [ -f "$STATE_FILE" ]; then
  # shellcheck disable=SC1090
  source "$STATE_FILE"

  if [ "${INSTALL_VERSION:-}" != "$INSTALL_STATE_VERSION" ]; then
    echo "WARNING: Incompatible installer state found at $STATE_FILE"
    echo "Starting again from the beginning."
    INSTALL_STAGE="none"
  elif [ "${INSTALL_MODE_SAVED:-}" != "$INSTALL_MODE" ]; then
    echo "WARNING: Installer mode does not match the saved state."
    echo "Starting again from the beginning."
    INSTALL_STAGE="none"
  else
    INSTALL_STAGE="${INSTALL_STAGE_SAVED:-none}"
  fi
fi

checkpoint_rank() {
  case "$1" in
    none)                   echo 0 ;;
    base-complete)          echo 10 ;;
    gpu-driver-installed)   echo 20 ;;
    gpu-awaiting-proxmox)   echo 30 ;;
    gpu-validation)         echo 35 ;;
    gpu-runtime-installed)  echo 40 ;;
    strixnote-installed)    echo 50 ;;
    complete)               echo 60 ;;
    *)                      echo -1 ;;
  esac
}

stage_is_complete() {
  local checkpoint="$1"
  local current_rank
  local requested_rank

  current_rank="$(checkpoint_rank "$INSTALL_STAGE")"
  requested_rank="$(checkpoint_rank "$checkpoint")"

  if [ "$current_rank" -lt 0 ] || [ "$requested_rank" -lt 0 ]; then
    echo "ERROR: Unknown installer checkpoint."
    echo "Current checkpoint: $INSTALL_STAGE"
    echo "Requested checkpoint: $checkpoint"
    exit 1
  fi

  [ "$current_rank" -ge "$requested_rank" ]
}

mark_stage_complete() {
  local checkpoint="$1"

  cat > "$STATE_FILE" <<EOF
INSTALL_VERSION=$INSTALL_STATE_VERSION
INSTALL_MODE_SAVED=$INSTALL_MODE
INSTALL_STAGE_SAVED=$checkpoint
EOF

  INSTALL_STAGE="$checkpoint"
}

begin_checkpoint() {
  local checkpoint="$1"
  local description="$2"

  if stage_is_complete "$checkpoint"; then
    echo "Checkpoint already complete: $checkpoint. Skipping."
    return 1
  fi

  echo ""
  echo "=== $description ==="
  return 0
}

complete_checkpoint() {
  local checkpoint="$1"

  mark_stage_complete "$checkpoint"
  echo "Checkpoint complete: $checkpoint"
}

echo "Installer checkpoint: $INSTALL_STAGE"

if begin_checkpoint "base-complete" "Base configuration and Docker prerequisites"; then

# Ensure .env exists
if [ ! -f .env ]; then
  echo "Creating .env from .env.example..."
  cp .env.example .env
fi

# Configure Whisper defaults for the selected installation mode
if [ "$GPU_MODE" -eq 1 ]; then
  echo "Configuring Whisper for NVIDIA GPU..."
  sed -i "s/^WHISPER_DEVICE=.*/WHISPER_DEVICE=cuda/" .env
  sed -i "s/^WHISPER_COMPUTE=.*/WHISPER_COMPUTE=float16/" .env

  if grep -q "^STRIXNOTE_GPU=" .env; then
    sed -i "s/^STRIXNOTE_GPU=.*/STRIXNOTE_GPU=1/" .env
  else
    echo "STRIXNOTE_GPU=1" >> .env
  fi
else
  echo "Configuring Whisper for CPU..."
  sed -i "s/^WHISPER_DEVICE=.*/WHISPER_DEVICE=cpu/" .env
  sed -i "s/^WHISPER_COMPUTE=.*/WHISPER_COMPUTE=int8/" .env

  if grep -q "^STRIXNOTE_GPU=" .env; then
    sed -i "s/^STRIXNOTE_GPU=.*/STRIXNOTE_GPU=0/" .env
  else
    echo "STRIXNOTE_GPU=0" >> .env
  fi
fi

# Apply environment overrides
WEB_PORT="${STRIXNOTE_WEB_PORT:-8080}"

echo "Setting STRIXNOTE_WEB_PORT=$WEB_PORT"
sed -i "s/^STRIXNOTE_WEB_PORT=.*/STRIXNOTE_WEB_PORT=$WEB_PORT/" .env

# Ensure openssl is available
if ! command -v openssl >/dev/null 2>&1; then
  echo "Installing openssl..."
  sudo apt update
  sudo apt install -y openssl
fi

# Ensure MEILI_MASTER_KEY exists
if ! grep -Eq "^MEILI_MASTER_KEY=.+$" .env; then
  echo "Generating Meilisearch master key..."
  KEY="$(openssl rand -hex 32)"

  if grep -q "^MEILI_MASTER_KEY=" .env; then
    # Replace existing (empty or invalid) line safely
    sed -i "s|^MEILI_MASTER_KEY=.*$|MEILI_MASTER_KEY=$KEY|" .env
  else
    # Add cleanly with proper newline
    printf '\n# Meilisearch\nMEILI_MASTER_KEY=%s\n' "$KEY" >> .env
  fi
fi

# Ensure required packages are installed
if ! command -v docker >/dev/null 2>&1; then
  echo "Installing Docker and required packages..."
  sudo apt update
  sudo apt install -y sudo docker.io git curl gpg pciutils mokutil
  sudo systemctl enable docker
  sudo systemctl start docker
  sudo usermod -aG sudo "$(whoami)"
  sudo usermod -aG docker "$(whoami)"
fi

# Ensure Docker Compose is available
if ! docker compose version >/dev/null 2>&1 && ! command -v docker-compose >/dev/null 2>&1; then
  echo "Installing Docker Compose..."
  sudo apt update
  if apt-cache show docker-compose-v2 >/dev/null 2>&1; then
    sudo apt install -y docker-compose-v2
  elif apt-cache show docker-compose-plugin >/dev/null 2>&1; then
    sudo apt install -y docker-compose-plugin
  else
    sudo apt install -y docker-compose
  fi
fi

# Refresh docker group for current shell if needed
if ! groups | grep -qw docker && getent group docker | grep -qw "$(whoami)"; then
  echo "Refreshing docker group for current shell..."
  exec sg docker -c "STRIXNOTE_DOCKER_OK=1 $0 $*"
fi

# Check Docker permissions
./scripts/check-docker.sh "$0" "$@"

complete_checkpoint "base-complete"
fi

# GPU installation: install the NVIDIA driver before the Proxmox pause
if [ "$GPU_MODE" -eq 1 ]; then
  if begin_checkpoint "gpu-driver-installed" "Install NVIDIA driver"; then
    echo "Enabling Debian contrib and non-free repositories..."

    if [ -f /etc/apt/sources.list.d/debian.sources ]; then
      sudo sed -Ei '/^Components:/ {
        /(^|[[:space:]])contrib([[:space:]]|$)/! s/$/ contrib/
        /(^|[[:space:]])non-free([[:space:]]|$)/! s/$/ non-free/
        /(^|[[:space:]])non-free-firmware([[:space:]]|$)/! s/$/ non-free-firmware/
      }' /etc/apt/sources.list.d/debian.sources
    fi

    if [ -f /etc/apt/sources.list ]; then
      sudo sed -Ei '/^[[:space:]]*deb(-src)?[[:space:]]/ {
        /(^|[[:space:]])contrib([[:space:]]|$)/! s/$/ contrib/
        /(^|[[:space:]])non-free([[:space:]]|$)/! s/$/ non-free/
        /(^|[[:space:]])non-free-firmware([[:space:]]|$)/! s/$/ non-free-firmware/
      }' /etc/apt/sources.list
    fi

    sudo apt update
    sudo apt install -y \
      "linux-headers-$(uname -r)" \
      dkms \
      nvidia-driver \
      firmware-misc-nonfree

    complete_checkpoint "gpu-driver-installed"
  fi

  if ! stage_is_complete "gpu-awaiting-proxmox"; then
    mark_stage_complete "gpu-awaiting-proxmox"

    if [ "$HELPER_MODE" -eq 1 ]; then
      echo "Automated Proxmox configuration detected."
      echo "Skipping the manual GPU passthrough pause."
    else
      echo ""
      echo "============================================================"
      echo "One-time Proxmox configuration is now required."
      echo "============================================================"
      echo ""
      echo "1. Shut down this virtual machine."
      echo "2. Pass the NVIDIA GPU through to the virtual machine."
      echo "3. Remove the existing EFI disk."
      echo "4. Add a new EFI disk using the same storage."
      echo "5. Leave Pre-Enroll keys unchecked."
      echo "6. Start the virtual machine."
      echo "7. Return to the StrixNote directory and run:"
      echo ""
      echo "   ./install.sh --gpu"
      echo ""
      echo "The installer will resume from checkpoint: gpu-awaiting-proxmox"
      exit 0
    fi
  fi

  if begin_checkpoint "gpu-validation" "Validate GPU passthrough and EFI configuration"; then
    VALIDATION_FAILED=0

    echo "Checking UEFI boot mode..."
    if [ -d /sys/firmware/efi ]; then
      echo "PASS: The virtual machine is booted using UEFI."
    else
      echo "ERROR: The virtual machine is not booted using UEFI."
      echo "Recreate the EFI disk in Proxmox and boot the virtual machine again."
      VALIDATION_FAILED=1
    fi

    echo "Checking Secure Boot status..."
    if [ -d /sys/firmware/efi ]; then
      SECURE_BOOT_STATUS="$(mokutil --sb-state 2>&1 || true)"

      if echo "$SECURE_BOOT_STATUS" | grep -qi "SecureBoot disabled"; then
        echo "PASS: Secure Boot is disabled."
      else
        echo "ERROR: Secure Boot is not confirmed as disabled."
        echo "Reported status: $SECURE_BOOT_STATUS"
        echo "Recreate the EFI disk with Pre-Enroll keys unchecked."
        VALIDATION_FAILED=1
      fi
    fi

    echo "Checking for a passed-through NVIDIA GPU..."
    if lspci -nn | grep -qi "NVIDIA"; then
      echo "PASS: An NVIDIA PCI device is present."
    else
      echo "ERROR: No NVIDIA PCI device was detected."
      echo "Confirm that the GPU is passed through to this virtual machine in Proxmox."
      VALIDATION_FAILED=1
    fi

    echo "Checking the NVIDIA driver..."
    if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
      echo "PASS: The NVIDIA driver can communicate with the GPU."
      nvidia-smi
    else
      echo "ERROR: nvidia-smi could not communicate with the NVIDIA GPU."
      echo "Confirm GPU passthrough, EFI configuration, and that Pre-Enroll keys are disabled."
      VALIDATION_FAILED=1
    fi

    if [ "$VALIDATION_FAILED" -ne 0 ]; then
      echo ""
      echo "GPU validation failed. The installer will not continue."
      echo "Correct the errors above, reboot if necessary, and run:"
      echo ""
      echo "  ./install.sh --gpu"
      exit 1
    fi

    complete_checkpoint "gpu-validation"
  fi

fi

# Install and configure NVIDIA Container Toolkit
if [ "$GPU_MODE" -eq 1 ]; then
  if begin_checkpoint "gpu-runtime-installed" "Install NVIDIA Container Toolkit"; then
    echo "Adding the NVIDIA Container Toolkit repository..."

    curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey |
      sudo gpg --dearmor --yes \
        -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg

    curl -fsSL \
      https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list |
      sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' |
      sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list >/dev/null

    sudo apt update
    sudo apt install -y nvidia-container-toolkit

    echo "Configuring the NVIDIA runtime for Docker..."
    sudo nvidia-ctk runtime configure --runtime=docker
    sudo systemctl restart docker

    echo "Testing GPU access from Docker..."
    if ! docker run --rm --gpus all \
      nvidia/cuda:12.6.3-base-ubuntu22.04 \
      nvidia-smi; then
      echo ""
      echo "ERROR: Docker could not access the NVIDIA GPU."
      echo "The NVIDIA Container Toolkit was installed, but its test failed."
      echo "Correct the error and rerun:"
      echo ""
      echo "  ./install.sh --gpu"
      exit 1
    fi

    complete_checkpoint "gpu-runtime-installed"
  fi
fi

# Initialize data folders
./scripts/init-data.sh

# Start containers
./scripts/dc.sh up -d

echo "Waiting for Meilisearch to become ready..."
READY=0
for i in $(seq 1 30); do
  if ./scripts/dc.sh exec -T meilisearch /bin/sh -c "wget -qO- http://127.0.0.1:7700/health >/dev/null 2>&1"; then
    echo "Meilisearch is ready."
    READY=1
    break
  fi
  sleep 2
done

if [ "$READY" -ne 1 ]; then
  echo "ERROR: Meilisearch did not become ready."
  echo "Check logs with: ./scripts/dc.sh logs"
  exit 1
fi

echo "Applying Meilisearch schema..."
./scripts/dc.sh exec -T upload_api python - <<'PY'
from app import ensure_meili_schema
import json
result = ensure_meili_schema()
print(json.dumps(result, indent=2))
if not result.get("ok"):
    raise SystemExit(1)
PY

# Run maigration script
echo "Running data migrations..."
./scripts/dc.sh exec -T upload_api python /app_host/scripts/migrate.py || true

# initialize index version
echo "Checking search index version..."
./scripts/index-version.sh

# Preload model
echo "Preloading Whisper model..."
./scripts/preload-model.sh

echo ""
echo "Container status:"
./scripts/dc.sh ps

echo "+------------------------------------------------------------------------------+"
echo "|      /\___/\        ____  _        _      _   _       _                      |"
echo "|     /  o o  \      / ___|| |_ _ __(_)_  _| \ | | ___ | |_ ___                |"
echo "|    |   \^/   |     \___ \| __| '__| \ \/ /  \| |/ _ \| __/ _ \               |"
echo "|    |  (___)  |      ___) | |_| |  | |>  <| |\  | (_) | ||  __/               |"
echo "|    |  /   \  |     |____/ \__|_|  |_/_/\_\_| \_|\___/ \__\___|               |"
echo "|    |_/|_|_|\_|                                                               |"
echo "+------------------------------------------------------------------------------+"
IP=$(hostname -I | awk '{print $1}')

echo ""
echo "Container status:"
./scripts/dc.sh ps

echo ""
echo "Install complete."

if [ -n "$IP" ]; then
  echo "Open StrixNote at: http://$IP:${STRIXNOTE_WEB_PORT:-8080}"
else
  echo "Open StrixNote at: http://<your-server-ip>:${STRIXNOTE_WEB_PORT:-8080}"
fi

echo ""
echo "The Whisper model has been preloaded."
echo "You can open the page and try your first upload now."
