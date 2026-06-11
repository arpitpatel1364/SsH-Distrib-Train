import torch
import json
import sys
import os
import time
import socket
import argparse
import requests
import threading
import subprocess

def get_gpu_metrics():
    try:
        out = subprocess.check_output(
            "nvidia-smi --query-gpu=utilization.gpu,utilization.memory,temperature.gpu --format=csv,noheader,nounits",
            shell=True
        ).decode().strip()
        parts = [float(p.strip()) for p in out.split(',')]
        return parts[0], parts[1], parts[2]
    except Exception:
        return 0.0, 0.0, 0.0

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def scan_worker():
    gpus = []
    cuda_available = torch.cuda.is_available()
    gpu_count = torch.cuda.device_count() if cuda_available else 0
    for i in range(gpu_count):
        gpus.append(torch.cuda.get_device_name(i))
    if not gpus:
        gpus = ["CPU Only"]
    return gpu_count, gpus

def heartbeat_loop(master_url, node_ip):
    while True:
        try:
            gpu_util, vram_util, temp = get_gpu_metrics()
            payload = {
                "node_id": node_ip,
                "gpu": gpu_util,
                "vram": vram_util,
                "temp": temp
            }
            requests.post(f"{master_url}/nodes/heartbeat", json=payload, timeout=3)
        except Exception as e:
            print(f"[Heartbeat Error] Failed to send heartbeat to master: {e}")
        time.sleep(5)

def main():
    parser = argparse.ArgumentParser(description="Persistent Distributed Training Worker Agent")
    parser.add_argument("--master", type=str, default="http://localhost:8000", help="Master Orchestrator URL")
    parser.add_argument("--ip", type=str, default=None, help="IP address of this worker node")
    parser.add_argument("--ssh-user", type=str, default="cactus", help="SSH username")
    parser.add_argument("--ssh-port", type=int, default=22, help="SSH port")
    args = parser.parse_args()

    master_url = args.master.rstrip("/")
    node_ip = args.ip if args.ip else get_local_ip()

    print(f"[*] Starting worker agent on node IP: {node_ip} targeting master: {master_url}")

    # 1. Scan hardware
    gpu_count, gpu_info = scan_worker()
    print(f"[*] Hardware scanned: {gpu_count} GPU(s) - {gpu_info}")

    # 2. Register with Master
    registered = False
    while not registered:
        try:
            payload = {
                "ip": node_ip,
                "ssh_user": args.ssh_user,
                "ssh_port": args.ssh_port,
                "gpu_count": gpu_count,
                "gpu_info": gpu_info
            }
            res = requests.post(f"{master_url}/nodes/register", json=payload, timeout=5)
            if res.status_code == 200:
                print(f"[+] Successfully registered with master. Node ID: {res.json().get('node_id')}")
                registered = True
            else:
                print(f"[-] Registration returned code {res.status_code}. Retrying...")
                time.sleep(5)
        except Exception as e:
            print(f"[-] Registration connection failed: {e}. Retrying in 5 seconds...")
            time.sleep(5)

    # 3. Start Heartbeat Thread
    hb_thread = threading.Thread(target=heartbeat_loop, args=(master_url, node_ip), daemon=True)
    hb_thread.start()
    print("[*] Heartbeat daemon started.")

    # 4. Main Job Polling & Execution Loop
    print("[*] Polling for jobs...")
    while True:
        try:
            res = requests.get(f"{master_url}/train/jobs/next?node_ip={node_ip}", timeout=5)
            if res.status_code == 200 and res.json() is not None:
                job = res.json()
                job_id = job["job_id"]
                master_job_id = job["master_job_id"]
                cmd = job["command"]
                
                print(f"\n[!] Pull-Queue: Received Job #{job_id}. Executing command: {cmd}")
                
                # Get current system path and prepend python's bin directory to locate torchrun
                env = os.environ.copy()
                bin_dir = os.path.dirname(sys.executable)
                env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")
                
                # Execute training command
                process = subprocess.Popen(
                    cmd,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    cwd=".", # Run in workspace directory
                    env=env
                )
                
                # Read stdout line-by-line in real-time and POST to master
                for line in process.stdout:
                    sys.stdout.write(line)
                    sys.stdout.flush()
                    try:
                        requests.post(
                            f"{master_url}/train/jobs/{master_job_id}/logs",
                            json={"log": line.strip()},
                            timeout=2
                        )
                    except Exception:
                        pass
                
                process.wait()
                exit_code = process.returncode
                
                if exit_code == 0:
                    print(f"[+] Job #{job_id} completed successfully.")
                    requests.post(
                        f"{master_url}/train/jobs/{job_id}/status",
                        json={"status": "completed"},
                        timeout=5
                    )
                else:
                    print(f"[-] Job #{job_id} failed with exit code {exit_code}.")
                    requests.post(
                        f"{master_url}/train/jobs/{job_id}/status",
                        json={"status": "failed"},
                        timeout=5
                    )
            
            elif res.status_code == 204:
                # No jobs available
                pass
                
        except Exception as e:
            print(f"[Error] Loop execution exception: {e}")
            
        time.sleep(2)

if __name__ == "__main__":
    main()
