from fastapi import APIRouter, Depends, HTTPException
import boto3
import uuid
import structlog
from botocore.config import Config
from sqlalchemy import select
from pydantic import BaseModel
from celery import chain
from app.config import settings
from app.db.session import AsyncSession
from app.db.models import Job
from app.schemas.jobs import PresignedURLResponse, JobStatusResponse
from app.tasks.standardize import standardize_media
from app.tasks.inference import run_inference
from app.tasks.aggregate import save_result

router = APIRouter(prefix="/jobs", tags=["jobs"])
logger = structlog.get_logger()

# Schema to accept optional user_id from mobile/client
class CreateJobRequest(BaseModel):
    user_id: str | None = None

async def get_db():
    async with AsyncSession() as session:
        try:
            yield session
        finally:
            await session.close()

def get_media_type(s3_key: str) -> str:
    """Detect if the file is an image or video by checking S3 metadata."""
    try:
        s3 = boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT_URL,
            aws_access_key_id=settings.S3_ACCESS_KEY,
            aws_secret_access_key=settings.S3_SECRET_KEY,
            config=Config(signature_version="s3v4"),
        )
        response = s3.head_object(Bucket=settings.S3_BUCKET_NAME, Key=s3_key)
        content_type = response.get('ContentType', '')
        
        # If the mobile app correctly set the MIME type during upload
        if content_type.startswith('image/'):
            return "image"
        elif content_type.startswith('video/'):
            return "video"
    except Exception as e:
        logger.warning("s3_head_failed", error=str(e), s3_key=s3_key)

    # Fallback to a hardcoded guess or extension if provided
    lower_key = s3_key.lower()
    if any(lower_key.endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp']):
        return "image"
    
    return "video" # Default fallback

@router.post("/", response_model=PresignedURLResponse)
async def create_upload_job(
    request: CreateJobRequest = None, 
    db: AsyncSession = Depends(get_db)
):
    job_id = str(uuid.uuid4())
    user_id = request.user_id if request else None
    s3_key = f"uploads/{job_id}"

    # Create S3 client with INTERNAL endpoint for backend communication
    s3 = boto3.client(
        "s3",
        endpoint_url=settings.S3_ENDPOINT_URL,  # localhost for backend
        aws_access_key_id=settings.S3_ACCESS_KEY,
        aws_secret_access_key=settings.S3_SECRET_KEY,
        config=Config(signature_version="s3v4"),
    )

    try:
        # Generate presigned POST fields (signature, policy, etc.)
        presigned = s3.generate_presigned_post(
            Bucket=settings.S3_BUCKET_NAME,
            Key=s3_key,
            ExpiresIn=900,
        )

        # ✅ FIX: Manually construct upload_url using EXTERNAL endpoint for mobile app
        # presigned["url"] contains localhost, so we replace it with the public URL
        upload_url = f"{settings.MINIO_PUBLIC_URL}/{settings.S3_BUCKET_NAME}"

        # Save user_id if provided
        db.add(Job(id=job_id, user_id=user_id, s3_key=s3_key, status="pending"))
        await db.commit()

        logger.info("upload_job_created", job_id=job_id, user_id=user_id, s3_key=s3_key)
        return PresignedURLResponse(
            job_id=job_id,
            upload_url=upload_url,  # ✅ Now returns http://192.168.1.14:9000/phos-uploads
            fields=presigned["fields"],
        )
    except Exception as e:
        logger.error("presigned_failed", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to generate upload URL")


@router.post("/{job_id}/process")
async def trigger_processing(job_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()

    if not job or job.status != "pending":
        raise HTTPException(status_code=400, detail="Job not ready")

    # Detect media type to route correctly
    media_type = get_media_type(job.s3_key)
    job.status = "processing"
    await db.commit()

    # Update chain to use standardize_media and pass media_type
    task_chain = chain(
        standardize_media.s(job_id, job.s3_key, media_type),
        run_inference.s(),
        save_result.s(),
    )
    task_chain.apply_async()

    logger.info("processing_triggered", job_id=job_id, media_type=media_type)
    return {"job_id": job_id, "status": "processing"}


@router.get("/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return JobStatusResponse(
        job_id=job.id,
        status=job.status,
        result=job.result,
    )