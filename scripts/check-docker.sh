#!/usr/bin/env bash
set -euo pipefail

if ! groups | grep -q docker; then
echo "ERROR: Your user is not in the docker group."
echo ""
echo "Run this as root:"
echo "  usermod -aG docker $(whoami)"
echo ""
echo "Then log out and log back in (or reconnect SSH)."
echo "This step is required for Docker access."
  exit 1
fi

echo "Docker permissions OK."
