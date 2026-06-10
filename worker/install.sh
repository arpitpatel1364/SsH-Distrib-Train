#!/bin/bash
# Worker installation shell script

echo "=== Installing system packages ==="
sudo apt-get update
sudo apt-get install -y python3-pip python3-dev build-essential

echo "=== Installing Python dependencies ==="
pip3 install -r $(dirname "$0")/requirements.txt

echo "=== Worker installation complete ==="
