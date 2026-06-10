# 🚀 Distributed YOLO Cluster End-to-End Setup Guide

This guide describes how to configure, deploy, and execute the Distributed YOLOv8 training system across multiple nodes.

---

## 📋 Prerequisites & Architecture

The system consists of:
1. **Master Orchestrator**: Runs the FastAPI backend (main server) and React frontend (user interface). Manages job scheduling, database storage (SQLite), telemetry, and parallel SSH triggers.
2. **Worker Nodes**: Physical or virtual machine nodes containing GPUs (or CPUs) where `torchrun` executes the DDP training script in parallel.

---

## 🛠️ Step 1: Master Orchestrator Setup

### 1. Install System Dependencies
Ensure you have Python 3.8+, Node.js, and npm installed on the master machine:
```bash
sudo apt update
sudo apt install -y python3-venv python3-pip nodejs npm sqlite3
```

### 2. Configure Virtual Environment & Backend Dependencies
Navigate to the root workspace directory and run the install script:
```bash
cd /home/cactus/Desktop/ssh
chmod +x scripts/install.sh scripts/run.sh
./scripts/install.sh
```
This script initializes the local virtual environment and installs:
* `fastapi` & `uvicorn` (REST & WebSockets)
* `paramiko` & `cryptography` (Async SSH and SFTP connection handling)
* `sqlalchemy` (SQLite ORM)
* `python-jose` & `passlib` (Authentication & Security)

### 3. Install Frontend Dependencies
Navigate to the frontend directory and install the packages:
```bash
cd frontend
npm install
```

---

## 🖥️ Step 2: Worker Nodes Provisioning

To enable DDP initialization and DDP-safe checkpoint recovery, each worker node must be prepared to accept parallel execution commands.

### 1. Configure Passwordless SSH Access
The master orchestrator connects to workers using SSH keys. Generate an SSH keypair on the master (if not already done) and copy the public key to all worker nodes:
```bash
# On Master:
ssh-keygen -t rsa -b 4096 -N "" -f ~/.ssh/id_rsa
ssh-copy-id -p <ssh_port> <user>@<worker_ip>
```
*Verify that you can login from the master to each worker node via `ssh <user>@<worker_ip>` without being prompted for a password.*

### 2. Configure Python Virtual Environment on Worker Nodes
On **each worker node**, create a virtual environment in the home directory named `venv` and install the training libraries:
```bash
# On each Worker node:
python3 -m venv ~/venv
source ~/venv/bin/activate
pip install --upgrade pip
pip install torch torchvision ultralytics requests
```

### 3. Data Sync (Optional)
Ensure the dataset YAML and training images are stored at the same absolute path on all worker nodes (e.g. `~/datasets/coco128/` or as defined in the job scheduler dataset config).

---

## ⚡ Step 3: Run the Orchestrator

To start both the FastAPI backend server (listening on port `8000`) and the Vite React frontend client (listening on port `5173`), run the launch script from the root workspace:
```bash
./scripts/run.sh
```

---

## 🖥️ Step 4: Step-by-Step Training Execution Workflow

1. **Access the Dashboard**: Open your browser and navigate to `http://localhost:5173`.
2. **Log In**: Authenticate using the default admin account:
   * **Username**: `admin`
   * **Password**: `admin123`
3. **Register Worker Nodes**:
   * Under the **Add Cluster Node** form, enter the worker node's IP address, SSH user, and SSH port.
   * Click **Add Node**. The orchestrator will run connectivity tests and hardware capability detection in a non-blocking background task. Once complete, the node card will turn online, showing the number of available GPUs and hardware models.
4. **Deploy & Launch Training**:
   * Select the YOLO model version (e.g. `yolov8n.pt`).
   * Provide the dataset configuration path.
   * Configure hyperparameters (Epochs, Batch Size, Learning Rate).
   * Click **Deploy & Launch DDP**. The orchestrator will:
     1. SFTP the local worker code package to all nodes in parallel.
     2. Programmatically detect active network routing interfaces (`NCCL_SOCKET_IFNAME`) on each machine.
     3. Select the best matching cluster backend (`nccl` if all GPUs, `gloo` if any CPUs are involved).
     4. Spin up concurrent DDP workers using `torchrun`.
     5. Scrape epoch metrics and live GPU telemetry in real-time, displaying them on the dashboard curves.
