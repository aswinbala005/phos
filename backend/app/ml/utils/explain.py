import os
import tempfile
import structlog
import cv2
import numpy as np
from app.config import settings

logger = structlog.get_logger()


def generate_heatmap(model, frame, job_id, s3_client):
    """Simplified Grad-CAM fallback for Phase 3."""
    try:
        # Create a synthetic attention map (replace with real Captum in Phase 3.1)
        heatmap = np.random.rand(224, 224).astype(np.float32)
        heatmap = (heatmap - heatmap.min()) / (heatmap.max() - heatmap.min())
        heatmap_uint8 = (heatmap * 255).astype(np.uint8)
        heatmap_color = cv2.applyColorMap(heatmap_uint8, cv2.COLORMAP_JET)
        overlay = cv2.addWeighted(frame, 0.6, heatmap_color, 0.4, 0)
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
            cv2.imwrite(tmp.name, overlay)
            key = f"heatmaps/{job_id}.jpg"
            s3_client.upload_file(tmp.name, settings.S3_BUCKET_NAME, key)
            os.unlink(tmp.name)
            
        url = s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.S3_BUCKET_NAME, "Key": key},
            ExpiresIn=3600
        )
        logger.info("heatmap_generated", job_id=job_id)
        return url
    except Exception as e:
        logger.error("heatmap_failed", error=str(e))
        return None