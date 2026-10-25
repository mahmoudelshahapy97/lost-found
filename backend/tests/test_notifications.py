"""Email notifications: new alerts to the staff of a workspace, and a confirmed
match to the reporter. Also the account's own alert-email switch.

Needs a live Postgres, like test_otp.py; skipped when unreachable. Mail never
leaves the process: smtplib.SMTP is replaced by a fake that keeps what would
have been sent.
"""

import json
import smtplib
import uuid

import pytest

from app.core.config import config
from app.core.database import close_db_pool, db_manager, init_db_pool, wait_for_schema
from app.core.migrations import run_migrations
from app.core.security import create_access_token
from app.services import mail_service
from app.services.notification_service import NotificationService
from app.services.user_service import user_service
from app.services.workspace_service import workspace_service

PASSWORD = "Valid1Password!"
JPEG = b"\xff\xd8\xff\xe0fake-jpeg"


@pytest.fixture(scope="module")
async def database():
    try:
        await init_db_pool()
    except Exception as e:
        pytest.skip(f"No database reachable ({config.db_host}:{config.db_port}): {e}")
    if not await wait_for_schema(timeout=5):
        await close_db_pool()
        pytest.skip("Database reachable but database/schema.sql has not been applied.")
    await run_migrations()
    yield
    await close_db_pool()


class FakeSMTP:
    sent = []
    refuse = set()

    def __init__(self, host, port, timeout=None):
        self.host = host

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        pass

    def login(self, username, password):
        pass

    def send_message(self, message):
        if message["To"] in FakeSMTP.refuse:
            raise smtplib.SMTPRecipientsRefused({message["To"]: (550, b"no such user")})
        FakeSMTP.sent.append(message)


@pytest.fixture
def mailer(monkeypatch):
    FakeSMTP.sent = []
    FakeSMTP.refuse = set()
    monkeypatch.setattr("smtplib.SMTP", FakeSMTP)
    monkeypatch.setattr(config, "smtp_host", "smtp.test")
    monkeypatch.setattr(config, "console_url", "https://console.test")
    return FakeSMTP


def _bearer(user) -> dict:
    token = create_access_token(user["user_id"], user["role"], user["token_version"])
    return {"Authorization": f"Bearer {token}"}


def _recipients(sent):
    return {m["To"] for m in sent}


@pytest.fixture
async def world(database):
    """A workspace with a camera and one alert, and accounts around it:
    an opted-in operator member, an opted-out operator member, a viewer member,
    an operator of another workspace, an inactive operator member, and an admin
    who is in no workspace."""
    suffix = uuid.uuid4().hex[:8]
    ws = await workspace_service.create(f"N-{suffix}", None, None)
    other = await workspace_service.create(f"O-{suffix}", None, None)

    async def account(name, role, workspace=None):
        user = await user_service.create_user(
            f"nt-{name}-{suffix}", f"nt-{name}-{suffix}@example.com", PASSWORD, role
        )
        if workspace:
            await workspace_service.add_member(workspace["workspace_id"], user["user_id"])
        return user

    users = {
        "operator": await account("op", "operator", ws),
        "muted": await account("muted", "operator", ws),
        "viewer": await account("viewer", "viewer", ws),
        "outsider": await account("outsider", "operator", other),
        "inactive": await account("inactive", "operator", ws),
        "admin": await account("admin", "admin"),
    }
    await user_service.set_alert_emails(users["muted"]["user_id"], False)
    await db_manager.execute_query(
        "UPDATE app_user SET is_active = FALSE WHERE user_id = $1", (users["inactive"]["user_id"],)
    )

    camera = await db_manager.execute_query(
        "INSERT INTO camera (name, rtsp_url, enabled, workspace_id, location) "
        "VALUES ($1, 'rtsp://x/n', FALSE, $2, 'Gate 4') RETURNING *",
        (f"cam-n-{suffix}", ws["workspace_id"]),
        fetch_one=True,
    )

    async def alert(track):
        row = await db_manager.execute_query(
            """
            INSERT INTO abandoned_event (camera_id, track_key, class_name, confidence, bbox,
                                         first_seen_at, abandoned_at, frame_jpeg)
            VALUES ($1, $2, 'bag', 0.83, $3::jsonb, NOW() - INTERVAL '1 minute', NOW(), $4)
            RETURNING event_id
            """,
            (camera["camera_id"], track, json.dumps({"x1": 0, "y1": 0, "x2": 9, "y2": 9}), JPEG),
            fetch_one=True,
        )
        return row["event_id"]

    yield {"ws": ws, "camera": camera, "users": users, "alert": alert, "suffix": suffix}
    for workspace in (ws, other):
        await db_manager.execute_query(
            "DELETE FROM workspace WHERE workspace_id = $1", (workspace["workspace_id"],)
        )
    for user in users.values():
        await db_manager.execute_query("DELETE FROM app_user WHERE user_id = $1", (user["user_id"],))


# ---------------------------------------------------------------- building
def test_build_embeds_the_image_in_the_html():
    message = mail_service.build(
        "a@example.com", "s", "text", '<p><img src="cid:image"></p>', image=JPEG
    )
    html_part = message.get_body(preferencelist=("html",))
    cid = html_part.get_content().split('src="cid:')[1].split('"')[0]
    images = [p for p in message.walk() if p.get_content_type() == "image/jpeg"]
    assert len(images) == 1
    assert images[0]["Content-ID"] == f"<{cid}>"
    assert images[0].get_content_disposition() == "inline"
    assert images[0].get_content() == JPEG


# ------------------------------------------------------------------ alerts
async def test_alert_goes_to_opted_in_staff_who_see_the_workspace(world, mailer):
    service = NotificationService()
    event_id = await world["alert"]("t-1")
    sent = await service.alert_raised(world["camera"]["camera_id"], event_id)

    users = world["users"]
    to = _recipients(mailer.sent)
    assert sent == len(mailer.sent)
    assert {users["operator"]["email"], users["admin"]["email"]} <= to
    for left_out in ("muted", "viewer", "outsider", "inactive"):
        assert users[left_out]["email"] not in to

    message = next(m for m in mailer.sent if m["To"] == users["operator"]["email"])
    assert world["camera"]["name"] in message["Subject"]
    text = message.get_body(preferencelist=("plain",)).get_content()
    assert "Gate 4" in text and "83%" in text
    assert f"https://console.test/events/{event_id}" in text
    assert any(p.get_content_type() == "image/jpeg" for p in message.walk())


async def test_alerts_inside_the_cooldown_are_counted_not_mailed(world, mailer, monkeypatch):
    service = NotificationService()
    camera_id = world["camera"]["camera_id"]
    assert await service.alert_raised(camera_id, await world["alert"]("c-1"))
    first = len(mailer.sent)

    assert await service.alert_raised(camera_id, await world["alert"]("c-2")) == 0
    assert await service.alert_raised(camera_id, await world["alert"]("c-3")) == 0
    assert len(mailer.sent) == first

    # The window has passed: the next alert is mailed and mentions the two held back.
    monkeypatch.setattr(config, "alert_email_cooldown_seconds", 0.0)
    assert await service.alert_raised(camera_id, await world["alert"]("c-4"))
    text = mailer.sent[-1].get_body(preferencelist=("plain",)).get_content()
    assert "2 more alerts on this camera" in text


async def test_no_alert_mail_without_smtp(world, mailer, monkeypatch):
    monkeypatch.setattr(config, "smtp_host", "")
    service = NotificationService()
    assert await service.alert_raised(world["camera"]["camera_id"], await world["alert"]("off-1")) == 0
    assert mailer.sent == []


async def test_one_refused_recipient_does_not_stop_the_rest(world, mailer):
    mailer.refuse = {world["users"]["admin"]["email"]}
    service = NotificationService()
    sent = await service.alert_raised(world["camera"]["camera_id"], await world["alert"]("r-1"))
    assert world["users"]["operator"]["email"] in _recipients(mailer.sent)
    assert sent == len(mailer.sent)


async def test_account_switches_its_own_alert_emails(world, api):
    user = world["users"]["operator"]
    response = await api.patch("/auth/me", json={"alert_emails": False}, headers=_bearer(user))
    assert response.status_code == 200, response.text
    assert response.json()["alert_emails"] is False
    me = await api.get("/auth/me", headers=_bearer(user))
    assert me.json()["alert_emails"] is False


async def test_options_say_whether_alert_emails_are_sent(api, mailer, monkeypatch):
    assert (await api.get("/auth/options")).json()["alert_emails"] is True
    monkeypatch.setattr(config, "smtp_host", "")
    assert (await api.get("/auth/options")).json()["alert_emails"] is False


# ---------------------------------------------------------- confirmed match
@pytest.fixture
async def report(world):
    found = await db_manager.execute_query(
        "INSERT INTO found_item (event_id, camera_id, class_name, dominant_color, crop_jpeg) "
        "VALUES ($1, $2, 'bag', 'black', $3) RETURNING found_id",
        (await world["alert"]("m-1"), world["camera"]["camera_id"], JPEG),
        fetch_one=True,
    )
    lost = await db_manager.execute_query(
        "INSERT INTO lost_item (reporter_name, reporter_email, description, class_name, workspace_id) "
        "VALUES ('Sam Reporter', $1, 'black bag with a red keyring', 'bag', $2) RETURNING lost_id",
        (f"reporter-{world['suffix']}@example.com", world["ws"]["workspace_id"]),
        fetch_one=True,
    )
    return {"lost_id": lost["lost_id"], "found_id": found["found_id"],
            "email": f"reporter-{world['suffix']}@example.com"}


async def _notified_at(lost_id):
    row = await db_manager.execute_query(
        "SELECT reporter_notified_at FROM lost_item WHERE lost_id = $1", (lost_id,), fetch_one=True
    )
    return row["reporter_notified_at"]


async def test_confirming_a_match_emails_the_reporter_once(world, report, mailer, api):
    response = await api.post(
        "/matches/confirm",
        json={"lost_id": str(report["lost_id"]), "found_id": str(report["found_id"]), "score": 0.9},
        headers={**_bearer(world["users"]["operator"]), "X-Workspace-Id": str(world["ws"]["workspace_id"])},
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["reporter_email_queued"] is True

    assert [m["To"] for m in mailer.sent] == [report["email"]]
    message = mailer.sent[0]
    assert "has been found" in message["Subject"]
    text = message.get_body(preferencelist=("plain",)).get_content()
    assert "Hello Sam Reporter" in text and "black bag with a red keyring" in text
    assert "Gate 4" in text and config.reporter_pickup_note in text
    assert any(p.get_content_type() == "image/jpeg" for p in message.walk())
    assert await _notified_at(report["lost_id"]) is not None

    # Confirming again does not mail them a second time.
    assert await NotificationService().match_confirmed(report["lost_id"], report["found_id"]) is False
    assert len(mailer.sent) == 1


async def test_a_failed_reporter_email_can_be_retried(report, mailer):
    mailer.refuse = {report["email"]}
    service = NotificationService()
    assert await service.match_confirmed(report["lost_id"], report["found_id"]) is False
    assert await _notified_at(report["lost_id"]) is None

    mailer.refuse = set()
    assert await service.match_confirmed(report["lost_id"], report["found_id"]) is True
    assert await _notified_at(report["lost_id"]) is not None


async def test_a_report_without_an_email_is_left_alone(world, report, mailer):
    await db_manager.execute_query(
        "UPDATE lost_item SET reporter_email = NULL WHERE lost_id = $1", (report["lost_id"],)
    )
    assert await NotificationService().match_confirmed(report["lost_id"], report["found_id"]) is False
    assert mailer.sent == []
