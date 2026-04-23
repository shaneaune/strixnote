#!/usr/bin/env bash
set -euo pipefail

USER_NAME="$(whoami)"

if groups | grep -qw docker; then
  echo "Docker permissions OK."
  exit 0
fi

if getent group docker | grep -qw "$USER_NAME"; then
  if [[ $# -gt 0 ]]; then
    echo "Refreshing docker group for current shell..."
    exec sg docker -c "STRIXNOTE_DOCKER_OK=1 $*"
  else
    echo "ERROR: Docker group membership exists but is not active in this shell."
    echo ""
    echo "Run the install again after logging out and back in,"
    echo "or re-run it through sg docker."
    exit 1
  fi
fi

echo "ERROR: Your user is not in the docker group."
echo ""
echo "Run this as root:"
echo "  usermod -aG docker $USER_NAME"
echo ""
echo "Then log out and log back in (or reconnect SSH)."
echo "This step is required for Docker access."
exit 1
