"""
OTA (Over-The-Air) Management API
Handles all code deployment and synchronization operations:
  - SCP-based initial deployment (first-time setup per node)
  - Rsync-based incremental sync (ongoing updates)
  - Bulk deploy / sync all nodes
  - Deployment path validation
  - Per-node deployment logs
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from backend.database.db import get_db
from backend.database.models import Node
from backend.database.schemas import NodeOTAStatus
from backend.auth.security import get_current_user
from backend.ssh.ssh_manager import ssh_manager
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import os
import zipfile
import uuid
import subprocess
import threading

router = APIRouter(prefix="/ota", tags=["ota"])

# ---------------------------------------------------------------------------
# In-memory log store  { node_id: [str, ...] }
# ---------------------------------------------------------------------------
_deploy_logs: dict = {}
_logs_lock = threading.Lock()

def _append_log(node_id: int, msg: str):
    ts = datetime.utcnow().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    with _logs_lock:
        if node_id not in _deploy_logs:
            _deploy_logs[node_id] = []
        _deploy_logs[node_id].append(line)
        _deploy_logs[node_id] = _deploy_logs[node_id][-200:]

def _clear_logs(node_id: int):
    with _logs_lock:
        _deploy_logs[node_id] = []

def _get_logs(node_id: int) -> List[str]:
    with _logs_lock:
        return list(_deploy_logs.get(node_id, []))

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class SCPDeployPayload(BaseModel):
    remote_path: str
    local_dir: str = "worker"

class RsyncSyncPayload(BaseModel):
    local_dir: str = "worker"

class BulkDeployPayload(BaseModel):
    remote_path: str
    local_dir: str = "worker"
    all_nodes: bool = False

class BulkSyncPayload(BaseModel):
    local_dir: str = "worker"

class ValidatePathsPayload(BaseModel):
    node_ids: Optional[List[int]] = None

# ---------------------------------------------------------------------------
# GET /ota/nodes — list all nodes with OTA status
# ---------------------------------------------------------------------------
@router.get("/nodes", response_model=List[NodeOTAStatus])
def list_ota_nodes(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    return db.query(Node).all()

# ---------------------------------------------------------------------------
# GET /ota/nodes/{node_id}/logs — per-node deployment logs
# ---------------------------------------------------------------------------
@router.get("/nodes/{node_id}/logs")
def get_node_logs(
    node_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    return {"node_id": node_id, "ip": node.ip, "logs": _get_logs(node_id)}

# ---------------------------------------------------------------------------
# POST /ota/nodes/{node_id}/scp-deploy — initial SCP deployment
# ---------------------------------------------------------------------------
@router.post("/nodes/{node_id}/scp-deploy")
def scp_deploy_node(
    node_id: int,
    payload: SCPDeployPayload,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    local_dir = payload.local_dir.strip().rstrip("/")
    if not os.path.isdir(local_dir):
        raise HTTPException(status_code=400, detail=f"Local directory '{local_dir}' does not exist on master.")

    remote_path = payload.remote_path.strip()
    if not remote_path:
        raise HTTPException(status_code=400, detail="Remote deployment path cannot be empty.")

    _clear_logs(node_id)
    _append_log(node_id, f"Starting SCP initial deployment → {node.ip}:{remote_path}")

    node.deploy_status = "pending"
    node.remote_deploy_path = remote_path
    db.commit()

    local_zip = f"/tmp/ota_scp_{uuid.uuid4().hex}.zip"
    try:
        # 1. Zip the local worker directory
        _append_log(node_id, f"Zipping '{local_dir}/' for transfer…")
        with zipfile.ZipFile(local_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            for root_dir, dirs, files in os.walk(local_dir):
                dirs[:] = [d for d in dirs if d not in ("__pycache__", "runs", ".git", "venv")]
                for f in files:
                    if f.endswith(".pyc"):
                        continue
                    abs_path = os.path.join(root_dir, f)
                    arc_name = os.path.relpath(abs_path, start=os.path.dirname(local_dir))
                    zf.write(abs_path, arc_name)
        _append_log(node_id, f"Archive created ({os.path.getsize(local_zip) // 1024} KB)")

        # 2. Get paramiko client via ssh_manager
        client = ssh_manager._get_client(node.ip, node.ssh_user, node.ssh_port)
        if not client:
            raise Exception("Could not establish SSH connection. Ensure the master SSH key is installed on this node.")

        # 3. SFTP upload
        _append_log(node_id, "Uploading via SFTP…")
        remote_zip = f"/tmp/ota_deploy_{uuid.uuid4().hex}.zip"
        sftp = client.open_sftp()
        sftp.put(local_zip, remote_zip)
        sftp.close()
        _append_log(node_id, "Upload complete.")

        # 4. Extract to remote_path on the worker
        parent_dir = os.path.dirname(remote_path)
        _append_log(node_id, f"Extracting to {remote_path}…")
        extract_cmd = (
            f"mkdir -p {remote_path} && "
            f"python3 -c \""
            f"import zipfile, os; z=zipfile.ZipFile('{remote_zip}'); "
            f"[z.extract(m, os.path.expanduser('{parent_dir}')) for m in z.namelist()]; z.close()"
            f"\" && rm {remote_zip}"
        )
        _, stdout, stderr = client.exec_command(extract_cmd)
        exit_code = stdout.channel.recv_exit_status()
        err = stderr.read().decode().strip()
        out = stdout.read().decode().strip()
        if out:
            _append_log(node_id, f"Remote stdout: {out}")
        if err:
            _append_log(node_id, f"Remote stderr: {err}")

        if exit_code != 0:
            raise Exception(f"Remote extraction failed (exit {exit_code}): {err}")

        _append_log(node_id, "✅ SCP deployment successful!")
        node.deploy_status = "success"
        node.remote_deploy_path = remote_path
        node.last_sync_time = datetime.utcnow()
        db.commit()

        return {
            "status": "success",
            "node_ip": node.ip,
            "remote_path": remote_path,
            "detail": f"Worker code deployed to {node.ip}:{remote_path}"
        }

    except Exception as e:
        _append_log(node_id, f"❌ Deployment failed: {e}")
        node.deploy_status = "failed"
        db.commit()
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        if os.path.exists(local_zip):
            os.remove(local_zip)


# ---------------------------------------------------------------------------
# POST /ota/nodes/{node_id}/rsync-sync — incremental rsync update
# ---------------------------------------------------------------------------
@router.post("/nodes/{node_id}/rsync-sync")
def rsync_sync_node(
    node_id: int,
    payload: RsyncSyncPayload,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    if not node.remote_deploy_path:
        raise HTTPException(status_code=400, detail="No remote path configured. Run SCP initial deployment first.")

    local_dir = payload.local_dir.strip().rstrip("/")
    if not os.path.isdir(local_dir):
        raise HTTPException(status_code=400, detail=f"Local directory '{local_dir}' not found.")

    remote_path = node.remote_deploy_path
    _append_log(node_id, f"Starting Rsync sync → {node.ip}:{remote_path}")

    try:
        rsync_cmd = [
            "rsync", "-avz",
            "--exclude=__pycache__", "--exclude=.git",
            "--exclude=runs", "--exclude=*.pyc", "--exclude=venv",
            "--delete",
            "-e", f"ssh -p {node.ssh_port} -o StrictHostKeyChecking=no -o ConnectTimeout=10",
            f"{local_dir}/",
            f"{node.ssh_user}@{node.ip}:{remote_path}/"
        ]
        _append_log(node_id, f"cmd: {' '.join(rsync_cmd)}")
        res = subprocess.run(rsync_cmd, timeout=60, capture_output=True)

        for line in res.stdout.decode().strip().splitlines():
            _append_log(node_id, line)
        for line in res.stderr.decode().strip().splitlines():
            _append_log(node_id, f"[stderr] {line}")

        if res.returncode != 0:
            raise Exception(f"rsync exited with code {res.returncode}: {res.stderr.decode().strip()}")

        _append_log(node_id, "✅ Rsync sync successful!")
        node.deploy_status = "success"
        node.last_sync_time = datetime.utcnow()
        db.commit()

        return {
            "status": "success",
            "node_ip": node.ip,
            "remote_path": remote_path,
            "detail": f"Rsync sync completed for {node.ip}"
        }

    except Exception as e:
        _append_log(node_id, f"❌ Rsync failed: {e}")
        node.deploy_status = "failed"
        db.commit()
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# POST /ota/deploy-all — SCP deploy to all nodes with deploy_status == 'never'
# ---------------------------------------------------------------------------
@router.post("/deploy-all")
def deploy_all_new_nodes(
    payload: BulkDeployPayload,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    if payload.all_nodes:
        target_nodes = db.query(Node).filter(Node.status != "failed").all()
    else:
        target_nodes = db.query(Node).filter(
            Node.deploy_status == "never",
            Node.status != "failed"
        ).all()

    if not target_nodes:
        return {"status": "ok", "detail": "No new nodes to deploy to.", "results": []}

    local_dir = payload.local_dir.strip().rstrip("/")
    if not os.path.isdir(local_dir):
        raise HTTPException(status_code=400, detail=f"Local directory '{local_dir}' not found.")

    local_zip = f"/tmp/ota_bulk_{uuid.uuid4().hex}.zip"
    results = []
    try:
        with zipfile.ZipFile(local_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            for root_dir, dirs, files in os.walk(local_dir):
                dirs[:] = [d for d in dirs if d not in ("__pycache__", "runs", ".git", "venv")]
                for f in files:
                    if f.endswith(".pyc"):
                        continue
                    abs_path = os.path.join(root_dir, f)
                    arc_name = os.path.relpath(abs_path, start=os.path.dirname(local_dir))
                    zf.write(abs_path, arc_name)

        remote_path = payload.remote_path.strip()
        parent_dir = os.path.dirname(remote_path)

        for node in target_nodes:
            _clear_logs(node.id)
            _append_log(node.id, f"Bulk SCP deploy → {node.ip}:{remote_path}")
            node.deploy_status = "pending"
            node.remote_deploy_path = remote_path
            db.commit()
            try:
                client = ssh_manager._get_client(node.ip, node.ssh_user, node.ssh_port)
                if not client:
                    raise Exception("SSH connection failed. Install master key first.")

                remote_zip = f"/tmp/ota_{uuid.uuid4().hex}.zip"
                sftp = client.open_sftp()
                sftp.put(local_zip, remote_zip)
                sftp.close()

                extract_cmd = (
                    f"mkdir -p {remote_path} && "
                    f"python3 -c \""
                    f"import zipfile, os; z=zipfile.ZipFile('{remote_zip}'); "
                    f"[z.extract(m, os.path.expanduser('{parent_dir}')) for m in z.namelist()]; z.close()"
                    f"\" && rm {remote_zip}"
                )
                _, stdout, stderr = client.exec_command(extract_cmd)
                exit_code = stdout.channel.recv_exit_status()
                err = stderr.read().decode().strip()
                if exit_code != 0:
                    raise Exception(f"Extraction failed: {err}")

                node.deploy_status = "success"
                node.last_sync_time = datetime.utcnow()
                db.commit()
                _append_log(node.id, f"✅ Deployed to {node.ip}")
                results.append({"ip": node.ip, "status": "success"})
            except Exception as e:
                node.deploy_status = "failed"
                db.commit()
                _append_log(node.id, f"❌ Failed: {e}")
                results.append({"ip": node.ip, "status": "failed", "error": str(e)})
    finally:
        if os.path.exists(local_zip):
            os.remove(local_zip)

    failed = [r for r in results if r["status"] == "failed"]
    succeeded = [r for r in results if r["status"] == "success"]
    return {
        "status": "partial" if failed else "success",
        "detail": f"Deployed to {len(succeeded)}/{len(results)} nodes.",
        "results": results
    }


# ---------------------------------------------------------------------------
# POST /ota/sync-all — Rsync all nodes that have a remote_deploy_path
# ---------------------------------------------------------------------------
@router.post("/sync-all")
def sync_all_nodes(
    payload: BulkSyncPayload,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    nodes = db.query(Node).filter(
        Node.remote_deploy_path.isnot(None),
        Node.status != "failed"
    ).all()

    if not nodes:
        return {"status": "ok", "detail": "No deployed nodes found to sync.", "results": []}

    local_dir = payload.local_dir.strip().rstrip("/")
    if not os.path.isdir(local_dir):
        raise HTTPException(status_code=400, detail=f"Local directory '{local_dir}' not found.")

    results = []
    for node in nodes:
        _append_log(node.id, f"Bulk Rsync → {node.ip}:{node.remote_deploy_path}")
        try:
            rsync_cmd = [
                "rsync", "-avz",
                "--exclude=__pycache__", "--exclude=.git",
                "--exclude=runs", "--exclude=*.pyc", "--exclude=venv",
                "--delete",
                "-e", f"ssh -p {node.ssh_port} -o StrictHostKeyChecking=no -o ConnectTimeout=10",
                f"{local_dir}/",
                f"{node.ssh_user}@{node.ip}:{node.remote_deploy_path}/"
            ]
            res = subprocess.run(rsync_cmd, timeout=60, capture_output=True)
            for line in res.stdout.decode().strip().splitlines():
                _append_log(node.id, line)
            for line in res.stderr.decode().strip().splitlines():
                _append_log(node.id, f"[stderr] {line}")

            if res.returncode != 0:
                raise Exception(f"rsync exit {res.returncode}: {res.stderr.decode().strip()}")

            node.deploy_status = "success"
            node.last_sync_time = datetime.utcnow()
            db.commit()
            _append_log(node.id, f"✅ Sync done for {node.ip}")
            results.append({"ip": node.ip, "status": "success"})
        except Exception as e:
            node.deploy_status = "failed"
            db.commit()
            _append_log(node.id, f"❌ Sync failed: {e}")
            results.append({"ip": node.ip, "status": "failed", "error": str(e)})

    failed = [r for r in results if r["status"] == "failed"]
    succeeded = [r for r in results if r["status"] == "success"]
    return {
        "status": "partial" if failed else "success",
        "detail": f"Synced {len(succeeded)}/{len(results)} nodes.",
        "results": results
    }


# ---------------------------------------------------------------------------
# POST /ota/validate-paths — check remote deploy paths exist on each node
# ---------------------------------------------------------------------------
@router.post("/validate-paths")
def validate_deployment_paths(
    payload: ValidatePathsPayload,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    query = db.query(Node).filter(Node.remote_deploy_path.isnot(None))
    if payload.node_ids:
        query = query.filter(Node.id.in_(payload.node_ids))
    nodes = query.all()

    if not nodes:
        return {"status": "ok", "detail": "No nodes with configured paths.", "results": []}

    results = []
    for node in nodes:
        try:
            check_cmd = f"test -d {node.remote_deploy_path} && echo EXISTS || echo MISSING"
            result = ssh_manager.execute(node.ip, node.ssh_user, node.ssh_port, check_cmd, timeout=10)
            if result and "EXISTS" in result:
                results.append({"ip": node.ip, "path": node.remote_deploy_path, "status": "valid"})
            else:
                results.append({"ip": node.ip, "path": node.remote_deploy_path, "status": "missing"})
        except Exception as e:
            results.append({"ip": node.ip, "path": node.remote_deploy_path, "status": "error", "error": str(e)})

    return {"status": "ok", "results": results}
