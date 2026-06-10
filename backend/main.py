from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.database.db import init_db, SessionLocal
from backend.database.models import User
from backend.auth.security import get_password_hash
from backend.api import nodes, training, monitoring, websockets
import os

app = FastAPI(title="Enterprise Distributed YOLO Cluster Management Platform")

# CORS middleware config to allow Next.js/Vite frontend interactions
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize database schema
init_db()

# Seed default admin user if database is empty
def seed_admin_user():
    db = SessionLocal()
    try:
        admin_exists = db.query(User).filter(User.username == "admin").first()
        if not admin_exists:
            hashed_pwd = get_password_hash("admin123")
            admin = User(username="admin", password_hash=hashed_pwd)
            db.add(admin)
            db.commit()
            print("Default admin user created: admin / admin123")
    except Exception as e:
        print(f"Error seeding database: {e}")
    finally:
        db.close()

seed_admin_user()

# Include routers
app.include_router(websockets.router)
app.include_router(nodes.router)
app.include_router(training.router)
app.include_router(monitoring.router)
from backend.auth import router as auth_router
app.include_router(auth_router.router)

@app.on_event("startup")
async def startup_event():
    # Start the WebSocket broadcast service
    websockets.start_broadcast_task()

from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

@app.get("/api/status")
def status():
    return {
        "status": "online",
        "service": "YOLO Distributed Orchestrator master node",
        "api_docs": "/docs"
    }

@app.get("/")
def serve_ui():
    return FileResponse("project/index.html")

app.mount("/", StaticFiles(directory="project"), name="static")
