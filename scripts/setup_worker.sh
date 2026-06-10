#!/bin/bash

# Exit on any failure and print commands
set -e

echo "========================================================"
echo " 🚀 YOLO Distributed Worker Node Auto-Provisioning"
echo "========================================================"

# --- PRE-FLIGHT CHECKS ---
echo "--> Running System Pre-Flight Checks..."

# 1. OS Check
if ! command -v apt-get &> /dev/null; then
    echo "❌ ERROR: apt-get not found. This script requires a Debian/Ubuntu-based system."
    exit 1
fi

# 2. CUDA / NVIDIA Check
if command -v nvidia-smi &> /dev/null; then
    echo "✅ NVIDIA Drivers found. GPU Acceleration is ENABLED."
    nvidia-smi --query-gpu=name --format=csv,noheader | sed 's/^/   - /'
else
    echo "⚠️  WARNING: nvidia-smi not found! CUDA drivers are missing or no GPU is present."
    echo "   Training on this node will fallback to CPU (extremely slow)."
    read -p "   Do you want to continue anyway? (y/N): " choice
    case "$choice" in 
      y|Y ) echo "   Proceeding with CPU-only setup...";;
      * ) echo "   Aborting setup. Please install NVIDIA drivers."; exit 1;;
    esac
fi

# --- DEPENDENCIES ---
echo "--> [1/4] Installing system dependencies (SSH, Python, venv)..."
sudo apt-get update -y
sudo apt-get install -y python3-venv python3-pip openssh-server

echo "--> [2/4] Configuring and enabling SSH service..."
sudo systemctl enable ssh
sudo systemctl start ssh || echo "⚠️ Warning: Failed to start SSH service. You may need to start it manually."

# --- VIRTUAL ENVIRONMENT ---
echo "--> [3/4] Building Python Virtual Environment..."
VENV_DIR="$HOME/venv"

if [ -d "$VENV_DIR" ]; then
    echo "    Virtual environment exists. Verifying integrity..."
    if [ ! -f "$VENV_DIR/bin/activate" ] || [ ! -x "$VENV_DIR/bin/python" ]; then
        echo "❌ ERROR: Existing venv is corrupted. Rebuilding..."
        rm -rf "$VENV_DIR"
        python3 -m venv "$VENV_DIR"
    else
        echo "✅ Venv integrity check passed."
    fi
else
    echo "    Creating new virtual environment at $VENV_DIR..."
    python3 -m venv "$VENV_DIR"
fi

# Activate and verify python version
source "$VENV_DIR/bin/activate"
PYTHON_VERSION=$(python --version)
echo "    Using $PYTHON_VERSION"

# --- ML PACKAGES ---
echo "--> [4/4] Installing ML Dependencies (PyTorch, Ultralytics)..."
pip install --upgrade pip

# Install PyTorch (defaulting to CUDA 12.1 pip index, safe fallback if no GPU)
pip install torch torchvision ultralytics requests --index-url https://download.pytorch.org/whl/cu121

echo "========================================================"
echo " ✅ Worker Node Successfully Provisioned & Ready!"
echo "========================================================"
echo ""
echo "This machine is now ready to accept distributed training jobs."
echo "To allow the Master Orchestrator to connect automatically, you must"
echo "share the Master's SSH key with this worker."
echo ""
echo "Run the following command ON YOUR MASTER NODE:"
echo -e "\033[1;32m   ssh-copy-id $(whoami)@$(hostname -I | awk '{print $1}')\033[0m"
echo "========================================================"
