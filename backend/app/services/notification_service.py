# app/services/notification_service.py
"""Email notifications: a new alert to the staff watching that camera, and a
confirmed match to the person who reported the item lost.

Nothing here runs while SMTP_HOST is empty. Both senders are background work
(a worker task, a FastAPI background task), so a failure is logged and never
reaches the camera loop or the request that triggered it.

Alert emails are throttled per camera: one per ``alert_email_cooldown_seconds``,
and the alerts swallowed in between are counted in the next one. The throttle
is in memory, which is enough because the API runs as a single replica (see
docker-compose.yml) and a restart only means one extra email.
"""

import html
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.core.config import config
from app.core.database import db_manager
from app.services import mail_service, media_service

logger = logging.getLogger(__name__)

_ROLES = ["viewer", "operator", "admin"]


def _roles_from(minimum: str) -> List[str]:
    return _ROLES[_ROLES.index(minimum):] if minimum in _ROLES else ["operator", "admin"]


def _when(value: Optional[datetime]) -> str:
    if not value:
        return "unknown time"
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _label(class_name: Optional[str]) -> str:
    return (class_name or "item").replace("_", " ")


def _link(path: str) -> Optional[str]:
    return f"{config.console_url.rstrip('/')}{path}" if config.console_url else None


def _rows(pairs: List[tuple]) -> str:
    cells = "".join(
        f'<tr><td style="padding:2px 12px 2px 0;color:#667">{html.escape(k)}</td>'
        f"<td>{html.escape(v)}</td></tr>"
        for k, v in pairs
    )
    return f'<table style="border-collapse:collapse;font-size:14px">{cells}</table>'


class NotificationService:
    def __init__(self) -> None:
        self.db_manager = db_manager
        # camera_id -> monotonic time of its last alert email
        self._last_alert_mail: Dict[UUID, float] = {}
        # camera_id -> alerts since then that were not mailed
        self._suppressed: Dict[UUID, int] = {}

    # ------------------------------------------------------------- alerts
    def _take_alert_slot(self, camera_id: UUID) -> Optional[int]:
        """None inside the camera's cooldown (and the alert is counted), else
        the number of alerts held back since the last email."""
        now = time.monotonic()
        last = self._last_alert_mail.get(camera_id)
        if last is not None and now - last < config.alert_email_cooldown_seconds:
            self._suppressed[camera_id] = self._suppressed.get(camera_id, 0) + 1
            return None
        self._last_alert_mail[camera_id] = now
        return self._suppressed.pop(camera_id, 0)

    async def alert_recipients(self, workspace_id: UUID) -> List[Dict[str, Any]]:
        """Active accounts at or above the minimum role that see the workspace
        (members, plus admins, who see every workspace) and want alert emails."""
        return await self.db_manager.execute_query(
            """
            SELECT u.user_id, u.username, u.email, u.full_name, u.role
            FROM app_user u
            WHERE u.is_active AND u.alert_emails AND u.role = ANY($2::text[])
              AND (u.role = 'admin' OR EXISTS (
                    SELECT 1 FROM workspace_member m
                    WHERE m.user_id = u.user_id AND m.workspace_id = $1))
            ORDER BY u.created_at
            """,
            (workspace_id, _roles_from(config.alert_email_min_role)),
            fetch_all=True,
        ) or []

    async def alert_raised(self, camera_id: UUID, event_id: UUID) -> int:
        """Mail a new alert; returns how many emails went out."""
        if not (config.mail_enabled and config.alert_emails_enabled):
            return 0
        held_back = self._take_alert_slot(camera_id)
        if held_back is None:
            return 0
        try:
            event = await self.db_manager.execute_query(
                """
                SELECT e.event_id, e.class_name, e.confidence, e.abandoned_at,
                       c.camera_id, c.name AS camera_name, c.location,
                       c.workspace_id, w.name AS workspace_name
                FROM abandoned_event e
                JOIN camera c ON c.camera_id = e.camera_id
                LEFT JOIN workspace w ON w.workspace_id = c.workspace_id
                WHERE e.event_id = $1
                """,
                (event_id,),
                fetch_one=True,
            )
            if not event:
                return 0
            recipients = await self.alert_recipients(event["workspace_id"])
            if not recipients:
                logger.info("Alert %s: nobody to email.", event_id)
                return 0
            frame = await media_service.load_image(media_service.EVENT_FRAME, event_id)
            messages = [self._alert_message(user, event, held_back, frame) for user in recipients]
            sent = await mail_service.send(messages)
            logger.info("Alert %s emailed to %d of %d recipients", event_id, sent, len(messages))
            return sent
        except Exception as e:
            logger.error("Could not email alert %s: %s", event_id, e)
            return 0

    @staticmethod
    def _alert_message(user, event, held_back: int, frame: Optional[bytes]):
        thing = _label(event["class_name"])
        camera = event["camera_name"]
        name = user.get("full_name") or user["username"]
        details = [
            ("Camera", camera),
            ("Location", event["location"] or "—"),
            ("Workspace", event["workspace_name"] or "—"),
            ("Detected", _when(event["abandoned_at"])),
            ("Confidence", f"{round((event['confidence'] or 0) * 100)}%"),
        ]
        minutes = max(1, round(config.alert_email_cooldown_seconds / 60))
        more = (
            f"{held_back} more alert{'s' if held_back != 1 else ''} on this camera in the "
            f"last {minutes} minutes {'were' if held_back != 1 else 'was'} not emailed separately."
            if held_back
            else ""
        )
        link = _link(f"/events/{event['event_id']}")
        footer = (
            "You get these emails because you watch this workspace. "
            "Turn them off from your account menu in the console."
        )

        text = "\n".join(
            [f"Hello {name},", "", f"An abandoned {thing} was detected.", ""]
            + [f"{k}: {v}" for k, v in details]
            + ([""] + [more] if more else [])
            + ([""] + [f"Open the alert: {link}"] if link else [])
            + ["", footer]
        )
        body = (
            f"<p>Hello {html.escape(name)},</p>"
            f"<p><strong>An abandoned {html.escape(thing)} was detected.</strong></p>"
            + _rows(details)
            + (f"<p>{html.escape(more)}</p>" if more else "")
            + ('<p><img src="cid:image" alt="Alert frame" style="max-width:100%;border-radius:6px"></p>' if frame else "")
            + (f'<p><a href="{html.escape(link)}">Open the alert in the console</a></p>' if link else "")
            + f'<p style="color:#889;font-size:12px">{html.escape(footer)}</p>'
        )
        return mail_service.build(
            to=user["email"],
            subject=f"{config.app_name}: abandoned {thing} on {camera}",
            text=text,
            html=body,
            image=frame,
            image_name=f"alert-{event['event_id']}.jpg",
        )

    # ------------------------------------------------------ found items
    async def match_confirmed(self, lost_id: UUID, found_id: UUID) -> bool:
        """Tell the reporter their item was found. Once per report: the row is
        claimed before sending and released again if the mail does not go out."""
        if not (config.mail_enabled and config.reporter_emails_enabled):
            return False
        report = await self.db_manager.execute_query(
            """
            UPDATE lost_item SET reporter_notified_at = NOW()
            WHERE lost_id = $1 AND reporter_notified_at IS NULL
              AND COALESCE(reporter_email, '') <> ''
            RETURNING lost_id, reporter_name, reporter_email, description,
                      class_name, reported_at
            """,
            (lost_id,),
            fetch_one=True,
        )
        if not report:
            return False
        try:
            found = await self.db_manager.execute_query(
                """
                SELECT f.found_id, f.class_name, f.found_at,
                       c.name AS camera_name, c.location
                FROM found_item f
                LEFT JOIN camera c ON c.camera_id = f.camera_id
                WHERE f.found_id = $1
                """,
                (found_id,),
                fetch_one=True,
            )
            crop = await media_service.load_image(media_service.FOUND_CROP, found_id)
            sent = await mail_service.send([self._reporter_message(report, found, crop)])
        except Exception as e:
            logger.error("Could not email the reporter of lost item %s: %s", lost_id, e)
            sent = 0
        if not sent:
            await self.db_manager.execute_query(
                "UPDATE lost_item SET reporter_notified_at = NULL WHERE lost_id = $1", (lost_id,)
            )
            return False
        logger.info("Reporter of lost item %s emailed about found item %s", lost_id, found_id)
        return True

    @staticmethod
    def _reporter_message(report, found, crop: Optional[bytes]):
        found = found or {}
        thing = _label(found.get("class_name") or report["class_name"])
        name = report["reporter_name"] or "there"
        where = found.get("location") or found.get("camera_name")
        details = [
            ("Your report", report["description"] or thing.capitalize()),
            ("Reported", _when(report["reported_at"])),
            ("Found", _when(found.get("found_at")) + (f", {where}" if where else "")),
            ("Reference", str(report["lost_id"]).split("-")[0].upper()),
        ]
        text = "\n".join(
            [f"Hello {name},", "", f"Good news: the {thing} you reported lost has been found.", ""]
            + [f"{k}: {v}" for k, v in details]
            + ["", config.reporter_pickup_note, "Quote the reference above when you collect it."]
        )
        body = (
            f"<p>Hello {html.escape(name)},</p>"
            f"<p><strong>Good news: the {html.escape(thing)} you reported lost has been found.</strong></p>"
            + _rows(details)
            + ('<p><img src="cid:image" alt="The found item" style="max-width:320px;border-radius:6px"></p>' if crop else "")
            + f"<p>{html.escape(config.reporter_pickup_note)}<br>Quote the reference above when you collect it.</p>"
        )
        return mail_service.build(
            to=report["reporter_email"],
            subject=f"{config.app_name}: your lost {thing} has been found",
            text=text,
            html=body,
            image=crop,
            image_name="found-item.jpg",
        )


notification_service = NotificationService()
