import paramiko
import time
import os
import threading
import logging
from typing import Dict, Tuple, Callable, Optional, Any

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SSHManager")

class SSHManager:
    def __init__(self):
        self.pool: Dict[Tuple[str, str, int], paramiko.SSHClient] = {}
        self.pool_lock = threading.Lock()
        # Keep track of active async execution channels and their threads so we can stop them
        self.active_jobs: Dict[str, Tuple[paramiko.Channel, threading.Thread]] = {}
        self.jobs_lock = threading.Lock()

    def _get_client(self, host: str, user: str, port: int = 22, timeout: int = 10) -> Optional[paramiko.SSHClient]:
        key = (host, user, port)
        
        # 1. Quick check for existing active client under lock
        with self.pool_lock:
            client = self.pool.get(key)
            if client:
                transport = client.get_transport()
                if transport and transport.is_active():
                    return client
                else:
                    try:
                        client.close()
                    except Exception:
                        pass
                    self.pool.pop(key, None)

        # 2. Perform connection attempt OUTSIDE the lock to prevent blocking other nodes
        connected_client = None
        for attempt in range(1, 4):
            try:
                logger.info(f"Connecting to {user}@{host}:{port} (Attempt {attempt}/3)")
                client = paramiko.SSHClient()
                client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                
                ssh_key_paths = [
                    os.path.expanduser("~/.ssh/id_rsa"),
                    os.path.expanduser("~/.ssh/id_dsa"),
                    os.path.expanduser("~/.ssh/id_ecdsa"),
                    os.path.expanduser("~/.ssh/id_ed25519")
                ]
                
                pkey = None
                for key_path in ssh_key_paths:
                    if os.path.exists(key_path):
                        try:
                            if "ed25519" in key_path:
                                pkey = paramiko.Ed25519Key.from_private_key_file(key_path)
                            else:
                                pkey = paramiko.RSAKey.from_private_key_file(key_path)
                            break
                        except Exception:
                            continue

                client.connect(
                    hostname=host,
                    username=user,
                    port=port,
                    pkey=pkey,
                    timeout=timeout,
                    allow_agent=True,
                    look_for_keys=True
                )
                connected_client = client
                logger.info(f"Successfully connected to {user}@{host}:{port}")
                break
            except Exception as e:
                logger.warning(f"Connection to {host} failed on attempt {attempt}: {e}")
                if attempt < 3:
                    time.sleep(2)
                else:
                    logger.error(f"Failed to connect to {host} after 3 attempts.")

        if connected_client:
            # 3. Store client under lock
            with self.pool_lock:
                existing = self.pool.get(key)
                if existing:
                    transport = existing.get_transport()
                    if transport and transport.is_active():
                        try:
                            connected_client.close()
                        except Exception:
                            pass
                        return existing
                self.pool[key] = connected_client
                return connected_client
        return None

    def execute(self, host: str, user: str, port: int = 22, cmd: str = "", timeout: int = 10) -> Optional[str]:
        client = self._get_client(host, user, port, timeout)
        if not client:
            return None
        try:
            stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
            exit_status = stdout.channel.recv_exit_status()
            if exit_status != 0:
                err = stderr.read().decode().strip()
                logger.warning(f"Command '{cmd}' on {host} exited with status {exit_status}: {err}")
            return stdout.read().decode().strip()
        except Exception as e:
            logger.error(f"Failed to execute command '{cmd}' on {host}: {e}")
            return None

    def execute_async(
        self, 
        job_id: str, 
        host: str, 
        user: str, 
        port: int, 
        cmd: str, 
        on_line: Callable[[str], None], 
        on_finish: Callable[[int, str], None]
    ) -> bool:
        """
        Executes a command asynchronously in a separate thread.
        on_line: Callback function called when a line of stdout/stderr is received.
        on_finish: Callback function called with (exit_status, host) when completed.
        """
        def worker_thread():
            client = self._get_client(host, user, port)
            if not client:
                on_finish(-1, f"Failed to connect to {host}")
                return
            channel = None
            try:
                transport = client.get_transport()
                channel = transport.open_session()
                
                # Store the channel so it can be terminated
                with self.jobs_lock:
                    self.active_jobs[f"{job_id}_{host}"] = (channel, threading.current_thread())
                
                channel.exec_command(cmd)
                
                # Buffer stdout and stderr lines
                stdout_file = channel.makefile('r')
                
                for line in stdout_file:
                    on_line(f"[{host}] {line.rstrip()}")
                
                exit_status = channel.recv_exit_status()
                logger.info(f"Command finished on {host} with status {exit_status}")
                on_finish(exit_status, host)
            except Exception as e:
                logger.error(f"Error executing async command on {host}: {e}")
                on_finish(-2, host)
            finally:
                if channel:
                    try:
                        channel.close()
                    except Exception:
                        pass
                with self.jobs_lock:
                    self.active_jobs.pop(f"{job_id}_{host}", None)

        thread = threading.Thread(target=worker_thread, daemon=True)
        thread.start()
        return True

    def stop_async_job(self, job_id: str, host: str):
        key = f"{job_id}_{host}"
        with self.jobs_lock:
            if key in self.active_jobs:
                channel, thread = self.active_jobs[key]
                try:
                    logger.info(f"Sending SIGINT/SIGTERM to job {job_id} on {host}")
                    # Try to close channel which kills the remote command
                    channel.close()
                except Exception as e:
                    logger.error(f"Failed to close channel for job {job_id} on {host}: {e}")
                self.active_jobs.pop(key, None)

    def close_all(self):
        with self.pool_lock:
            for key, client in list(self.pool.items()):
                try:
                    client.close()
                except Exception:
                    pass
            self.pool.clear()

ssh_manager = SSHManager()
