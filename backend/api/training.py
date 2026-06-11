from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from backend.database.db import get_db
from backend.database.models import Job, Node, TrainingMetric
from backend.database.schemas import JobCreate, JobResponse, TrainingMetricResponse
from backend.auth.security import get_current_user
from backend.training.trainer import stop_job_by_id, get_job_logs, add_job_log
import os
import shutil
from datetime import datetime
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/train", tags=["training"])

class MetricsPayload(BaseModel):
    job_id: str
    gpu: float
    vram: float
    temp: float
    epoch: Optional[int] = None
    box_loss: Optional[float] = 0.0
    cls_loss: Optional[float] = 0.0
    dfl_loss: Optional[float] = 0.0
    map50: Optional[float] = 0.0
    map50_95: Optional[float] = 0.0

class StatusPayload(BaseModel):
    status: str

@router.post("/start", response_model=JobResponse)
def start_training_job(
    job_in: JobCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    # Check if there is already a running job
    active_job = db.query(Job).filter(Job.status == "running", Job.assigned_node == None).first()
    if active_job:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="There is already a training job running. Stop it before starting a new one."
        )

    # Check if there are active nodes
    active_nodes = db.query(Node).filter(Node.status == "active").all()
    if not active_nodes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active nodes in the cluster. Register and refresh nodes first."
        )

    # Generate a unique master job ID with a descriptive name
    import uuid
    from datetime import datetime
    model_clean = "".join(c if c.isalnum() or c in "-_" else "_" for c in job_in.model_name.replace(".pt", ""))
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    job_id = f"job_{model_clean}_{job_in.epochs}ep_{timestamp}_{uuid.uuid4().hex[:4]}"

    # 1. Sync dataset via rsync
    os.makedirs("dataset", exist_ok=True)
    import subprocess
    for node in active_nodes:
        try:
            rsync_cmd = [
                "rsync", "-az", "-e",
                f"ssh -p {node.ssh_port} -o StrictHostKeyChecking=no",
                "dataset/",
                f"{node.ssh_user}@{node.ip}:dataset/"
            ]
            subprocess.run(rsync_cmd, timeout=10, capture_output=True)
        except Exception as e:
            print(f"Rsync failed for node {node.ip}: {e}")

    # 2. Create the master job
    master_job = Job(
        id=job_id,
        model_name=job_in.model_name,
        dataset_path=job_in.dataset_path,
        epochs=job_in.epochs,
        batch_size=job_in.batch_size,
        learning_rate=job_in.learning_rate,
        status="pending",
        assigned_node=None,
        command=None
    )
    db.add(master_job)
    db.commit()
    db.refresh(master_job)

    # 3. Create sub-jobs (one for each node in the process group)
    nnodes = len(active_nodes)
    master_addr = active_nodes[0].ip
    master_port = 29500
    total_world_size = sum(max(1, n.gpu_count) for n in active_nodes)

    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        orchestrator_ip = s.getsockname()[0]
        s.close()
    except Exception:
        orchestrator_ip = "127.0.0.1"
    
    orchestrator_url = f"http://{orchestrator_ip}:8000"

    for rank, node in enumerate(active_nodes):
        nproc = max(1, node.gpu_count)
        backend = "gloo" if node.gpu_count == 0 else "nccl"
        
        cmd = (
            f"torchrun "
            f"--nnodes={nnodes} "
            f"--node_rank={rank} "
            f"--nproc_per_node={nproc} "
            f"--master_addr={master_addr} "
            f"--master_port={master_port} "
            f"worker/trainer.py "
            f"--world_size {total_world_size} "
            f"--rank {rank} "
            f"--master_addr {master_addr} "
            f"--master_port {master_port} "
            f"--backend {backend} "
            f"--orchestrator_url {orchestrator_url} "
            f"--epochs {job_in.epochs} "
            f"--batch_size {job_in.batch_size} "
            f"--lr {job_in.learning_rate} "
            f"--model {job_in.model_name} "
            f"--dataset {job_in.dataset_path} "
            f"--job_id {job_id}"
        )
        
        sub_job = Job(
            id=f"{job_id}_{node.ip}",
            status="pending",
            model_name=job_in.model_name,
            dataset_path=job_in.dataset_path,
            epochs=job_in.epochs,
            batch_size=job_in.batch_size,
            learning_rate=job_in.learning_rate,
            assigned_node=node.ip,
            command=cmd
        )
        db.add(sub_job)

    db.commit()
    db.refresh(master_job)

    add_job_log(job_id, f"Created DDP Job #{job_id}. Nodes: {nnodes}. World size: {total_world_size}. Waiting for workers to pull...")
    return master_job

@router.get("/jobs", response_model=list[JobResponse])
def list_jobs(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    # Only list master jobs in main view (sub-jobs are monitored internally)
    return db.query(Job).filter(Job.assigned_node == None).order_by(Job.created_at.desc()).all()

@router.get("/jobs/next")
def get_next_job(node_ip: str, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.status == "pending", Job.assigned_node == node_ip).first()
    if not job:
        return None
    
    # Mark worker job as running
    job.status = "running"
    job.started_at = datetime.utcnow()
    
    # Find master job and mark as running
    master_id = job.id.rsplit("_", 1)[0] # job_uuid
    master_job = db.query(Job).filter(Job.id == master_id).first()
    if master_job and master_job.status != "running":
        master_job.status = "running"
        master_job.started_at = datetime.utcnow()
    
    db.commit()
    
    # Update node status to training
    node = db.query(Node).filter(Node.ip == node_ip).first()
    if node:
        node.status = "training"
        db.commit()

    add_job_log(master_id, f"Worker {node_ip} pulled command and started execution.")
    return {
        "job_id": job.id,
        "master_job_id": master_job.id if master_job else job.id,
        "command": job.command
    }

@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job

@router.post("/jobs/{job_id}/stop")
def stop_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job.status = "stopped"
    job.finished_at = datetime.utcnow()
    
    # Also stop all worker sub-jobs
    sub_jobs = db.query(Job).filter(Job.id.like(f"{job_id}_%")).all()
    for sj in sub_jobs:
        sj.status = "stopped"
        sj.finished_at = datetime.utcnow()
        # Reset node status
        node = db.query(Node).filter(Node.ip == sj.assigned_node).first()
        if node and node.status == "training":
            node.status = "active"
            
    db.commit()
    add_job_log(job_id, "Job stopped by administrator command.")
    return {"message": "Job stop signal issued."}

@router.post("/jobs/{job_id}/status")
def update_job_status(job_id: str, payload: StatusPayload, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job.status = payload.status
    if payload.status in ["completed", "failed", "stopped"]:
        job.finished_at = datetime.utcnow()
        # Reset node status
        if job.assigned_node:
            node = db.query(Node).filter(Node.ip == job.assigned_node).first()
            if node and node.status == "training":
                node.status = "active"
    
    # If a sub-job finished, check if all sub-jobs finished or if one failed
    if job.assigned_node:
        master_id = job.id.rsplit("_", 1)[0]
        master_job = db.query(Job).filter(Job.id == master_id).first()
        if master_job:
            sub_jobs = db.query(Job).filter(Job.id.like(f"{master_id}_%")).all()
            if payload.status == "failed":
                master_job.status = "retry"  # Trigger retry logic in broadcast loop
                master_job.finished_at = datetime.utcnow()
            elif all(sj.status == "completed" for sj in sub_jobs):
                master_job.status = "completed"
                master_job.finished_at = datetime.utcnow()
                
    db.commit()
    return {"status": "updated"}

@router.get("/jobs/{job_id}/logs")
def get_logs(
    job_id: str,
    current_user=Depends(get_current_user)
):
    logs = get_job_logs(job_id)
    return {"logs": logs}

@router.post("/jobs/{job_id}/logs")
def append_logs(job_id: str, payload: dict):
    log_line = payload.get("log", "")
    add_job_log(job_id, log_line)
    return {"status": "logged"}

@router.get("/jobs/{job_id}/metrics", response_model=list[TrainingMetricResponse])
def get_job_metrics(
    job_id: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    return db.query(TrainingMetric).filter(
        TrainingMetric.job_id == job_id
    ).order_by(TrainingMetric.epoch.asc()).all()

@router.post("/metrics")
def post_metrics(payload: MetricsPayload, db: Session = Depends(get_db)):
    # Add metric to DB
    metric = TrainingMetric(
        job_id=payload.job_id,
        epoch=payload.epoch,
        box_loss=payload.box_loss,
        cls_loss=payload.cls_loss,
        dfl_loss=payload.dfl_loss,
        map50=payload.map50,
        map50_95=payload.map50_95,
        gpu_util=payload.gpu,
        vram_util=payload.vram,
        temp=payload.temp
    )
    db.add(metric)
    
    # Update job epoch
    if payload.epoch:
        job = db.query(Job).filter(Job.id == payload.job_id).first()
        if job:
            job.current_epoch = payload.epoch
            
    db.commit()
    return {"status": "ok"}

@router.post("/upload_model")
def upload_model(
    job_id: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    os.makedirs(f"outputs/{job_id}", exist_ok=True)
    file_path = f"outputs/{job_id}/model.pt"
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    # Mark master job and worker jobs as completed
    master_id = job_id.rsplit("_", 1)[0]
    master_job = db.query(Job).filter(Job.id == master_id).first()
    if master_job:
        master_job.status = "completed"
        master_job.finished_at = datetime.utcnow()
        
    # Also set nodes status back to active
    sub_jobs = db.query(Job).filter(Job.id.like(f"{master_id}_%")).all()
    for sj in sub_jobs:
        sj.status = "completed"
        sj.finished_at = datetime.utcnow()
        node = db.query(Node).filter(Node.ip == sj.assigned_node).first()
        if node and node.status == "training":
            node.status = "active"
            
    db.commit()
    add_job_log(master_id, "Training completed. Model checkpoint successfully uploaded to Master.")
    return {"status": "uploaded", "path": file_path}

@router.get("/download/{job_id}")
def download_model(job_id: str, token: Optional[str] = None):
    # Accept token via query parameters or let the client perform auth.
    # We serve FileResponse from outputs/{job_id}/model.pt
    file_path = f"outputs/{job_id}/model.pt"
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Model file not found. Training might be in progress or failed.")
    return FileResponse(file_path, media_type="application/octet-stream", filename=f"model_{job_id}.pt")



