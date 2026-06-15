import os
import logging
import socket
from datetime import datetime
from sqlalchemy.orm import Session
from backend.database.models import Node, Job

logger = logging.getLogger("Trainer")

# Global dict to store live training logs: job_id -> list of log strings
job_logs = {}

def get_job_logs(job_id: str):
    # Support both int and str keys
    return job_logs.get(str(job_id), [])

def add_job_log(job_id: str, log_line: str):
    job_key = str(job_id)
    if job_key not in job_logs:
        job_logs[job_key] = []
    job_logs[job_key].append(log_line)
    if len(job_logs[job_key]) > 1000:
        job_logs[job_key].pop(0)

def stop_job_by_id(job_id: str):
    # Handled inside API endpoints via direct DB updates
    return False

def check_and_recover_jobs(db: Session):
    # Find all master jobs in "retry" state
    retry_jobs = db.query(Job).filter(Job.status == "retry", Job.assigned_node == None).all()
    for m_job in retry_jobs:
        # Get active nodes
        active_nodes = db.query(Node).filter(Node.status == "active").all()
        if not active_nodes:
            # No active nodes, mark job as failed
            m_job.status = "failed"
            m_job.finished_at = datetime.utcnow()
            db.commit()
            add_job_log(m_job.id, "Auto-recovery failed: No active nodes left in the cluster.")
            continue
        
        # Reset master job to pending
        m_job.status = "pending"
        db.commit()
        add_job_log(m_job.id, f"Auto-recovery triggered. Restarting training with {len(active_nodes)} active nodes...")
        
        # Delete old sub-jobs for this master job.
        # Sub-job IDs are: {master_job_id}_{node_ip} e.g. job_yolo_65dc_192.168.1.13
        # We use LIKE with the master ID prefix — safe because node IPs start with digits
        # and master job IDs never end with an underscore+digit pattern.
        db.query(Job).filter(
            Job.assigned_node != None,
            Job.id.like(f"{m_job.id}_%")
        ).delete(synchronize_session=False)
        db.commit()
        
        # Re-create sub-jobs with new active nodes
        nnodes = len(active_nodes)
        master_addr = active_nodes[0].ip
        import random
        master_port = random.randint(29500, 39500)
        total_world_size = sum(max(1, n.gpu_count) for n in active_nodes)
        
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            orchestrator_ip = s.getsockname()[0]
            s.close()
        except Exception:
            orchestrator_ip = "127.0.0.1"
        orchestrator_url = f"http://{orchestrator_ip}:8000"
        
        import time
        retry_suffix = str(int(time.time()))
        
        for rank, node in enumerate(active_nodes):
            nproc = max(1, node.gpu_count)
            backend = "gloo" if node.gpu_count == 0 else "nccl"
            
            cmd = (
                f"MASTER_ADDR={master_addr} "
                f"MASTER_PORT={master_port} "
                f"TORCH_NCCL_ENABLE_MONITORING=0 "
                f"NCCL_IB_DISABLE=1 "
                f"NCCL_SOCKET_FAMILY=AF_INET "
                f"GLOO_SOCKET_FAMILY=AF_INET "
                f"NCCL_SOCKET_IFNAME=^lo,docker,virbr,br- "
                f"GLOO_SOCKET_IFNAME=en,eth,em,bond,wl "
                f"torchrun "
                f"--nnodes={nnodes} "
                f"--node_rank={rank} "
                f"--nproc_per_node={nproc} "
                f"--rdzv_backend=c10d "
                f"--rdzv_endpoint={master_addr}:{master_port} "
                f"--rdzv_id={m_job.id}-retry "
                f"--local-addr={node.ip} "
                f"worker/trainer.py "
                f"--world_size {total_world_size} "
                f"--rank {rank} "
                f"--master_addr {master_addr} "
                f"--master_port {master_port} "
                f"--backend {backend} "
                f"--orchestrator_url {orchestrator_url} "
                f"--epochs {m_job.epochs} "
                f"--batch_size {m_job.batch_size} "
                f"--lr {m_job.learning_rate} "
                f"--model {m_job.model_name} "
                f"--dataset {m_job.dataset_path or 'coco128.yaml'} "
                f"--job_id {m_job.id}"
            )
            
            sub_job = Job(
                id=f"{m_job.id}_{node.ip}-{retry_suffix}",
                status="pending",
                model_name=m_job.model_name,
                dataset_path=m_job.dataset_path,
                epochs=m_job.epochs,
                batch_size=m_job.batch_size,
                learning_rate=m_job.learning_rate,
                assigned_node=node.ip,
                command=cmd
            )
            db.add(sub_job)
        db.commit()
