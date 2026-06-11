from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = "sqlite:///./cluster.db"

# Use connect_args to allow access from multiple threads in SQLite
engine = create_engine(
    DATABASE_URL, 
    connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    import os
    if os.path.exists("cluster.db"):
        try:
            os.remove("cluster.db")
            print("Existing cluster.db deleted to apply new schema.")
        except Exception as e:
            print(f"Could not delete cluster.db: {e}")
    import backend.database.models  # Import models to register them
    Base.metadata.create_all(bind=engine)
