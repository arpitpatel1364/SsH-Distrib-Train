from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime

# --- AUTH SCHEMAS ---
class UserBase(BaseModel):
    username: str

class UserCreate(UserBase):
    password: str

class UserResponse(UserBase):
    id: int
    created_at: datetime
    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str

class LoginRequest(BaseModel):
    username: str
    password: str

# --- NODE SCHEMAS ---
class NodeBase(BaseModel):
    ip: str
    ssh_user: str
    ssh_port: int = 22

class NodeCreate(NodeBase):
    pass

class NodeResponse(NodeBase):
    id: int
    status: str
    gpu_count: int
    gpu_info: str
    last_seen: datetime
    remote_deploy_path: Optional[str] = None
    deploy_status: str = "never"
    last_sync_time: Optional[datetime] = None
    class Config:
        from_attributes = True

class NodeOTAStatus(BaseModel):
    """Rich OTA view for the OTA management page."""
    id: int
    ip: str
    ssh_user: str
    ssh_port: int
    status: str
    remote_deploy_path: Optional[str] = None
    deploy_status: str = "never"
    last_sync_time: Optional[datetime] = None
    class Config:
        from_attributes = True

# --- JOB SCHEMAS ---
class JobBase(BaseModel):
    model_name: str = "yolov8n.pt"
    dataset_path: str
    epochs: int = 10
    batch_size: int = 16
    learning_rate: float = 0.01

class JobCreate(JobBase):
    pass

class JobResponse(JobBase):
    id: str
    status: str
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    current_epoch: int
    assigned_node: Optional[str] = None
    command: Optional[str] = None
    class Config:
        from_attributes = True

# --- METRIC SCHEMAS ---
class NodeMetricResponse(BaseModel):
    id: int
    node_id: int
    timestamp: datetime
    gpu_util: str
    vram_util: str
    temp: str
    class Config:
        from_attributes = True

class TrainingMetricResponse(BaseModel):
    id: int
    job_id: str
    epoch: Optional[int] = None
    box_loss: float
    cls_loss: float
    dfl_loss: float
    map50: float
    map50_95: float
    gpu_util: Optional[float] = None
    vram_util: Optional[float] = None
    temp: Optional[float] = None
    timestamp: datetime
    class Config:
        from_attributes = True
