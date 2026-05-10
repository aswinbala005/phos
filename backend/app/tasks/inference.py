import os
import gc
import tempfile
import structlog
import torch
import numpy as np
import cv2
from PIL import Image
import torchvision.transforms as transforms
import boto3
from botocore.config import Config
from app.celery_app import celery_app
from app.config import settings
from app.ml.models.spatial import load_real_model

# Force CPU single-threading
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
torch.set_num_threads(1)

logger = structlog.get_logger()

# Preprocessing for EfficientNet (ImageNet standards)
transform = transforms.Compose([
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
])

@celery_app.task(bind=True, max_retries=2, acks_late=True)
def run_inference(self, prev_result: dict) -> dict:
    job_id = prev_result["job_id"]
    std_key = prev_result["standardized_key"]
    media_type = prev_result.get("media_type", "video")
    
    try:
        logger.info("inference_start", job_id=job_id, type=media_type)
        
        s3 = boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT_URL,
            aws_access_key_id=settings.S3_ACCESS_KEY,
            aws_secret_access_key=settings.S3_SECRET_KEY,
            config=Config(signature_version="s3v4"),
        )
        
        # Determine suffix for temp file
        suffix = ".mp4" if media_type == "video" else ".jpg"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            s3.download_fileobj(settings.S3_BUCKET_NAME, std_key, tmp)
            media_path = tmp.name
        
        # Load Real Model
        model = load_real_model()
        model.eval()
        scores = []
        
        if media_type == "image":
            # Process Single Image
            try:
                img = Image.open(media_path).convert("RGB").resize((224, 224))
                tensor = transform(img).unsqueeze(0)
                with torch.no_grad():
                    output = model(tensor)
                    prob = torch.softmax(output, dim=1)[0, 1].item() # Prob of Fake
                    scores.append(prob)
            except Exception as e:
                logger.error("image_processing_failed", error=str(e))
                raise e
                
        else: 
            # Process Video Frames
            cap = cv2.VideoCapture(media_path)
            fps = cap.get(cv2.CAP_PROP_FPS)
            interval = max(1, int(fps)) if fps > 0 else 1
            count = 0
            frames_processed = 0
            
            while cap.isOpened() and frames_processed < 10:
                ret, frame = cap.read()
                if not ret: break
                
                if count % interval == 0:
                    try:
                        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        img = Image.fromarray(frame_rgb).resize((224, 224))
                        tensor = transform(img).unsqueeze(0)
                        with torch.no_grad():
                            output = model(tensor)
                            prob = torch.softmax(output, dim=1)[0, 1].item()
                            scores.append(prob)
                        frames_processed += 1
                    except Exception as e:
                        logger.warning("frame_skip", error=str(e))
                
                count += 1
            cap.release()

        if not scores:
            raise ValueError("No frames/images processed successfully")
            
        avg_score = float(np.mean(scores))
        
        # Thresholds for Real vs Fake
        # Note: Since we are using ImageNet weights, these are heuristic. 
        # Fine-tuning would adjust these thresholds.
        verdict = "LIKELY_FAKE" if avg_score > 0.7 else "LIKELY_REAL" if avg_score < 0.3 else "UNCERTAIN"
        
        logger.info("inference_done", job_id=job_id, verdict=verdict, score=avg_score)
        
        # Cleanup
        del model
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        os.unlink(media_path)
        
        return {
            "job_id": job_id,
            "verdict": verdict,
            "confidence": avg_score,
            "heatmap_url": None # Heatmaps disabled for Phase 3.5 to ensure stability
        }
        
    except Exception as e:
        logger.error("inference_failed", job_id=job_id, error=str(e))
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        if "media_path" in locals() and os.path.exists(media_path):
            os.unlink(media_path)
        raise self.retry(exc=e, countdown=60)