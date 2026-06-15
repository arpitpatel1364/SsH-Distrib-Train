from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.orm import Session
from backend.database.db import get_db, SessionLocal
from backend.database.models import Node
from backend.database.schemas import NodeCreate, NodeResponse
from backend.auth.security import get_current_user
from backend.ssh.ssh_manager import ssh_manager
import json

router = APIRouter(prefix="/nodes", tags=["nodes"])

def verify_node_background(node_id: int):
    db = SessionLocal()
    try:
        node = db.query(Node).filter(Node.id == node_id).first()
        if not node:
            return
        
        gpu_res = ssh_manager.execute(node.ip, node.ssh_user, node.ssh_port, "nvidia-smi -L")
        if gpu_res is None:
            test_res = ssh_manager.execute(node.ip, node.ssh_user, node.ssh_port, "echo 'hello'")
            if test_res is None:
                node.status = "failed"
                node.gpu_count = 0
                node.gpu_info = json.dumps([])
            else:
                node.status = "active"
                node.gpu_count = 0
                node.gpu_info = json.dumps(["CPU Only"])
        else:
            node.status = "active"
            lines = [line.strip() for line in gpu_res.strip().split('\n') if line.strip()]
            gpu_list = []
            for line in lines:
                if "GPU " in line:
                    parts = line.split(":", 1)
                    gpu_name = parts[1].split("(UUID:")[0].strip() if len(parts) > 1 else line
                    gpu_list.append(gpu_name)
                else:
                    gpu_list.append(line)
            node.gpu_count = len(gpu_list)
            node.gpu_info = json.dumps(gpu_list)
            
        db.commit()
    except Exception as e:
        print(f"Error verifying node {node_id} in background: {e}")
    finally:
        db.close()

@router.post("/add", response_model=NodeResponse)
def add_node(
    node_in: NodeCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    # Check if node already exists
    existing_node = db.query(Node).filter(Node.ip == node_in.ip).first()
    if existing_node:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Node with IP {node_in.ip} already exists."
        )

    # Validate SSH connection synchronously BEFORE saving
    test_res = ssh_manager.execute(node_in.ip, node_in.ssh_user, node_in.ssh_port, "echo 'hello'")
    if test_res is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Not connected! Could not verify SSH access to node."
        )

    gpu_count = 0
    gpu_info_list = ["CPU Only"]
    gpu_res = ssh_manager.execute(node_in.ip, node_in.ssh_user, node_in.ssh_port, "nvidia-smi -L")
    
    if gpu_res is not None:
        lines = [line.strip() for line in gpu_res.strip().split('\n') if line.strip()]
        gpu_info_list = []
        for line in lines:
            if "GPU " in line:
                parts = line.split(":", 1)
                gpu_name = parts[1].split("(UUID:")[0].strip() if len(parts) > 1 else line
                gpu_info_list.append(gpu_name)
            else:
                gpu_info_list.append(line)
        gpu_count = len(gpu_info_list)

    # Save to database only if connected successfully
    node = Node(
        ip=node_in.ip,
        ssh_user=node_in.ssh_user,
        ssh_port=node_in.ssh_port,
        status="active",
        gpu_count=gpu_count,
        gpu_info=json.dumps(gpu_info_list)
    )
    
    db.add(node)
    db.commit()
    db.refresh(node)
    
    return node


# ---------------------------------------------------------------------------
# Add node with explicit password auth + optional SSH key installation
# ---------------------------------------------------------------------------
import paramiko
from typing import Optional
from pydantic import BaseModel as _BaseModel

class AddWithAuthPayload(_BaseModel):
    ip: str
    ssh_user: str = "ubuntu"
    ssh_port: int = 22
    ssh_password: str                  # always required
    install_key: bool = False          # if True, copy public_key into authorized_keys
    public_key: Optional[str] = None   # the key content to install (required when install_key=True)


def _parse_gpu_info(gpu_res: Optional[str]):
    gpu_count = 0
    gpu_info_list = ["CPU Only"]
    if gpu_res:
        lines = [l.strip() for l in gpu_res.strip().split('\n') if l.strip()]
        gpu_info_list = []
        for line in lines:
            if "GPU " in line:
                parts = line.split(":", 1)
                name = parts[1].split("(UUID:")[0].strip() if len(parts) > 1 else line
                gpu_info_list.append(name)
            else:
                gpu_info_list.append(line)
        gpu_count = len(gpu_info_list)
        if not gpu_info_list:
            gpu_info_list = ["CPU Only"]
    return gpu_count, gpu_info_list


@router.post("/add-with-auth", response_model=NodeResponse)
def add_node_with_auth(
    payload: AddWithAuthPayload,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    # Duplicate check
    if db.query(Node).filter(Node.ip == payload.ip).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Node {payload.ip} is already registered."
        )

    if payload.install_key and not payload.public_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="public_key is required when install_key is True."
        )

    # --- Step 1: Connect with password ---
    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            hostname=payload.ip,
            username=payload.ssh_user,
            port=payload.ssh_port,
            password=payload.ssh_password,
            timeout=12,
            allow_agent=False,
            look_for_keys=False
        )
    except paramiko.AuthenticationException:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="SSH Authentication failed. Wrong password."
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not connect to {payload.ip}:{payload.ssh_port} — {e}"
        )

    try:
        # --- Step 2 (optional): Install public key ---
        if payload.install_key and payload.public_key:
            pub_key = payload.public_key.strip()
            install_cmd = (
                "mkdir -p ~/.ssh && "
                "chmod 700 ~/.ssh && "
                f"echo '{pub_key}' >> ~/.ssh/authorized_keys && "
                "chmod 600 ~/.ssh/authorized_keys"
            )
            stdin, stdout, stderr = client.exec_command(install_cmd)
            stdout.channel.recv_exit_status()  # wait
            err = stderr.read().decode().strip()
            if err:
                raise HTTPException(
                    status_code=500,
                    detail=f"Key installation failed: {err}"
                )

        # --- Step 3: Scan GPU via the already-open password session ---
        _, stdout_gpu, _ = client.exec_command("nvidia-smi -L")
        gpu_out = stdout_gpu.read().decode().strip()
        gpu_count, gpu_info_list = _parse_gpu_info(gpu_out if gpu_out else None)

    finally:
        client.close()

    # --- Step 4: Save node (key-based SSH will be used from here on) ---
    node = Node(
        ip=payload.ip,
        ssh_user=payload.ssh_user,
        ssh_port=payload.ssh_port,
        status="active",
        gpu_count=gpu_count,
        gpu_info=json.dumps(gpu_info_list)
    )
    db.add(node)
    db.commit()
    db.refresh(node)
    return node


@router.get("/", response_model=list[NodeResponse])
def list_nodes(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    return db.query(Node).all()

@router.delete("/{node_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_node(
    node_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Node not found"
        )
    db.delete(node)
    db.commit()
    return None

@router.post("/{node_id}/refresh", response_model=NodeResponse)
def refresh_node(
    node_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Node not found"
        )

    background_tasks.add_task(verify_node_background, node.id)
    return node

from pydantic import BaseModel
from typing import List
from datetime import datetime
from backend.database.models import NodeMetric

class NodeRegister(BaseModel):
    ip: str
    ssh_user: str = "ubuntu"
    ssh_port: int = 22
    gpu_count: int = 0
    gpu_info: List[str] = []

class NodeHeartbeat(BaseModel):
    node_id: str
    gpu: float
    vram: float
    temp: float

@router.post("/register")
def register_node(node_in: NodeRegister, db: Session = Depends(get_db)):
    node = db.query(Node).filter(Node.ip == node_in.ip).first()
    if not node:
        node = Node(
            ip=node_in.ip,
            ssh_user=node_in.ssh_user,
            ssh_port=node_in.ssh_port,
        )
        db.add(node)
    
    node.gpu_count = node_in.gpu_count
    node.gpu_info = json.dumps(node_in.gpu_info)
    node.status = "active"
    node.last_seen = datetime.utcnow()
    db.commit()
    db.refresh(node)
    return {"status": "registered", "node_id": node.id}

@router.post("/heartbeat")
def heartbeat_node(heartbeat: NodeHeartbeat, db: Session = Depends(get_db)):
    node = db.query(Node).filter((Node.ip == heartbeat.node_id) | (Node.id == heartbeat.node_id)).first()
    if not node:
        raise HTTPException(status_code=404, detail="Node not registered")
    
    if node.status != "training":
        node.status = "active"
    node.last_seen = datetime.utcnow()
    
    metric = NodeMetric(
        node_id=node.id,
        gpu_util=json.dumps([int(heartbeat.gpu)]),
        vram_util=json.dumps([int(heartbeat.vram)]),
        temp=json.dumps([int(heartbeat.temp)])
    )
    db.add(metric)
    db.commit()
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Start / Stop worker agent remotely via SSH
# ---------------------------------------------------------------------------

class StartWorkerPayload(BaseModel):
    master_url: str

import socket as _socket

@router.post("/{node_id}/start-worker")
def start_worker_on_node(
    node_id: int,
    payload: StartWorkerPayload,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    master_url = payload.master_url.rstrip("/")

    # Command finds worker dir, saves URL, attempts systemctl start (if passwordless sudo is available)
    # or falls back to nohup. Finally, checks if process is running.
    cmd = (
        f"WORKER_DIR=$(find ~ -maxdepth 2 -type d -name 'worker' | head -n 1) && "
        f"if [ -z \"$WORKER_DIR\" ]; then echo 'Worker directory not found'; exit 1; fi && "
        f"cd \"$WORKER_DIR\" && "
        f"echo '{master_url}' > .master_url && "
        f"if command -v systemctl >/dev/null 2>&1 && sudo -n true 2>/dev/null; then "
        f"  sudo systemctl restart cactus-worker || "
        f"  nohup bash run.sh > worker_agent.log 2>&1 & "
        f"else "
        f"  nohup bash run.sh > worker_agent.log 2>&1 & "
        f"fi && "
        f"sleep 2 && "
        f"if pgrep -f 'worker.py' >/dev/null; then echo 'RUNNING'; else echo 'FAILED'; fi"
    )

    result = ssh_manager.execute(node.ip, node.ssh_user, node.ssh_port, cmd, timeout=15)
    
    if result is None:
        raise HTTPException(
            status_code=500,
            detail=f"SSH command failed on node {node.ip}. Check SSH connectivity."
        )

    output = result.strip()
    if "FAILED" in output or "Worker directory not found" in output:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to start worker service on {node.ip}. Output: {output}"
        )

    return {
        "status": "started",
        "node_ip": node.ip,
        "master_url": master_url,
        "detail": "Worker service is running and verified."
    }

@router.post("/{node_id}/stop-worker")
def stop_worker_on_node(
    node_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    # Stop via systemd if available, else pkill
    cmd = (
        "if command -v systemctl >/dev/null 2>&1 && sudo -n true 2>/dev/null; then "
        "  sudo systemctl stop cactus-worker; "
        "fi; "
        "pkill -f 'python worker.py' || true"
    )
    ssh_manager.execute(node.ip, node.ssh_user, node.ssh_port, cmd, timeout=10)

    return {"status": "stopped", "node_ip": node.ip}

