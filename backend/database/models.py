from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Float
from sqlalchemy.orm import relationship
from datetime import datetime
from backend.database.db import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class Node(Base):
    __tablename__ = "nodes"
    id = Column(Integer, primary_key=True, index=True)
    ip = Column(String, unique=True, index=True, nullable=False)
    ssh_user = Column(String, nullable=False)
    ssh_port = Column(Integer, default=22)
    status = Column(String, default="offline")  # offline, active, failed, training
    gpu_count = Column(Integer, default=0)
    gpu_info = Column(String, default="[]")      # JSON array of GPU names
    last_seen = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    metrics = relationship("NodeMetric", back_populates="node", cascade="all, delete-orphan")

class NodeMetric(Base):
    __tablename__ = "node_metrics"
    id = Column(Integer, primary_key=True, index=True)
    node_id = Column(Integer, ForeignKey("nodes.id"), nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    gpu_util = Column(String, default="[]")       # JSON array of GPU util %
    vram_util = Column(String, default="[]")      # JSON array of VRAM usage in MB or %
    temp = Column(String, default="[]")           # JSON array of GPU temps in C
    node = relationship("Node", back_populates="metrics")

class Job(Base):
    __tablename__ = "jobs"
    id = Column(String, primary_key=True, index=True)
    status = Column(String, default="pending")    # pending, running, completed, failed, stopped, degraded, retry
    model_name = Column(String, default="yolov8n.pt")
    dataset_path = Column(String, nullable=True)
    epochs = Column(Integer, default=10)
    batch_size = Column(Integer, default=16)
    learning_rate = Column(Float, default=0.01)
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    current_epoch = Column(Integer, default=0)
    assigned_node = Column(String, nullable=True)  # IP of the node assigned to run this sub-job
    command = Column(String, nullable=True)        # The specific command for the worker
    training_metrics = relationship("TrainingMetric", back_populates="job", cascade="all, delete-orphan")

class TrainingMetric(Base):
    __tablename__ = "training_metrics"
    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False)
    epoch = Column(Integer, nullable=True)
    box_loss = Column(Float, default=0.0)
    cls_loss = Column(Float, default=0.0)
    dfl_loss = Column(Float, default=0.0)
    map50 = Column(Float, default=0.0)
    map50_95 = Column(Float, default=0.0)
    gpu_util = Column(Float, nullable=True)
    vram_util = Column(Float, nullable=True)
    temp = Column(Float, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    job = relationship("Job", back_populates="training_metrics")
