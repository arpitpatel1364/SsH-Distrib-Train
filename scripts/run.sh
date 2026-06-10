#!/bin/bash
# Master execution runner script

echo "=== Activating Virtual Environment ==="
source venv/bin/activate

echo "=== Starting FastAPI Backend ==="
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload

