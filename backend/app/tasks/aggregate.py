import asyncio
import structlog
from sqlalchemy import update
from app.celery_app import celery_app
from app.db.models import Job
from app.db.session import AsyncSession

logger = structlog.get_logger()


@celery_app.task(bind=True, acks_late=True)
def save_result(self, result: dict) -> dict:
    job_id = result["job_id"]
    try:
        logger.info("aggregate_start", job_id=job_id)
        
        verdict = result["verdict"]
        confidence = result["confidence"]
        
        # Generate Plain-Language Report Message for Mobile UI
        if verdict == "LIKELY_FAKE":
            message = "This media shows significant signs of manipulation. Please verify with the original source."
        elif verdict == "UNCERTAIN":
            message = "We couldn't determine authenticity with high confidence. Manual review is recommended."
        else:
            message = "This media appears authentic. No common manipulation patterns were detected."

        async def _update():
            async with AsyncSession() as db:
                stmt = (
                    update(Job)
                    .where(Job.id == job_id)
                    .values(
                        status="completed",
                        result={
                            "verdict": verdict,
                            "confidence": confidence,
                            "message": message,  # <-- NEW: Human-readable report
                            "heatmap_url": result.get("heatmap_url"),
                        },
                    )
                )
                await db.execute(stmt)
                await db.commit()

        asyncio.run(_update())
        logger.info("aggregate_done", job_id=job_id, verdict=verdict)
        return {"status": "completed"}

    except Exception as e:
        error_msg = str(e)
        logger.error("aggregate_failed", job_id=job_id, error=error_msg)

        # Mark as failed
        async def _fail(err_msg: str):
            async with AsyncSession() as db:
                await db.execute(
                    update(Job)
                    .where(Job.id == job_id)
                    .values(status="failed", result={"error": err_msg})
                )
                await db.commit()

        asyncio.run(_fail(error_msg))
        raise