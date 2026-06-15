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
echo "--> [1/4] Checking system dependencies (SSH, Python, venv)..."

NEED_SYSTEM_INSTALL=false
if ! python3 -c "import venv" &> /dev/null; then
    echo "   - python3-venv is missing."
    NEED_SYSTEM_INSTALL=true
fi
if ! python3 -c "import pip" &> /dev/null; then
    echo "   - python3-pip is missing."
    NEED_SYSTEM_INSTALL=true
fi
if ! command -v sshd &> /dev/null; then
    echo "   - openssh-server is missing."
    NEED_SYSTEM_INSTALL=true
fi

if [ "$NEED_SYSTEM_INSTALL" = true ]; then
    echo "    Attempting to install missing system dependencies..."
    if [ "$EUID" -ne 0 ] && ! command -v sudo &> /dev/null; then
        echo "❌ ERROR: sudo is not available and system dependencies are missing. Please install python3-venv, python3-pip, and openssh-server manually."
        exit 1
    fi
    sudo apt-get update -y
    sudo apt-get install -y python3-venv python3-pip openssh-server
else
    echo "✅ All required system packages (venv, pip, SSH) are already installed."
fi

echo "--> [2/4] Configuring and enabling SSH service..."
if command -v systemctl &> /dev/null; then
    if systemctl is-active --quiet ssh; then
        echo "✅ SSH service is already running."
    else
        if [ "$EUID" -eq 0 ] || command -v sudo &> /dev/null; then
            sudo systemctl enable ssh
            sudo systemctl start ssh || echo "⚠️ Warning: Failed to start SSH service. You may need to start it manually."
        else
            echo "⚠️ Warning: SSH service is not running and sudo is not available to start it."
        fi
    fi
else
    echo "⚠️ Warning: systemctl not found. Please ensure SSH daemon is running."
fi

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

# --- POST-INSTALLATION VALIDATION ---
echo "--> Verifying ML environment status..."
if python -c "import torch; import requests; import ultralytics" &> /dev/null; then
    echo "✅ Core packages (PyTorch, Requests, Ultralytics) successfully verified."
    CUDA_AVAIL=$(python -c "import torch; print(torch.cuda.is_available())")
    if [ "$CUDA_AVAIL" = "True" ]; then
        echo "✅ PyTorch CUDA acceleration is active and working."
    else
        echo "⚠️  PyTorch is running on CPU-only mode."
    fi
else
    echo "❌ ERROR: Verification failed. Some dependencies did not install correctly."
    exit 1
fi

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
echo ""
echo "To start the worker agent manually, run:"
echo -e "\033[1;32m   ./run.sh <MASTER_URL>\033[0m"
echo "========================================================"

# Interactive prompt to run agent immediately
if [ -t 0 ]; then
    echo ""
    read -p "Would you like to start the worker agent now? (y/N): " run_now
    if [[ "$run_now" =~ ^[yY]$ ]]; then
        echo "--> Starting worker agent..."
        # Locate run.sh in the same directory as this setup_worker.sh script
        SCRIPT_DIR="$(dirname "$0")"
        if [ -x "$SCRIPT_DIR/run.sh" ]; then
            exec "$SCRIPT_DIR/run.sh"
        else
            exec bash "$SCRIPT_DIR/run.sh"
        fi
    fi
fi
