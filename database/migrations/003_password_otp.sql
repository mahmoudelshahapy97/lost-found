-- 003_password_otp.sql
-- "Forgot your password?" codes. At most one live code per account; only its
-- HMAC is stored. See backend/app/services/otp_service.py.

CREATE TABLE IF NOT EXISTS password_otp (
    user_id       UUID PRIMARY KEY REFERENCES app_user (user_id) ON DELETE CASCADE,
    otp_hash      TEXT NOT NULL,
    expires_at    TIMESTAMPTZ NOT NULL,
    attempts      INTEGER NOT NULL DEFAULT 0,
    last_sent_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
