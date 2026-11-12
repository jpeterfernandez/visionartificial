import json
from typing import ClassVar, List, Union
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


MIN_YOLO_STREAM_INTERVAL_MS = 100
MAX_YOLO_STREAM_INTERVAL_MS = 1000


class Settings(BaseSettings):
    DEVELOPMENT_SECRET_KEY: ClassVar[str] = "cardinova-dev-secret-key-production-control-system-2026"
    EXAMPLE_SECRET_KEY: ClassVar[str] = "cardinova-production-super-secret-jwt-key-replace-in-production"
    DEVELOPMENT_DATABASE_URL: ClassVar[str] = "postgresql+psycopg://admin:admin@localhost:5432/cardinova_core_platform"

    PROJECT_NAME: str = "Cardinova Control de Producción y Visión Artificial"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    API_V1_STR: str = "/api/v1"

    # CORS
    BACKEND_CORS_ORIGINS: List[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
    ]

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, str) and v.startswith("["):
            return json.loads(v)
        return v

    # PostgreSQL Database
    DATABASE_URL: str = DEVELOPMENT_DATABASE_URL
    DB_ECHO: bool = False

    # Security
    SECRET_KEY: str = DEVELOPMENT_SECRET_KEY
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480

    # YOLO Inference
    YOLO_MODEL_PATH: str = "best.pt"
    YOLO_CONF_THRESHOLD: float = 0.60
    YOLO_IOU_THRESHOLD: float = 0.45
    YOLO_IMG_SIZE: int = 416
    YOLO_STREAM_IMG_SIZE: int = 224
    YOLO_DEVICE: str = "auto"
    YOLO_CPU_EXTRA_THREADS: int = 1
    YOLO_GPU_MEMORY_FRACTION: float = 0.85
    YOLO_STREAM_INTERVAL_MS: int = 200

    STAGE_MIN_TIME_BETWEEN_EVENTS_SECONDS: int = 30
    CAMERA_CAPTURE_INTERVAL_SECONDS: int = 10
    FINAL_PRODUCTION_STAGE: str = "ALMACEN"

    # Storage
    STORAGE_DIR: str = "storage"
    SAVE_INFERENCE_IMAGES: bool = False

    # Odoo ERP Integration
    ODOO_BASE_URL: str = "http://localhost:8069"
    ODOO_DATABASE: str = "cardinova_odoo"
    ODOO_USERNAME: str = "admin"
    ODOO_API_KEY: str = ""
    ODOO_ENCRYPTION_KEY: str = ""
    ODOO_TIMEOUT: int = 10
    ODOO_SYNC_INTERVAL_SECONDS: int = 30
    CAMERA_HEALTH_CHECK_INTERVAL_SECONDS: int = 30

    @model_validator(mode="after")
    def validate_production_secrets(self):
        if self.ENVIRONMENT.lower() != "development":
            if self.SECRET_KEY in {self.DEVELOPMENT_SECRET_KEY, self.EXAMPLE_SECRET_KEY} or len(self.SECRET_KEY) < 32:
                raise ValueError("SECRET_KEY debe ser único y tener al menos 32 caracteres fuera de desarrollo")
            if self.DATABASE_URL == self.DEVELOPMENT_DATABASE_URL:
                raise ValueError("DATABASE_URL de desarrollo no puede usarse fuera de desarrollo")
            if len(self.ODOO_ENCRYPTION_KEY) < 32:
                raise ValueError("ODOO_ENCRYPTION_KEY debe tener al menos 32 caracteres fuera de desarrollo")
        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"
    )


settings = Settings()
