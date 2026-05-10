import os
import subprocess
import tempfile
import structlog
import boto3
from botocore.config import Config
from app.celery_app import celery_app
from app.config import settings

logger = structlog.get_logger()


@celery_app.task(bind=True, max_retries=2, acks_late=True)
def standardize_media(self, job_id: str, s3_key: str, media_type: str) -> dict:
    """
    Standardize media based on type.
    media_type: 'video' or 'image'
    """
    try:
        logger.info("standardize_start", job_id=job_id, type=media_type)
        
        s3 = boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT_URL,
            aws_access_key_id=settings.S3_ACCESS_KEY,
            aws_secret_access_key=settings.S3_SECRET_KEY,
            config=Config(signature_version="s3v4"),
        )
        
        # Determine suffix based on type
        suffix = ".mp4" if media_type == "video" else ".jpg"
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_in:
            s3.download_fileobj(settings.S3_BUCKET_NAME, s3_key, tmp_in)
            input_path = tmp_in.name
        
        output_path = None
        std_key = None

        if media_type == "video":
            # Process Video: Convert to 720p h264/aac
            output_path = f"{input_path.replace(suffix, '')}_std.mp4"
            cmd = [
                "ffmpeg",
                "-y",
                "-i",
                input_path,
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "28",
                "-vf",
                "scale=720:-2",
                "-c:a",
                "aac",
                "-b:a",
                "64k",
                "-movflags",
                "+faststart",
                output_path,
            ]
            logger.info("ffmpeg_running", cmd=" ".join(cmd))
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            std_key = f"processed/{job_id}_std.mp4"
            
        elif media_type == "image":
            # Process Image: For Phase 3.5, we keep original but rename for consistency
            # In future phases, we can add Pillow resizing here for uniformity
            output_path = input_path 
            std_key = f"processed/{job_id}_std.jpg"
            
        else:
            raise ValueError(f"Unsupported media type: {media_type}")

        # Upload standardized file
        s3.upload_file(output_path, settings.S3_BUCKET_NAME, std_key)
        logger.info("standardize_done", job_id=job_id, output_key=std_key)
        
        # Cleanup
        os.unlink(input_path)
        if output_path and output_path != input_path:
            os.unlink(output_path)
            
        return {"job_id": job_id, "standardized_key": std_key, "media_type": media_type}
        
    except subprocess.CalledProcessError as e:
        logger.error("ffmpeg_failed", job_id=job_id, stderr=e.stderr)
        raise self.retry(exc=e, countdown=60)
    except Exception as e:
        logger.error("standardize_failed", job_id=job_id, error=str(e))
        raise self.retry(exc=e, countdown=60)