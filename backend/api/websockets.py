from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from typing import List
import asyncio
import json
import logging
from sqlalchemy.orm import Session
from backend.database.db import SessionLocal
from backend.database.models import Node, Job, NodeMetric, TrainingMetric
from backend.training.trainer import get_job_logs

logger = logging.getLogger("Websockets")

router = APIRouter(prefix="/ws", tags=["websockets"])

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"New client connected. Active connections: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"Client disconnected. Active connections: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        # Create a list of tasks to run concurrently and handle failures
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.append(connection)
        
        for conn in disconnected:
            self.disconnect(conn)

manager = ConnectionManager()

# Background broadcast loop
async def broadcast_loop():
    from datetime import datetime
    from backend.training.trainer import check_and_recover_jobs
    
    while True:
        if manager.active_connections:
            db = SessionLocal()
            try:
                # Run auto-recovery check first
                check_and_recover_jobs(db)
                
                # Check for heartbeat timeouts (nodes offline)
                now = datetime.utcnow()
                nodes = db.query(Node).all()
                for node in nodes:
                    if node.status in ["active", "training"] and (now - node.last_seen).total_seconds() > 15:
                        node.status = "offline"
                        db.commit()
                        
                        # Stop sub-jobs for this node
                        running_sub_jobs = db.query(Job).filter(Job.status == "running", Job.assigned_node == node.ip).all()
                        for sub_job in running_sub_jobs:
                            sub_job.status = "failed"
                            master_id = sub_job.id.rsplit("_", 1)[0]
                            master_job = db.query(Job).filter(Job.id == master_id).first()
                            if master_job and master_job.status == "running":
                                master_job.status = "retry"
                                # Also stop other running sub-jobs of this master job
                                other_sub_jobs = db.query(Job).filter(Job.status == "running", Job.id.like(f"{master_id}_%")).all()
                                for oj in other_sub_jobs:
                                    oj.status = "stopped"
                        db.commit()

                # 1. Fetch Node Statuses & GPU metrics
                nodes_data = []
                for node in nodes:
                    # Get latest metric
                    latest_metric = db.query(NodeMetric).filter(
                        NodeMetric.node_id == node.id
                    ).order_by(NodeMetric.timestamp.desc()).first()
                    
                    metric_data = None
                    if latest_metric:
                        try:
                            metric_data = {
                                "gpu_util": json.loads(latest_metric.gpu_util),
                                "vram_util": json.loads(latest_metric.vram_util),
                                "temp": json.loads(latest_metric.temp)
                            }
                        except Exception:
                            pass
                            
                    nodes_data.append({
                        "id": node.id,
                        "ip": node.ip,
                        "ssh_user": node.ssh_user,
                        "status": node.status,
                        "gpu_count": node.gpu_count,
                        "gpu_info": json.loads(node.gpu_info) if node.gpu_info else [],
                        "latest_metric": metric_data,
                        "last_seen": node.last_seen.isoformat()
                    })

                # 2. Fetch Active Job Details (only main master jobs, i.e., assigned_node is None)
                active_job = db.query(Job).filter(Job.status == "running", Job.assigned_node == None).first()
                job_data = None
                if active_job:
                    # Fetch training metrics for active job
                    t_metrics = db.query(TrainingMetric).filter(
                        TrainingMetric.job_id == active_job.id
                    ).order_by(TrainingMetric.epoch.asc()).all()
                    
                    history = []
                    for m in t_metrics:
                        history.append({
                            "epoch": m.epoch,
                            "box_loss": m.box_loss,
                            "cls_loss": m.cls_loss,
                            "dfl_loss": m.dfl_loss,
                            "map50": m.map50,
                            "map50_95": m.map50_95
                        })
                        
                    job_data = {
                        "id": active_job.id,
                        "status": active_job.status,
                        "model_name": active_job.model_name,
                        "dataset_path": active_job.dataset_path,
                        "epochs": active_job.epochs,
                        "batch_size": active_job.batch_size,
                        "current_epoch": active_job.current_epoch,
                        "metrics_history": history,
                        "logs": get_job_logs(active_job.id)
                    }

                payload = {
                    "nodes": nodes_data,
                    "active_job": job_data
                }
                
                await manager.broadcast(payload)
            except Exception as e:
                logger.error(f"Error in broadcast loop: {e}")
            finally:
                db.close()
        
        await asyncio.sleep(1.5)  # Stream data every 1.5 seconds

# Start the broadcast loop on application startup
def start_broadcast_task():
    asyncio.create_task(broadcast_loop())

@router.websocket("/stream")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
