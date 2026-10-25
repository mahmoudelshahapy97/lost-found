-- 005_notifications.sql
-- Email notifications, sent once SMTP_HOST is set. See
-- backend/app/services/notification_service.py.

-- Operators and admins are mailed new alerts unless they turn it off.
ALTER TABLE app_user ADD COLUMN IF NOT EXISTS alert_emails BOOLEAN NOT NULL DEFAULT TRUE;

-- When the reporter was told their item was found. Set once, so confirming the
-- same report again never mails them twice.
ALTER TABLE lost_item ADD COLUMN IF NOT EXISTS reporter_notified_at TIMESTAMPTZ;
