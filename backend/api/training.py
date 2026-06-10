from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from backend.database.db import get_db
from backend.database.models import Job, Node, TrainingMetric
from backend.database.schemas import JobCreate, JobResponse, TrainingMetricResponse
from backend.auth.security import get_current_user
from backend.training.trainer import launch_job_in_background, stop_job_by_id, get_job_logs

router = APIRouter(prefix="/train", tags=["training"])

@router.post("/start", response_model=JobResponse)
def start_training_job(
    job_in: JobCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    # Check if there is already a running job
    active_job = db.query(Job).filter(Job.status == "running").first()
    if active_job:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="There is already a training job running. Stop it before starting a new one."
        )

    # Check if there are active nodes
    active_nodes = db.query(Node).filter(Node.status == "active").count()
    if active_nodes == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active nodes in the cluster. Register and refresh nodes first."
        )

    job = Job(
        model_name=job_in.model_name,
        dataset_path=job_in.dataset_path,
        epochs=job_in.epochs,
        batch_size=job_in.batch_size,
        learning_rate=job_in.learning_rate,
        status="pending"
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Launch DDP background training manager
    launch_job_in_background(job.id)
    return job

@router.get("/jobs", response_model=list[JobResponse])
def list_jobs(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    return db.query(Job).order_by(Job.created_at.desc()).all()

@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(
    job_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job

@router.post("/jobs/{job_id}/stop")
def stop_job(
    job_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if job.status != "running" and job.status != "pending":
        raise HTTPException(status_code=400, detail="Job is not active")

    stopped = stop_job_by_id(job_id)
    if not stopped:
        # Fallback update DB state
        job.status = "stopped"
        db.commit()

    return {"message": "Job stop signal issued."}

@router.get("/jobs/{job_id}/logs")
def get_logs(
    job_id: int,
    current_user=Depends(get_current_user)
):
    logs = get_job_logs(job_id)
    return {"logs": logs}

@router.get("/jobs/{job_id}/metrics", response_model=list[TrainingMetricResponse])
def get_job_metrics(
    job_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    return db.query(TrainingMetric).filter(
        TrainingMetric.job_id == job_id
    ).order_by(TrainingMetric.epoch.asc()).all()


