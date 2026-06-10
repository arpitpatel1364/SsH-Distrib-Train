import os
import json
import threading
import logging
from datetime import datetime
from sqlalchemy.orm import Session
from backend.database.db import SessionLocal
from backend.database.models import Node, Job, TrainingMetric
from backend.ssh.ssh_manager import ssh_manager

logger = logging.getLogger("Trainer")

# Global dict to store live training logs: job_id -> list of log strings
job_logs = {}
# Active job runners to prevent overlapping triggers
active_job_runners = {}

def get_job_logs(job_id: int):
    return job_logs.get(job_id, [])

def add_job_log(job_id: int, log_line: str):
    if job_id not in job_logs:
        job_logs[job_id] = []
    # Limit to last 1000 lines
    job_logs[job_id].append(log_line)
    if len(job_logs[job_id]) > 1000:
        job_logs[job_id].pop(0)

# Redundant DistributedJobRunner definition removed

def mark_node_failed(node_id: int):
    db = SessionLocal()
    try:
        node = db.query(Node).filter(Node.id == node_id).first()
        if node:
            node.status = "failed"
            db.commit()
            logger.warning(f"Node {node.ip} has been marked as FAILED in the database.")
    except Exception as e:
        logger.error(f"Error in mark_node_failed: {e}")
    finally:
        db.close()

class DistributedJobRunner:
    def __init__(self, job_id: int):
        self.job_id = job_id
        self.lock = threading.Lock()
        self.running_hosts = set()
        self.failed_hosts = set()
        self.is_stopped = False
        self.nodes_list = []

    def deploy_worker_package(self, host: str, user: str, port: int) -> bool:
        """Deploys the local worker directory to the remote node via SFTP."""
        try:
            add_job_log(self.job_id, f"Deploying worker scripts to {host}...")
            client = ssh_manager._get_client(host, user, port)
            if not client:
                return False
            
            sftp = client.open_sftp()
            
            # Ensure remote ~/worker directory exists
            try:
                sftp.mkdir("worker")
            except IOError:
                pass # Already exists
            
            local_worker_dir = "/home/cactus/Desktop/ssh/worker"
            if not os.path.exists(local_worker_dir):
                os.makedirs(local_worker_dir, exist_ok=True)
                
            for filename in os.listdir(local_worker_dir):
                local_path = os.path.join(local_worker_dir, filename)
                if os.path.isfile(local_path):
                    sftp.put(local_path, f"worker/{filename}")
                    
            sftp.close()
            add_job_log(self.job_id, f"Worker scripts successfully deployed to {host}")
            return True
        except Exception as e:
            add_job_log(self.job_id, f"Deployment failed to {host}: {e}")
            return False

    def start_training(self):
        db = SessionLocal()
        try:
            job = db.query(Job).filter(Job.id == self.job_id).first()
            if not job:
                logger.error(f"Job {self.job_id} not found in DB.")
                return

            job.status = "running"
            job.started_at = datetime.utcnow()
            db.commit()

            # Retrieve active nodes
            nodes = db.query(Node).filter(Node.status == "active").all()
            if not nodes:
                add_job_log(self.job_id, "No active nodes available to start training.")
                job.status = "failed"
                job.finished_at = datetime.utcnow()
                db.commit()
                return

            self.nodes_list = [
                {
                    "ip": n.ip, 
                    "user": n.ssh_user, 
                    "port": n.ssh_port, 
                    "id": n.id, 
                    "gpu_count": max(1, n.gpu_count)
                } for n in nodes
            ]

            # --- MLOps Verification: Check PyTorch / CUDA environment consistency ---
            add_job_log(self.job_id, "Validating cluster environment consistency and auto-detecting GPU/interface...")
            
            import concurrent.futures
            node_results = {}
            mismatch_found = False
            
            def check_node(n_info):
                check_cmd = (
                    "bash -lc \""
                    "if [ -d 'venv' ]; then source venv/bin/activate; fi; "
                    "if [ -d '~/venv' ]; then source ~/venv/bin/activate; fi; "
                    "python3 -c \\\""
                    "import torch, json, subprocess; "
                    "gpus = torch.cuda.device_count() if torch.cuda.is_available() else 0; "
                    "iface = ''; "
                    "try: "
                    "    out = subprocess.check_output('ip route get 8.8.8.8', shell=True).decode(); "
                    "    parts = out.split(); "
                    "    if 'dev' in parts: "
                    "        iface = parts[parts.index('dev') + 1]; "
                    "except Exception: "
                    "    pass; "
                    "print(json.dumps({'torch_ver': torch.__version__, 'cuda_ver': torch.version.cuda, 'gpus': gpus, 'iface': iface}))"
                    "\\\"\""
                )
                try:
                    res = ssh_manager.execute(n_info["ip"], n_info["user"], n_info["port"], check_cmd, timeout=10)
                    if res is None:
                        return n_info["ip"], {"error": "Failed to connect or execute command."}
                    data = json.loads(res.strip().split("\n")[-1])
                    return n_info["ip"], data
                except Exception as e:
                    return n_info["ip"], {"error": str(e)}

            with concurrent.futures.ThreadPoolExecutor(max_workers=len(self.nodes_list)) as executor:
                futures = {executor.submit(check_node, n): n for n in self.nodes_list}
                for future in concurrent.futures.as_completed(futures):
                    ip, result = future.result()
                    node_results[ip] = result

            base_torch = None
            base_cuda = None
            any_cpu = False
            
            updated_nodes_list = []
            for n_info in self.nodes_list:
                res = node_results.get(n_info["ip"])
                if not res or "error" in res:
                    err_msg = res.get("error", "Unknown error") if res else "No response"
                    add_job_log(self.job_id, f"❌ Node {n_info['ip']} validation failed: {err_msg}")
                    mismatch_found = True
                    mark_node_failed(n_info["id"])
                    continue
                
                torch_ver = res.get("torch_ver")
                cuda_ver = res.get("cuda_ver")
                gpus = res.get("gpus", 0)
                iface = res.get("iface", "eth0")
                if not iface:
                    iface = "eth0"
                
                add_job_log(self.job_id, f"Node {n_info['ip']} - Torch: {torch_ver}, CUDA: {cuda_ver}, GPUs: {gpus}, Interface: {iface}")
                
                if base_torch is None:
                    base_torch = torch_ver
                    base_cuda = cuda_ver
                elif torch_ver != base_torch or cuda_ver != base_cuda:
                    add_job_log(self.job_id, f"❌ Node {n_info['ip']} environment mismatch. Expected Torch {base_torch} CUDA {base_cuda}, got Torch {torch_ver} CUDA {cuda_ver}")
                    mismatch_found = True
                    break
                
                if gpus == 0:
                    any_cpu = True
                
                n_info["gpu_count"] = gpus
                n_info["iface"] = iface
                updated_nodes_list.append(n_info)
            
            if mismatch_found:
                add_job_log(self.job_id, "Job aborted: PyTorch/CUDA environments are inconsistent or nodes are unreachable.")
                job.status = "failed"
                job.finished_at = datetime.utcnow()
                db.commit()
                return

            self.nodes_list = updated_nodes_list
            self.run_ddp_epoch_loop(db, job)

        except Exception as e:
            logger.error(f"Error during training lifecycle: {e}")
        finally:
            db.close()

    def run_ddp_epoch_loop(self, db: Session, job: Job):
        if self.is_stopped:
            return

        nnodes = len(self.nodes_list)
        if nnodes == 0:
            add_job_log(self.job_id, "No remaining worker nodes. Job failed.")
            job.status = "failed"
            job.finished_at = datetime.utcnow()
            db.commit()
            return

        # Determine backend and world size
        any_cpu = any(n["gpu_count"] == 0 for n in self.nodes_list)
        backend = "gloo" if any_cpu else "nccl"
        total_world_size = sum(max(1, n["gpu_count"]) for n in self.nodes_list)

        master_ip = self.nodes_list[0]["ip"]
        # Detect orchestrator IP to pass as orchestrator_url for checkpoint uploads
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            orchestrator_ip = s.getsockname()[0]
            s.close()
        except Exception:
            orchestrator_ip = "127.0.0.1"
            
        orchestrator_url = f"http://{orchestrator_ip}:8000"

        # If master_ip is loopback (dev setup), resolve it to network-reachable IP
        if master_ip in ["127.0.0.1", "localhost"]:
            master_ip = orchestrator_ip
        
        add_job_log(
            self.job_id, 
            f"Starting distributed training. Machines: {nnodes}, Total GPUs (World Size): {total_world_size}, Master IP: {master_ip}, Backend: {backend}"
        )

        for n_info in self.nodes_list:
            node = db.query(Node).filter(Node.id == n_info["id"]).first()
            if node:
                node.status = "training"
        db.commit()

        # Step 1: Deploy scripts to all nodes in parallel
        import concurrent.futures
        valid_nodes = []
        
        def deploy_node(n_info):
            success = self.deploy_worker_package(n_info["ip"], n_info["user"], n_info["port"])
            return n_info, success
            
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(self.nodes_list)) as executor:
            futures = {executor.submit(deploy_node, n): n for n in self.nodes_list}
            for future in concurrent.futures.as_completed(futures):
                n_info, success = future.result()
                if success:
                    valid_nodes.append(n_info)
                else:
                    mark_node_failed(n_info["id"])
                    add_job_log(self.job_id, f"Node {n_info['ip']} marked as failed due to deployment failure.")

        self.nodes_list = valid_nodes
        nnodes = len(self.nodes_list)
        if nnodes == 0:
            add_job_log(self.job_id, "All nodes failed deployment. Job failed.")
            job.status = "failed"
            job.finished_at = datetime.utcnow()
            db.commit()
            return

        master_ip = self.nodes_list[0]["ip"]
        if master_ip in ["127.0.0.1", "localhost"]:
            master_ip = orchestrator_ip
        total_world_size = sum(max(1, n["gpu_count"]) for n in self.nodes_list)
        self.running_hosts.clear()

        # Step 2: Trigger torchrun commands concurrently (non-blocking parallel threads)
        for rank, n_info in enumerate(self.nodes_list):
            nproc_per_node = max(1, n_info["gpu_count"])
            
            cmd = (
                f"export NCCL_SOCKET_IFNAME={n_info.get('iface', 'eth0')} && "
                f"export NCCL_IB_DISABLE=1 && "
                f"export NCCL_DEBUG=INFO && "
                f"bash -lc \""
                f"if [ -d 'venv' ]; then source venv/bin/activate; fi; "
                f"if [ -d '~/venv' ]; then source ~/venv/bin/activate; fi; "
                f"torchrun "
                f"--nnodes={nnodes} "
                f"--node_rank={rank} "
                f"--nproc_per_node={nproc_per_node} "
                f"--master_addr={master_ip} "
                f"--master_port=29500 "
                f"worker/trainer.py "
                f"--world_size {total_world_size} "
                f"--rank {rank} "
                f"--master_addr {master_ip} "
                f"--master_port 29500 "
                f"--backend {backend} "
                f"--orchestrator_url {orchestrator_url} "
                f"--epochs {job.epochs} "
                f"--batch_size {job.batch_size} "
                f"--lr {job.learning_rate} "
                f"--model {job.model_name} "
                f"--dataset {job.dataset_path} "
                f"--job_id {self.job_id}"
                f"\""
            )

            self.running_hosts.add(n_info["ip"])

            def make_line_callback(host):
                return lambda line: self.handle_worker_log(host, line)

            def make_finish_callback(host, node_id):
                return lambda exit_status, msg: self.handle_worker_finish(host, node_id, exit_status, msg)

            success = ssh_manager.execute_async(
                job_id=str(self.job_id),
                host=n_info["ip"],
                user=n_info["user"],
                port=n_info["port"],
                cmd=cmd,
                on_line=make_line_callback(n_info["ip"]),
                on_finish=make_finish_callback(n_info["ip"], n_info["id"])
            )

            if not success:
                self.running_hosts.discard(n_info["ip"])
                mark_node_failed(n_info["id"])
                self.handle_fault(n_info["ip"])
                break

    def handle_worker_log(self, host: str, line: str):
        add_job_log(self.job_id, line)
        
        if "METRICS:" in line:
            try:
                metric_json = line.split("METRICS:")[1].strip()
                data = json.loads(metric_json)
                
                db = SessionLocal()
                existing = db.query(TrainingMetric).filter(
                    TrainingMetric.job_id == self.job_id,
                    TrainingMetric.epoch == data["epoch"]
                ).first()
                
                if not existing:
                    m = TrainingMetric(
                        job_id=self.job_id,
                        epoch=data["epoch"],
                        box_loss=data.get("box_loss", 0.0),
                        cls_loss=data.get("cls_loss", 0.0),
                        dfl_loss=data.get("dfl_loss", 0.0),
                        map50=data.get("map50", 0.0),
                        map50_95=data.get("map50_95", 0.0)
                    )
                    db.add(m)
                    
                    job = db.query(Job).filter(Job.id == self.job_id).first()
                    if job:
                        job.current_epoch = data["epoch"]
                    
                    db.commit()
                db.close()
            except Exception as e:
                logger.error(f"Error parsing metric line: {e}")

    def handle_worker_finish(self, host: str, node_id: int, exit_status: int, error_msg: str):
        with self.lock:
            self.running_hosts.discard(host)
            
            db = SessionLocal()
            node = db.query(Node).filter(Node.id == node_id).first()
            
            if exit_status == 0:
                add_job_log(self.job_id, f"Worker {host} completed successfully.")
                if node and node.status == "training":
                    node.status = "active"
                db.commit()
                
                if not self.running_hosts and not self.is_stopped:
                    job = db.query(Job).filter(Job.id == self.job_id).first()
                    if job and job.status != "completed":
                        job.status = "completed"
                        job.finished_at = datetime.utcnow()
                        add_job_log(self.job_id, "Job finished successfully on all nodes!")
                    db.commit()
            else:
                add_job_log(self.job_id, f"Worker {host} failed or disconnected with status {exit_status}.")
                if node:
                    node.status = "failed"
                db.commit()
                
                if not self.is_stopped:
                    # Launch handle_fault asynchronously on a separate thread to release the lock immediately
                    threading.Thread(target=self.handle_fault, args=(host,), daemon=True).start()
            db.close()

    def handle_fault(self, failed_host: str):
        """Auto recovery logic: stops training on other nodes, removes failed node, and resumes training."""
        add_job_log(self.job_id, f"⚠️ Fault detected on node {failed_host}. Triggering auto-recovery...")
        
        for n_info in self.nodes_list:
            if n_info["ip"] != failed_host:
                ssh_manager.stop_async_job(str(self.job_id), n_info["ip"])
        
        self.nodes_list = [n for n in self.nodes_list if n["ip"] != failed_host]
        
        time.sleep(3)
        
        db = SessionLocal()
        job = db.query(Job).filter(Job.id == self.job_id).first()
        
        if job and job.status == "running" and not self.is_stopped:
            add_job_log(self.job_id, f"Restarting training with remaining {len(self.nodes_list)} nodes...")
            self.run_ddp_epoch_loop(db, job)
        db.close()

    def stop(self):
        with self.lock:
            self.is_stopped = True
            add_job_log(self.job_id, "Stopping job...")
            for n_info in self.nodes_list:
                ssh_manager.stop_async_job(str(self.job_id), n_info["ip"])
            
            db = SessionLocal()
            job = db.query(Job).filter(Job.id == self.job_id).first()
            if job:
                job.status = "stopped"
                job.finished_at = datetime.utcnow()
            
            for n_info in self.nodes_list:
                node = db.query(Node).filter(Node.id == n_info["id"]).first()
                if node and node.status == "training":
                    node.status = "active"
            db.commit()
            db.close()

def launch_job_in_background(job_id: int):
    runner = DistributedJobRunner(job_id)
    active_job_runners[job_id] = runner
    thread = threading.Thread(target=runner.start_training, daemon=True)
    thread.start()

def stop_job_by_id(job_id: int):
    runner = active_job_runners.get(job_id)
    if runner:
        runner.stop()
        active_job_runners.pop(job_id, None)
        return True
    return False
