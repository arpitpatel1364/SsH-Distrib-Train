from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import json
import threading
import time
from datetime import datetime
from backend.database.db import get_db, SessionLocal
from backend.database.models import Node, NodeMetric
from backend.database.schemas import NodeMetricResponse
from backend.auth.security import get_current_user
from backend.ssh.ssh_manager import ssh_manager

router = APIRouter(prefix="/monitor", tags=["monitoring"])

# Background thread to scrape GPU metrics periodically
def scrape_gpu_metrics():
    while True:
        db = SessionLocal()
        try:
            nodes = db.query(Node).all()
            threads = []
            
            def scrape_node(node_id, ip, user, port):
                # Query GPU utilization, memory utilization, and temperature
                # Output format: util.gpu [%], util.memory [%], temp [C]
                # e.g., "32, 12, 68"
                cmd = "nvidia-smi --query-gpu=utilization.gpu,utilization.memory,temperature.gpu --format=csv,noheader,nounits"
                res = ssh_manager.execute(ip, user, port, cmd, timeout=5)
                
                inner_db = SessionLocal()
                node_db = inner_db.query(Node).filter(Node.id == node_id).first()
                if not node_db:
                    inner_db.close()
                    return

                if res is None:
                    # SSH call failed or timed out. If it was active/training, mark as failed/offline
                    if node_db.status in ["active", "training"]:
                        node_db.status = "failed"
                        inner_db.commit()
                else:
                    # Parse lines (could be multi-GPU)
                    lines = [line.strip() for line in res.strip().split('\n') if line.strip()]
                    gpu_utils = []
                    vram_utils = []
                    temps = []
                    
                    for line in lines:
                        try:
                            # Parse CSV: "32, 12, 68"
                            parts = [p.strip() for p in line.split(',')]
                            if len(parts) >= 3:
                                gpu_utils.append(int(parts[0]))
                                vram_utils.append(int(parts[1]))
                                temps.append(int(parts[2]))
                        except ValueError:
                            pass
                    
                    # If parsing succeeded, save metric
                    if gpu_utils:
                        # If node was failed, set it back to active
                        if node_db.status == "failed":
                            node_db.status = "active"
                        
                        metric = NodeMetric(
                            node_id=node_id,
                            gpu_util=json.dumps(gpu_utils),
                            vram_util=json.dumps(vram_utils),
                            temp=json.dumps(temps)
                        )
                        inner_db.add(metric)
                        inner_db.commit()
                inner_db.close()

            for node in nodes:
                t = threading.Thread(target=scrape_node, args=(node.id, node.ip, node.ssh_user, node.ssh_port), daemon=True)
                t.start()
                threads.append(t)
                
            for t in threads:
                t.join(timeout=6) # Wait for all threads to join
                
        except Exception as e:
            print(f"Error scraping GPU metrics: {e}")
        finally:
            db.close()
            
        time.sleep(5)  # Scrape every 5 seconds

# Start background scraper thread
daemon_thread = threading.Thread(target=scrape_gpu_metrics, daemon=True)
daemon_thread.start()

@router.get("/metrics", response_model=dict[str, list[NodeMetricResponse]])
def get_metrics(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    # Returns the latest 20 metrics for each node in the cluster
    nodes = db.query(Node).all()
    results = {}
    
    for node in nodes:
        metrics = db.query(NodeMetric).filter(
            NodeMetric.node_id == node.id
        ).order_by(NodeMetric.timestamp.desc()).limit(20).all()
        
        # Sort in ascending order for graphing
        metrics.reverse()
        results[node.ip] = metrics
        
    return results
