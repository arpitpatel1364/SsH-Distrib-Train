#!/bin/bash

# =============================================================================
#  Cactus DDP Worker Node — Full Auto-Provisioning Script
#  Installs everything needed: SSH, Python, ML deps, systemd service
#  Run once on the worker machine. No manual steps required.
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CURRENT_USER="$(whoami)"
VENV_DIR="$HOME/venv"
SERVICE_NAME="cactus-worker"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

echo "========================================================"
echo "  Cactus DDP Worker Node — Auto-Provisioning"
echo "  User : $CURRENT_USER"
echo "  Dir  : $SCRIPT_DIR"
echo "========================================================"

# ------------------------------------------------------------------------------
# STEP 1: OS CHECK
# ------------------------------------------------------------------------------
echo ""
echo "--> [1/6] System compatibility check..."

if ! command -v apt-get &> /dev/null; then
    echo "ERROR: apt-get not found. This script requires a Debian/Ubuntu system."
    exit 1
fi
echo "  OS: OK (Debian/Ubuntu detected)"

# NVIDIA / CUDA
if command -v nvidia-smi &> /dev/null; then
    echo "  GPU: NVIDIA drivers found."
    nvidia-smi --query-gpu=name --format=csv,noheader | sed 's/^/       - /'
else
    echo "  GPU: WARNING — nvidia-smi not found. Training will fall back to CPU."
    read -p "       Continue anyway? (y/N): " choice
    case "$choice" in
      y|Y ) echo "       Proceeding with CPU-only setup.";;
      * )   echo "       Aborted. Please install NVIDIA drivers first."; exit 1;;
    esac
fi

# ------------------------------------------------------------------------------
# STEP 2: SYSTEM PACKAGES (SSH + Python)
# ------------------------------------------------------------------------------
echo ""
echo "--> [2/6] Installing system packages (openssh-server, python3-venv, pip)..."

PKGS_NEEDED=()
command -v sshd &> /dev/null      || PKGS_NEEDED+=("openssh-server")
python3 -c "import venv" &>/dev/null || PKGS_NEEDED+=("python3-venv")
python3 -c "import pip"  &>/dev/null || PKGS_NEEDED+=("python3-pip")

if [ ${#PKGS_NEEDED[@]} -gt 0 ]; then
    echo "  Installing: ${PKGS_NEEDED[*]}"
    sudo apt-get update -y -q
    sudo apt-get install -y -q "${PKGS_NEEDED[@]}"
else
    echo "  All system packages already installed."
fi

# ------------------------------------------------------------------------------
# STEP 3: ENABLE & START SSH SERVER
# ------------------------------------------------------------------------------
echo ""
echo "--> [3/6] Configuring SSH server..."

if command -v systemctl &> /dev/null; then
    sudo systemctl enable ssh  2>/dev/null || sudo systemctl enable sshd 2>/dev/null || true
    if ! systemctl is-active --quiet ssh 2>/dev/null && ! systemctl is-active --quiet sshd 2>/dev/null; then
        sudo systemctl start ssh 2>/dev/null || sudo systemctl start sshd 2>/dev/null || true
        echo "  SSH server started."
    else
        echo "  SSH server already running."
    fi
else
    echo "  WARNING: systemctl not found. Ensure SSH daemon is running manually."
fi

# Ensure ~/.ssh exists with correct permissions
mkdir -p "$HOME/.ssh"
chmod 700 "$HOME/.ssh"
touch "$HOME/.ssh/authorized_keys"
chmod 600 "$HOME/.ssh/authorized_keys"
echo "  ~/.ssh permissions verified."

# ------------------------------------------------------------------------------
# STEP 4: PYTHON VIRTUAL ENVIRONMENT
# ------------------------------------------------------------------------------
echo ""
echo "--> [4/6] Building Python virtual environment at $VENV_DIR..."

if [ -d "$VENV_DIR" ]; then
    if [ ! -f "$VENV_DIR/bin/activate" ] || [ ! -x "$VENV_DIR/bin/python" ]; then
        echo "  Corrupted venv detected. Rebuilding..."
        rm -rf "$VENV_DIR"
        python3 -m venv "$VENV_DIR"
    else
        echo "  Existing venv is healthy."
    fi
else
    python3 -m venv "$VENV_DIR"
    echo "  Virtual environment created."
fi

source "$VENV_DIR/bin/activate"
echo "  Python: $(python --version)"

# ------------------------------------------------------------------------------
# STEP 5: ML DEPENDENCIES
# ------------------------------------------------------------------------------
echo ""
echo "--> [5/6] Installing ML dependencies (PyTorch, Ultralytics, Requests)..."

pip install --upgrade pip -q
pip install -r "$SCRIPT_DIR/requirements.txt" \
    --extra-index-url https://download.pytorch.org/whl/cu121 -q

# Validate
if python -c "import torch; import requests; import ultralytics" &>/dev/null; then
    CUDA_AVAIL=$(python -c "import torch; print(torch.cuda.is_available())")
    if [ "$CUDA_AVAIL" = "True" ]; then
        echo "  PyTorch + CUDA: OK"
    else
        echo "  PyTorch: OK (CPU-only mode)"
    fi
else
    echo "ERROR: Dependency verification failed. Check pip output above."
    exit 1
fi

# ------------------------------------------------------------------------------
# STEP 6: CHMOD ALL SCRIPTS + SYSTEMD SERVICE
# ------------------------------------------------------------------------------
echo ""
echo "--> [6/6] Setting permissions and installing systemd service..."

# Make every shell script in the worker directory executable
find "$SCRIPT_DIR" -name "*.sh" -exec chmod +x {} \;
echo "  Permissions: chmod +x applied to all .sh scripts in $SCRIPT_DIR"

# Create the systemd service file
cat > /tmp/${SERVICE_NAME}.service << EOF
[Unit]
Description=Cactus DDP Distributed Training Worker Agent
After=network.target network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${CURRENT_USER}
WorkingDirectory=${SCRIPT_DIR}
EnvironmentFile=-${SCRIPT_DIR}/.env
ExecStartPre=/bin/bash -c 'test -f ${SCRIPT_DIR}/.master_url || { echo "MASTER URL not set. Use the dashboard to start the worker."; exit 1; }'
ExecStart=${VENV_DIR}/bin/python ${SCRIPT_DIR}/worker.py --master \$(cat ${SCRIPT_DIR}/.master_url)
Restart=on-failure
RestartSec=10
StandardOutput=append:${HOME}/worker_agent.log
StandardError=append:${HOME}/worker_agent.log
KillMode=control-group
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
EOF

# Install the service file
if sudo cp /tmp/${SERVICE_NAME}.service "$SERVICE_FILE"; then
    sudo systemctl daemon-reload
    sudo systemctl enable "${SERVICE_NAME}"
    echo "  Systemd service '${SERVICE_NAME}' installed and enabled."
    echo "  Service file: $SERVICE_FILE"
    echo "  Start with:  sudo systemctl start ${SERVICE_NAME}"
    echo "  Status:      sudo systemctl status ${SERVICE_NAME}"
    echo "  Logs:        journalctl -u ${SERVICE_NAME} -f"
else
    echo "  WARNING: Could not install systemd service (no sudo access?)."
    echo "  You can still start the worker manually using ./run.sh"
fi

# Clean up temp file
rm -f /tmp/${SERVICE_NAME}.service

# ------------------------------------------------------------------------------
# DONE
# ------------------------------------------------------------------------------
echo ""
echo "========================================================"
echo "  Worker Node Successfully Provisioned!"
echo "========================================================"
echo ""
echo "  This worker is ready to join the Cactus DDP cluster."
echo ""
echo "  The MASTER SSH public key will be installed automatically"
echo "  when you register this node from the dashboard."
echo ""
echo "  Worker IP:  $(hostname -I | awk '{print $1}')"
echo "  SSH User:   $CURRENT_USER"
echo "  SSH Port:   22"
echo ""
echo "  To start the worker agent NOW, run:"
echo "    ./run.sh <MASTER_URL>"
echo ""
echo "  Or start via systemd (after setting master URL from dashboard):"
echo "    sudo systemctl start ${SERVICE_NAME}"
echo "========================================================"

# Interactive option to run immediately
if [ -t 0 ]; then
    echo ""
    read -p "Start the worker agent now? (y/N): " run_now
    if [[ "$run_now" =~ ^[yY]$ ]]; then
        echo "--> Starting worker agent..."
        if [ -x "$SCRIPT_DIR/run.sh" ]; then
            exec "$SCRIPT_DIR/run.sh"
        else
            exec bash "$SCRIPT_DIR/run.sh"
        fi
    fi
fi
