# backend/app/tasks/inference.py
import os
import gc
import tempfile
import structlog
import requests
import time
import cv2
import boto3
from PIL import Image
from botocore.config import Config
from dotenv import load_dotenv
from app.celery_app import celery_app
from app.config import settings

# Load .env explicitly for any local testing
load_dotenv()

logger = structlog.get_logger()

# =============================================================================
# HUGGING FACE FREE API INTEGRATION
# =============================================================================
MODEL_NAME = "prithivMLmods/Deep-Fake-Detector-v2-Model"
HF_API_URL = f"https://router.huggingface.co/hf-inference/models/{MODEL_NAME}"

HEADERS = {
    "Authorization": f"Bearer {settings.HF_API_TOKEN}",
    "Content-Type": "image/jpeg",
}

@celery_app.task(bind=True, max_retries=2, acks_late=True)
def run_inference(self, prev_result: dict) -> dict:
    job_id = prev_result["job_id"]
    std_key = prev_result["standardized_key"]
    media_type = prev_result.get("media_type", "video")
    
    try:
        logger.info("inference_start", job_id=job_id, type=media_type, method="hf_requests")
        
        s3 = boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT_URL,
            aws_access_key_id=settings.S3_ACCESS_KEY,
            aws_secret_access_key=settings.S3_SECRET_KEY,
            config=Config(signature_version="s3v4"),
        )
        
        suffix = ".mp4" if media_type == "video" else ".jpg"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            s3.download_fileobj(settings.S3_BUCKET_NAME, std_key, tmp)
            media_path = tmp.name
        
        scores = []
        
        if media_type == "image":
            score = _run_model_on_image(media_path)
            scores.append(score)
                
        else: 
            cap = cv2.VideoCapture(media_path)
            if not cap.isOpened():
                raise ValueError(f"Could not open video: {media_path}")
                
            fps = cap.get(cv2.CAP_PROP_FPS)
            interval = max(1, int(fps)) if fps > 0 else 30
            count = 0
            frames_processed = 0
            
            # Limit to 3 frames to keep API usage light
            while cap.isOpened() and frames_processed < 3:
                ret, frame = cap.read()
                if not ret:
                    break
                    
                if count % interval == 0:
                    try:
                        # Convert to RGB and temporarily save as JPEG
                        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        img = Image.fromarray(frame_rgb)
                        
                        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as f_tmp:
                            img.save(f_tmp, format="JPEG", quality=85)
                            frame_path = f_tmp.name
                            
                        score = _run_model_on_image(frame_path)
                        scores.append(score)
                        os.unlink(frame_path)
                        frames_processed += 1
                    except Exception as e:
                        logger.warning("frame_skip", error=str(e))
                
                count += 1
            cap.release()

        if not scores:
            raise ValueError("No frames processed")
            
        avg_score = sum(scores) / len(scores)
        
        if avg_score > 0.50:
            verdict = "FAKE"
            confidence = avg_score
            message = "Deepfake detected."
        else:
            verdict = "REAL"
            confidence = 1 - avg_score
            message = "No significant manipulation detected."
        
        logger.info("inference_done", job_id=job_id, verdict=verdict, confidence=round(confidence, 4))
        
        gc.collect()
        os.unlink(media_path)
        
        return {
            "job_id": job_id,
            "verdict": verdict,
            "confidence": round(confidence, 4),
            "message": message,
            "raw_scores": {"fake": round(avg_score, 4), "real": round(1 - avg_score, 4)},
            "model": MODEL_NAME,
            "heatmap_url": None,
        }
        
    except Exception as e:
        logger.error("inference_failed", job_id=job_id, error=str(e))
        gc.collect()
        if "media_path" in locals() and os.path.exists(media_path):
            os.unlink(media_path)
        raise self.retry(exc=e, countdown=60)


def _run_model_on_image(image_path: str) -> float:
    """Run model on a single image using Hugging Face Free API."""
    if not settings.HF_API_TOKEN:
        logger.warning("hf_api_token_missing", message="Falling back to 0.5 (UNCERTAIN) score.")
        return 0.5

    with open(image_path, "rb") as f:
        data = f.read()

    max_retries = 3
    for attempt in range(max_retries):
        try:
            logger.info("querying_hf_api", attempt=attempt+1)
            response = requests.post(HF_API_URL, headers=HEADERS, data=data, timeout=30)
            
            try:
                result = response.json()
            except ValueError:
                response.raise_for_status()
                return 0.5
            
            # Handle "loading" state
            if isinstance(result, dict) and "error" in result:
                if "currently loading" in result.get("error", "").lower():
                    wait_time = result.get("estimated_time", 15.0)
                    logger.info("model_loading_wait", seconds=wait_time)
                    time.sleep(max(wait_time, 5))
                    continue
                else:
                    logger.error("hf_api_error", error=result.get("error"))
                    return 0.5
                
            response.raise_for_status()
                
            # Parse classification output
            # Expected format: [{'label': 'Fake', 'score': 0.98}, {'label': 'Real', 'score': 0.02}]
            if isinstance(result, list) and len(result) > 0:
                for item in result:
                    if "fake" in item.get("label", "").lower():
                        return float(item["score"])
                return 1.0 - float(result[0]["score"])
                
            logger.error("unexpected_api_response", result=result)
            return 0.5

        except requests.exceptions.RequestException as e:
            logger.error("hf_api_request_failed", error=str(e))
            time.sleep(5)

    logger.error("hf_api_max_retries_exceeded")
    return 0.5