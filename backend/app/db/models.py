from sqlalchemy import Column, String, DateTime, JSON
from sqlalchemy.orm import DeclarativeBase
from datetime import datetime  # <-- Do NOT import timezone here

class Base(DeclarativeBase):
    pass

class Job(Base):
    __tablename__ = "jobs"
    
    id = Column(String(36), primary_key=True, index=True)
    user_id = Column(String(36), index=True, nullable=True)
    status = Column(String(20), default="pending", index=True)
    s3_key = Column(String(255), nullable=True)
    result = Column(JSON, nullable=True)
    # Use naive datetime for PostgreSQL compatibility
    created_at = Column(DateTime, default=datetime.utcnow) 