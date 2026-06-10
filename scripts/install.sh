#!/bin/bash
# Master node setup installer

echo "=== Creating Virtual Environment ==="
python3 -m venv venv
source venv/bin/activate

echo "=== Installing Backend dependencies ==="
pip install --upgrade pip
pip install fastapi uvicorn sqlalchemy paramiko python-jose[cryptography] passlib[bcrypt] pydantic cryptography

echo "=== Setup complete ==="

