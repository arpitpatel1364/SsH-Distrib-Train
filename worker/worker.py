import json
import sys
import os
import time
import socket
import argparse
import threading
import subprocess
import signal

# Check and install dependencies at startup
def check_and_install_dependencies():
    print("[*] Running dependency and environment checks...")
    
    # 1. Virtual Environment check
    is_venv = (sys.prefix != sys.base_prefix) or 'VIRTUAL_ENV' in os.environ
    if is_venv:
        print("[+] Environment check: Running inside a Virtual Environment.")
    else:
        print("[!] Warning: Not running inside a Virtual Environment. System-wide python packages will be affected.")

    # 2. NVIDIA Driver & GPU check
    try:
        subprocess.check_output("nvidia-smi", shell=True, stderr=subprocess.DEVNULL)
        print("[+] Driver check: NVIDIA driver is installed and nvidia-smi is working.")
    except Exception:
        print("[!] Driver check: nvidia-smi not found or failed. GPU training may not be available (CPU only).")

    # 3. Pip dependencies check & install
    required_packages = {
        "requests": "requests",
        "torch": "torch"
    }
    
    for lib_name, pip_name in required_packages.items():
        try:
            __import__(lib_name)
            print(f"[+] Dependency check: '{lib_name}' is already installed.")
        except ImportError:
            print(f"[!] Dependency check: '{lib_name}' is missing. Attempting automatic installation via pip...")
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install", pip_name])
                print(f"[+] Dependency check: Successfully installed '{lib_name}' via pip.")
            except Exception as e:
                print(f"[-] Dependency check error: Failed to install '{lib_name}'. Error: {e}")
                sys.exit(1)

check_and_install_dependencies()

import torch
import requests

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
    parser.add_argument("--master", type=str, default=None, help="Master Orchestrator URL")
    parser.add_argument("--ip", type=str, default=None, help="IP address of this worker node")
    parser.add_argument("--ssh-user", type=str, default="cactus", help="SSH username")
    parser.add_argument("--ssh-port", type=int, default=22, help="SSH port")
    args = parser.parse_args()

    master_url = args.master
    if master_url:
        master_url = master_url.rstrip("/")

    # Keep asking until a valid, reachable URL is confirmed
    while True:
        if not master_url:
            try:
                master_url = input("\nEnter Master Orchestrator URL (e.g., http://192.168.1.21:8000): ").strip().rstrip("/")
            except EOFError:
                print("\n[!] Non-interactive mode: --master argument is required.")
                sys.exit(1)

        if not master_url:
            print("[!] URL cannot be empty. Please try again.")
            master_url = None
            continue

        # Basic format check
        if not (master_url.startswith("http://") or master_url.startswith("https://")):
            print(f"[!] '{master_url}' does not look like a valid URL (must start with http:// or https://). Try again.")
            master_url = None
            continue

        # Connectivity check
        print(f"[*] Testing connection to master at {master_url} ...")
        try:
            test = requests.get(f"{master_url}/health", timeout=4)
            print(f"[+] Master reachable (status {test.status_code}). Proceeding.")
            break
        except requests.exceptions.ConnectionError:
            print(f"[-] Cannot connect to '{master_url}'. Make sure the master is running and the URL is correct.")
        except requests.exceptions.Timeout:
            print(f"[-] Connection to '{master_url}' timed out. Check the IP/port and try again.")
        except Exception as e:
            print(f"[-] Unexpected error while connecting: {e}")

        retry = input("    Re-enter a different URL? (Y/n): ").strip().lower()
        if retry == "n":
            print("[!] Aborted by user.")
            sys.exit(1)
        master_url = None  # force re-prompt

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
                if not os.path.exists("worker/trainer.py") and os.path.exists("trainer.py"):
                    cmd = cmd.replace("worker/trainer.py", "trainer.py")
                
                print(f"\n[!] Pull-Queue: Received Job #{job_id}. Executing command: {cmd}")
                
                # Download checkpoint if available on the master
                try:
                    os.makedirs("worker", exist_ok=True)
                    chk_url = f"{master_url}/train/jobs/{master_job_id}/checkpoint"
                    print(f"[*] Checking for checkpoint on master: {chk_url}")
                    chk_res = requests.get(chk_url, timeout=10)
                    if chk_res.status_code == 200:
                        local_chk_path = f"worker/checkpoint_job_{master_job_id}.pt"
                        with open(local_chk_path, "wb") as f:
                            f.write(chk_res.content)
                        print(f"[+] Downloaded checkpoint from master to {local_chk_path}")
                except Exception as e:
                    print(f"[-] Failed to download checkpoint: {e}")

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
                    env=env,
                    preexec_fn=os.setsid
                )
                
                # Flag to coordinate thread termination
                stop_watcher = False
                
                def job_status_watcher():
                    while not stop_watcher:
                        try:
                            # Poll status every 3 seconds
                            for _ in range(6):
                                time.sleep(0.5)
                                if stop_watcher:
                                    return
                            
                            res = requests.get(f"{master_url}/train/jobs/{master_job_id}", timeout=2)
                            if res.status_code == 200:
                                status = res.json().get("status")
                                if status in ["failed", "retry", "stopped"]:
                                    print(f"\n[!] Job status changed to {status}. Force terminating local training process group...")
                                    try:
                                        import signal
                                        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                                    except Exception:
                                        process.kill()
                                    break
                        except Exception:
                            pass
                
                watcher_thread = threading.Thread(target=job_status_watcher, daemon=True)
                watcher_thread.start()
                
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
                stop_watcher = True
                watcher_thread.join(timeout=1.0)
                exit_code = process.returncode
                
                if exit_code == 0:
                    print(f"[+] Job #{job_id} completed successfully.")
                    try:
                        requests.post(
                            f"{master_url}/train/jobs/{job_id}/status",
                            json={"status": "completed"},
                            timeout=5
                        )
                    except Exception:
                        pass
                else:
                    print(f"[-] Job #{job_id} failed with exit code {exit_code}.")
                    try:
                        requests.post(
                            f"{master_url}/train/jobs/{job_id}/status",
                            json={"status": "failed"},
                            timeout=5
                        )
                    except Exception:
                        pass

                # Check master job status — exit cleanly if the full training run is done
                try:
                    status_res = requests.get(f"{master_url}/train/jobs/{master_job_id}", timeout=5)
                    if status_res.status_code == 200:
                        master_status = status_res.json().get("status", "")
                        if master_status in ("completed", "stopped"):
                            print("\n" + "=" * 56)
                            print(" ✅  YOUR JOB IS DONE! Training has finished successfully.")
                            print("    This worker node will now stop processing.")
                            print("=" * 56)
                            sys.exit(0)
                except Exception:
                    pass

            elif res.status_code == 204:
                print("NO JOBS AVAILABLE IN THE QUEUE")# No jobs available
                pass

        except Exception as e:
            print(f"[Error] Loop execution exception: {e}")

        time.sleep(2)

if __name__ == "__main__":
    main()
