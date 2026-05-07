from fastapi import APIRouter, Depends, HTTPException
import boto3
import uuid
import structlog
from botocore.config import Config
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession as SQLAlchemyAsyncSession
from app.config import settings
from app.db.session import AsyncSession
from app.db.models import Job
from app.schemas.jobs import PresignedURLResponse, JobStatusResponse

router = APIRouter(prefix="/jobs", tags=["jobs"])
logger = structlog.get_logger()


async def get_db():
    """Async dependency to yield a database session."""
    async with AsyncSession() as session:
        try:
            yield session
        finally:
            await session.close()


@router.post("/", response_model=PresignedURLResponse)
async def create_upload_job(db: AsyncSession = Depends(get_db)):
    job_id = str(uuid.uuid4())
    s3_key = f"uploads/{job_id}"
    
    s3 = boto3.client(
        "s3",
        endpoint_url=settings.S3_ENDPOINT_URL,
        aws_access_key_id=settings.S3_ACCESS_KEY,
        aws_secret_access_key=settings.S3_SECRET_KEY,
        config=Config(signature_version="s3v4"),
    )
    
    try:
        presigned = s3.generate_presigned_post(
            Bucket=settings.S3_BUCKET_NAME,
            Key=s3_key,
            ExpiresIn=900,
        )
        
        db_job = Job(id=job_id, s3_key=s3_key, status="pending")
        db.add(db_job)
        await db.commit()
        
        logger.info("upload_job_created", job_id=job_id, s3_key=s3_key)
        return PresignedURLResponse(
            job_id=job_id, upload_url=presigned["url"], fields=presigned["fields"]
        )
    except Exception as e:
        logger.error("presigned_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to generate upload URL")


@router.get("/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobStatusResponse(job_id=job.id, status=job.status, result=job.result)