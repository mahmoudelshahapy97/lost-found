# app/core/config.py
"""Central application configuration loaded from environment variables and .env."""

from typing import List, Literal

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()


class Settings(BaseSettings):
    """
    Central application configuration.
    Loaded from:
    - Environment variables
    - .env
    - Defaults below
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # =========================================================================
    # APPLICATION
    # =========================================================================
    app_name: str = "Lost & Found API"
    app_description: str = "Abandoned object detection and lost/found item matching"
    app_version: str = "1.0.0"
    app_api_prefix: str = "/api/v1"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_debug: bool = True
    environment: Literal["development", "staging", "production"] = "development"

    # =========================================================================
    # CORS
    # =========================================================================
    cors_origins: List[str] = ["http://localhost:3000", "http://localhost:8000"]
    cors_allow_credentials: bool = True
    cors_allow_methods: List[str] = ["GET", "POST", "PUT", "PATCH", "DELETE"]
    cors_allow_headers: List[str] = ["Content-Type", "Authorization", "X-Request-ID"]

    # =========================================================================
    # AUTH
    # =========================================================================
    # No default: pydantic-settings refuses to build Settings without this set,
    # which is the right failure mode for a signing key. Generate one with:
    #   python -c "import secrets; print(secrets.token_urlsafe(48))"
    secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # Sent alongside the bearer token so <img src="..."> endpoints (camera
    # snapshots, event frames, found-item crops) can authenticate without a
    # header. Never accepted on a route that changes state -- see
    # app/api/deps.py.
    auth_cookie_name: str = "lf_access"
    auth_cookie_secure: bool = False
    auth_cookie_samesite: str = "lax"

    # There is no public signup. If app_user is empty at startup, one admin is
    # created from these three values -- see ensure_bootstrap_admin() in
    # app/services/user_service.py. Change the password immediately after.
    bootstrap_admin_username: str = "admin"
    bootstrap_admin_email: str = "admin@insighteye.local"
    bootstrap_admin_password: str = "ChangeMe!123"

    # =========================================================================
    # LOGGING
    # =========================================================================
    log_level: str = "INFO"
    log_format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    log_file_path: str = "logs/lostfound.log"

    # =========================================================================
    # DATABASE
    # =========================================================================
    postgres_db: str = "lostfound_db"
    postgres_user: str = "lostfound"
    postgres_password: str = "lostfound_pass"
    db_host: str = "db"
    db_port: int = 5432

    db_min_pool_size: int = 2
    db_max_pool_size: int = 10
    db_timeout: float = 30.0
    db_command_timeout: float = 60.0
    db_max_retries: int = 10
    db_retry_delay_base: int = 2
    db_retry_delay_max: int = 30

    @property
    def database_dsn(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.db_host}:{self.db_port}/{self.postgres_db}"
        )

    # =========================================================================
    # MODELS
    # =========================================================================
    model_cache_dir: str = "models"
    model_device: str = "cpu"

    yolo_model_path: str = "models/yolo11n.pt"
    yolo_confidence: float = 0.35
    yolo_input_size: int = 640
    yolo_tracker: str = "bytetrack.yaml"

    # COCO class ids
    person_class_id: int = 0
    object_class_ids: List[int] = [24, 26, 28]  # backpack, handbag, suitcase

    clip_model_name: str = "ViT-B-32"
    clip_pretrained: str = "laion2b_s34b_b79k"
    embedding_dim: int = 512

    @property
    def tracked_class_ids(self) -> List[int]:
        """Every class the tracker must follow: the objects plus their potential owners."""
        return sorted({self.person_class_id, *self.object_class_ids})

    # =========================================================================
    # RTSP / STREAM
    # =========================================================================
    rtsp_transport: str = "tcp"
    rtsp_buffer_size: int = 1
    rtsp_open_timeout: float = 15.0
    rtsp_read_failure_limit: int = 30
    rtsp_reconnect_delay_base: float = 2.0
    rtsp_reconnect_delay_max: float = 30.0

    frame_skip: int = 5
    target_process_fps: float = 5.0
    jpeg_quality: int = 85

    stream_start_stagger_delay: float = 2.0
    stream_worker_restart_delay: float = 5.0

    # =========================================================================
    # ABANDONMENT STATE MACHINE
    # =========================================================================
    static_tolerance_px: float = 25.0
    static_window_seconds: float = 3.0
    owner_distance_px: float = 180.0
    abandon_distance_px: float = 260.0
    abandon_seconds: float = 30.0
    track_max_misses: int = 30
    event_cooldown_seconds: float = 300.0

    # =========================================================================
    # MATCHING
    # =========================================================================
    match_top_k: int = 10
    match_min_similarity: float = 0.55
    match_same_class_bonus: float = 0.05
    match_same_color_bonus: float = 0.03
    match_text_weight: float = 0.25
    max_upload_bytes: int = 10 * 1024 * 1024


config = Settings()
