#!/bin/bash
# Master node setup installer

# Change to the project root directory
cd "$(dirname "$0")/.."

echo "=== Creating Virtual Environment ==="
python3 -m venv venv
source venv/bin/activate

echo "=== Installing dependencies ==="
pip install --upgrade pip
pip install -r requirements.txt

echo "=== Setup complete ==="

