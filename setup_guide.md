# Cactus Cluster: End-to-End Setup Guide

This guide describes how to configure, deploy, and execute the Distributed YOLOv8 training system across multiple nodes using our automated deployment tools.

---

## 1. Master Orchestrator Setup

The Master node runs the web dashboard and coordinates all workers.

### 1.1 Install Master Dependencies
Ensure you have Python 3.8+ installed on the master machine:
```bash
sudo apt update
sudo apt install -y python3-venv python3-pip sqlite3
```

### 1.2 Start the Backend
Navigate to the root workspace directory and run the FastAPI server:
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Start the orchestrator (runs on http://0.0.0.0:8000)
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

### 1.3 Generate Master SSH Key (Important)
For the Master to securely control the workers, it needs an SSH keypair. If you don't already have one, generate it now:
```bash
ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519
```
*Note: You do **not** need to manually copy this key. The UI dashboard will handle it.*

---

## 2. Worker Node Provisioning

Each machine with GPUs needs the worker agent installed. We provide an automated script that handles the entire setup with zero manual configuration.

### 2.1 Get the Worker Package
You can get the worker code onto your node in two ways:
1. **Via UI Download:** Open the Master dashboard, go to the **OTA Sync** tab, and click **Build & Download Worker Package**. Transfer this zip file to your worker via USB or SCP.
2. **Direct Copy:** Copy the `worker/` directory from the repository to the worker machine.

### 2.2 Run the Auto-Installer
On the worker machine, run the setup script:
```bash
cd worker
chmod +x install.sh
./install.sh
```
**What this script does:**
1. Installs OS packages (`openssh-server`, Python).
2. Starts the SSH Daemon.
3. Builds a Python virtual environment and installs PyTorch (CUDA) + Ultralytics.
4. Installs a background systemd service called `cactus-worker`.

---

## 3. Registering Nodes via Dashboard

1. **Access the UI:** Open a browser and go to `http://<MASTER_IP>:8000`.
2. **Login:** Use username `admin` and password `admin123`.
3. **Go to Cluster Nodes:**
   - Enter the Worker's IP Address.
   - Enter the Worker's SSH Password.
   - Check **"Also install SSH public key"** and paste the Master's public key (run `cat ~/.ssh/id_ed25519.pub` on the Master to get it).
   - Click **Register Node**.

The Master will connect using the password, securely install the key for future passwordless access, scan the GPU hardware, and add it to the cluster.

---

## 4. Service Management & OTA Updates

### Starting the Worker Agent
Once registered, click the **▶ Start Worker** button on the node's card in the dashboard. The master will automatically send the orchestrator URL to the worker and start the `cactus-worker` systemd service in the background. 

### Keeping Workers Updated (OTA)
If you update the worker code on the Master, you don't need to manually copy it again:
- Go to the **OTA Sync** tab.
- Click **Sync Worker Code Package**.
- The Master will automatically SFTP the new codebase to all registered worker nodes in parallel.

---

## 5. Launching Distributed Training

1. Navigate to the **Launch Training** tab.
2. Select the YOLO model version (e.g. `yolov8n.pt` for nano, `yolov8x.pt` for extra-large).
3. Set your dataset path (must exist on all nodes at the same location).
4. Configure Hyperparameters (Epochs, Batch Size, LR).
5. Click **Launch DDP Cluster Job**.

The Orchestrator will:
1. Ensure all workers are updated.
2. Determine the optimal communication backend (`nccl` for NVIDIA GPUs, `gloo` for CPUs).
3. Spawn `torchrun` distributed processes across the cluster.
4. Stream live metrics (GPU usage, temperatures, loss, mAP) back to the dashboard in real-time.
