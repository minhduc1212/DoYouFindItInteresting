"""
Database configuration using SQLAlchemy + SQLite.
The database file is stored at the project root for easy access.
"""

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os

# Store the DB file one level up (project root), next to both backend/ and frontend/
DB_PATH = os.path.join(os.path.dirname(__file__), "..", "til_database.db")
DATABASE_URL = f"sqlite:///{os.path.abspath(DB_PATH)}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}  # Required for SQLite with FastAPI
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()