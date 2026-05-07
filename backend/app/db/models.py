from sqlalchemy import Column, String, DateTime, JSON
from sqlalchemy.orm import DeclarativeBase
from datetime import datetime

# Correct SQLAlchemy 2.0 syntax: inherit, don't instantiate
class Base(DeclarativeBase):
    pass

class Job(Base):
    __tablename__ = "jobs"
    
    id = Column(String(36), primary_key=True, index=True)
    status = Column(String(20), default="pending", index=True)  # pending, processing, completed, failed
    s3_key = Column(String(255), nullable=True)
    result = Column(JSON, nullable=True)
    # Use naive datetime for PostgreSQL TIMESTAMP WITHOUT TIME ZONE compatibility
    created_at = Column(DateTime, default=datetime.utcnow)