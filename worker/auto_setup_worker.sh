#!/bin/bash
set -e

# Disable interactive prompts
export DEBIAN_FRONTEND=noninteractive

echo "========================================================"
echo " 🚀 YOLO Distributed Worker Node Auto-Provisioning"
echo "========================================================"

echo "--> [1/5] Checking and Installing System Dependencies..."
if [ "$EUID" -ne 0 ] && ! command -v sudo &> /dev/null; then
    echo "❌ ERROR: sudo is required but not available."
    exit 1
fi

sudo apt-get update -y

# Check and install python tools
echo "   -> Installing basic tools (venv, pip, curl)..."
sudo apt-get install -y python3-venv python3-pip openssh-server curl systemd

# Check for NVIDIA/CUDA tools
if command -v nvidia-smi &> /dev/null; then
    echo "   -> NVIDIA drivers found. Checking for CUDA toolkit..."
    if ! command -v nvcc &> /dev/null; then
        echo "   -> nvcc (CUDA toolkit) not found. Installing nvidia-cuda-toolkit..."
        sudo apt-get install -y nvidia-cuda-toolkit
    else
        echo "   -> CUDA toolkit is already installed."
    fi
else
    echo "   -> No NVIDIA GPU detected. Skipping CUDA toolkit installation."
fi

echo "--> [2/5] Creating directories..."
WORKER_DIR="$HOME/worker"
VENV_DIR="$HOME/venv"
mkdir -p "$WORKER_DIR"

echo "--> [3/5] Setting up Python Virtual Environment..."
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"

echo "--> [4/5] Installing Python dependencies..."
if [ -f "$WORKER_DIR/requirements.txt" ]; then
    pip install -r "$WORKER_DIR/requirements.txt"
else
    pip install ultralytics torch torchvision torchaudio fastapi uvicorn requests psutil pynvml pydantic
fi

echo "--> [5/5] Configuring systemd service..."
MASTER_IP=$(echo $SSH_CONNECTION | awk '{print $1}')
MASTER_URL="http://${MASTER_IP}:8000"

SERVICE_FILE="/tmp/cactus-worker.service"
cat <<EOF > "$SERVICE_FILE"
[Unit]
Description=Cactus Worker Agent
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$WORKER_DIR
Environment="PATH=$VENV_DIR/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
ExecStart=$VENV_DIR/bin/python worker.py --master $MASTER_URL --ssh-user $USER
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo mv "$SERVICE_FILE" /etc/systemd/system/cactus-worker.service

echo "--> [6/5] Configuring passwordless systemctl for worker service..."
SUDOERS_FILE="/etc/sudoers.d/99-cactus-worker"
echo "$USER ALL=(ALL) NOPASSWD: /bin/systemctl start cactus-worker.service, /bin/systemctl stop cactus-worker.service, /bin/systemctl restart cactus-worker.service, /bin/systemctl status cactus-worker.service, /bin/systemctl enable cactus-worker.service, /bin/systemctl disable cactus-worker.service" | sudo tee "$SUDOERS_FILE"
sudo chmod 440 "$SUDOERS_FILE"

sudo systemctl daemon-reload
sudo systemctl enable cactus-worker.service
sudo systemctl start cactus-worker.service

echo "✅ Worker auto-setup complete and service started successfully."
