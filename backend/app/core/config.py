# app/core/config.py
"""Central application configuration loaded from environment variables and .env."""

from typing import Dict, List, Literal

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
    cors_allow_headers: List[str] = ["Content-Type", "Authorization", "X-Request-ID", "X-Workspace-Id"]

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

    # "Forgot your password?": a one-time code mailed to the account's email
    # (app/services/otp_service.py). Off while SMTP_HOST is empty.
    otp_ttl_seconds: int = 600
    otp_resend_seconds: int = 60
    otp_max_attempts: int = 5

    # =========================================================================
    # EMAIL (SMTP)
    # =========================================================================
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = "Lost & Found <no-reply@insighteye.local>"
    smtp_starttls: bool = True   # STARTTLS on smtp_port (587)
    smtp_ssl: bool = False       # implicit TLS instead (465)
    smtp_timeout_seconds: float = 20.0

    @property
    def mail_enabled(self) -> bool:
        return bool(self.smtp_host)

    @property
    def password_reset_enabled(self) -> bool:
        return self.mail_enabled

    # =========================================================================
    # NOTIFICATIONS (app/services/notification_service.py; need SMTP_HOST)
    # =========================================================================
    # New alerts are mailed to every active account at or above this role that
    # can see the camera's workspace and has not turned alert emails off.
    alert_emails_enabled: bool = True
    alert_email_min_role: str = "operator"
    # At most one alert email per camera in this window; alerts inside it are
    # counted and mentioned in the next email.
    alert_email_cooldown_seconds: float = 300.0
    # The reporter of a lost item is mailed once its match is confirmed.
    reporter_emails_enabled: bool = True
    reporter_pickup_note: str = (
        "Please bring photo ID to the lost property desk to collect it."
    )
    # The console's address as people open it, for links in emails
    # (e.g. https://lostfound.example.com). Left empty, emails carry no links.
    console_url: str = ""

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

    # database/migrations, mounted read-only by docker-compose.yml. When this
    # path is missing (a checkout run outside Docker) the repo's own folder is
    # used -- see app/core/migrations.py.
    migrations_dir: str = "/app/migrations"

    @property
    def database_dsn(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.db_host}:{self.db_port}/{self.postgres_db}"
        )

    # =========================================================================
    # MODELS
    # =========================================================================
    model_device: str = "cpu"

    yolo_model_path: str = "models/yolo26l.pt"
    yolo_confidence: float = 0.05  # low on purpose: the tracker yaml decides what starts a track
    yolo_input_size: int = 640
    # Tuned ByteTrack: starts tracks on weak detections and keeps a lost track
    # for 30 s at 5 fps, so a small, still object holds one id (see the file).
    yolo_tracker: str = "trackers/lostfound_bytetrack.yaml"
    # One box per object: COCO scores a bag as backpack, handbag and suitcase at
    # once, and without class-agnostic NMS each becomes its own track and alert.
    yolo_agnostic_nms: bool = True
    # FP16 inference on CUDA (~25% faster on a T4); ignored on CPU.
    yolo_half: bool = True
    # Object detections ByteTrack leaves unconfirmed are followed by box overlap
    # (see tracking_service); this IoU links them frame to frame.
    loose_track_iou: float = 0.5
    # ...and keeps their id across at most this many frames without a sighting.
    loose_track_max_gap_frames: int = 10

    # COCO class ids: 24 backpack, 25 umbrella, 26 handbag, 28 suitcase, 67 cell phone
    person_class_id: int = 0
    object_class_ids: List[int] = [24, 25, 26, 28, 67]
    # Detector label -> the name stored and shown in the app. Folding the three
    # COCO bag classes into one stops a single bag flipping type between frames.
    class_name_map: Dict[str, str] = {
        "backpack": "bag",
        "handbag": "bag",
        "suitcase": "bag",
        "cell phone": "mobile_phone",
    }

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

    # Every live viewer costs one JPEG encode per frame; cap them so a wall of
    # open browser tabs cannot starve detection.
    max_mjpeg_clients: int = 4

    # =========================================================================
    # WORKER SUPERVISION
    # =========================================================================
    # Restarts workers that died, errored, or wedged inside a blocking read,
    # and starts enabled cameras that have no worker. Without it a camera whose
    # model load failed stays dark until someone notices by hand.
    worker_supervision_enabled: bool = True
    worker_supervision_interval_s: float = 15.0
    worker_restart_backoff_base_s: float = 5.0
    worker_restart_backoff_max_s: float = 300.0

    # =========================================================================
    # EVIDENCE CLIPS
    # =========================================================================
    # One annotated mp4 per abandoned event: clip_pre_seconds before the moment
    # the object is declared abandoned and clip_post_seconds after. The drop
    # itself happens about abandon_seconds before the event, so the pre-roll has
    # to be longer than that to show who left the item.
    clip_enabled: bool = True
    clip_dir: str = "data/clips"
    clip_pre_seconds: float = 40.0
    clip_post_seconds: float = 10.0
    clip_max_width: int = 960
    clip_jpeg_quality: int = 70

    # =========================================================================
    # OBJECT STORAGE (MinIO)
    # =========================================================================
    # Images and videos go to MinIO; Postgres keeps the records and object keys.
    # Empty endpoint = disabled: media stays in Postgres bytes / clip files.
    minio_endpoint: str = ""
    minio_access_key: str = ""
    minio_secret_key: str = ""
    minio_bucket: str = "lostfound"
    minio_secure: bool = False

    # =========================================================================
    # RETENTION
    # =========================================================================
    retention_enabled: bool = True
    retention_interval_s: float = 21600.0  # 6 hours
    clip_retention_days: int = 30
    clip_max_total_mb: int = 5120

    # =========================================================================
    # ABANDONMENT STATE MACHINE
    # =========================================================================
    static_tolerance_px: float = 25.0
    # ...or this fraction of the object's height, whichever is larger: a bag near
    # the camera jitters by more pixels than one far away.
    static_tolerance_ratio: float = 0.5
    static_window_seconds: float = 3.0
    owner_distance_px: float = 180.0
    abandon_distance_px: float = 260.0
    # Radii in heights of the person concerned (0 = use the pixel values above).
    # A person's height is the local scale, so the radius shrinks with distance
    # from the camera the way floor distances do. Sensors 2025 sets the owner
    # radius at about one person height; PETS 2006 abandons at 1.5x that (3 m
    # vs 2 m).
    owner_radius_heights: float = 1.0
    abandon_radius_heights: float = 1.5
    # An item nobody was ever seen with never alarms (PETS 2006): it filters the
    # bins and chairs a COCO model mistakes for bags.
    require_owner: bool = True
    # Ignore objects whose shorter side is below this - too far away to judge.
    min_object_size_px: float = 10.0
    # Once the owner is gone, a stranger counts as minding the object only after
    # staying within the owner radius this long - walking past does not.
    stand_in_seconds: float = 3.0
    abandon_seconds: float = 30.0
    track_max_misses: int = 30
    # A new track id overlapping a just-dropped object by this IoU is that object
    # again (the tracker re-ids blinking detections); it inherits the timers.
    reid_iou: float = 0.5
    event_cooldown_seconds: float = 300.0

    # =========================================================================
    # MATCHING
    # =========================================================================
    # Lost reports are matched by rules, no models: a weighted sum of the
    # same object type, a compatible colour, and how soon after the loss the
    # item was found. The weights sum to 1, so a score reads as a percentage.
    match_top_k: int = 10
    match_class_weight: float = 0.5
    match_color_weight: float = 0.3
    match_time_weight: float = 0.2
    # When the report has a photo: weight of its likeness to the found crop
    # (perceptual hash + colour histogram, see utils/visual_similarity). The
    # score is renormalised over the parts available.
    match_visual_weight: float = 0.3
    # Share of the hash in that likeness; the colour histogram carries the rest,
    # being the sturdier of the two between a phone photo and a CCTV crop.
    match_hash_share: float = 0.3
    # Fraction of the reporter's photo kept (centred) - drops background edges.
    match_photo_keep: float = 0.8
    # A sighting this many hours after the reported loss earns no time credit.
    match_window_hours: float = 72.0
    # Suggestions scoring below this are not shown.
    match_min_score: float = 0.3
    # Same camera + boxes overlapping this much = one object re-detected.
    match_dedupe_iou: float = 0.6
    # Context around the box when cropping, as a fraction of its longer side.
    crop_context_ratio: float = 0.15
    max_upload_bytes: int = 10 * 1024 * 1024


config = Settings()
