from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
    
    # Database
    DATABASE_URL: str
    DATABASE_URL_SYNC: str
    
    # Redis
    REDIS_URL: str
    
    # MinIO - Internal (backend uses this to talk to MinIO)
    S3_ENDPOINT_URL: str
    S3_ACCESS_KEY: str
    S3_SECRET_KEY: str
    S3_BUCKET_NAME: str
    
    # MinIO - External (mobile app uses this for presigned URL uploads)
    # Defaults to S3_ENDPOINT_URL if not set (for backward compatibility)
    MINIO_EXTERNAL_URL: str = ""
    
    # App
    SECRET_KEY: str
    SENTRY_DSN: str = ""
    RATE_LIMIT: str = "10/hour"
    
    # Hugging Face Free API
    HF_API_TOKEN: str = ""
    
    @property
    def MINIO_PUBLIC_URL(self) -> str:
        """
        Returns the URL that external clients (mobile app) should use to upload to MinIO.
        Falls back to S3_ENDPOINT_URL if MINIO_EXTERNAL_URL is not set.
        """
        return self.MINIO_EXTERNAL_URL if self.MINIO_EXTERNAL_URL else self.S3_ENDPOINT_URL

settings = Settings()