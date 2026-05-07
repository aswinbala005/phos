from pydantic import BaseModel
from typing import Dict, Any

class PresignedURLResponse(BaseModel):
    job_id: str
    upload_url: str
    fields: Dict[str, str]

class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    result: Dict[str, Any] | None = None