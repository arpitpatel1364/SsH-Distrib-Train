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
