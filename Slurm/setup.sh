#!/bin/bash

# Exit instantly if any step fails
set -e

echo "=== 1. Updating System Packages ==="
sudo apt update && sudo apt upgrade -y

echo "=== 2. Installing Docker Engine ==="
sudo apt install -y docker.io

echo "=== 3. Configuring User Group Permissions ==="
sudo usermod -aG docker $USER

echo "=== 4. Installing Docker Compose ==="
sudo apt update && sudo apt install -y docker-compose-v2
sudo ln -sf /usr/libexec/docker/cli-plugins/docker-compose /usr/local/bin/docker-compose
hash -r
docker-compose version

echo "=== 5. Verifying Installation Versions ==="
docker --version
docker-compose version

echo "=== 6. Navigating to PolyScope X Workspace ==="
cd /work/EventsSimulation/polyscopex-sdk-0.20.49

echo "=== 7. Building the PolyScope X Base Developer Image ==="
docker build --network=host -t polyscopex-env -f .devcontainer/Dockerfile .devcontainer/

echo "========================================================="
echo " SETUP COMPLETE! All simulation services are running."
echo " Use 'docker ps' to inspect active containers."
echo "========================================================="

