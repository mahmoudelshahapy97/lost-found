# app/services/mail_service.py
"""Outgoing email over SMTP, for password reset codes and notifications.

Off while SMTP_HOST is empty: ``config.mail_enabled`` is the switch every
sender checks first. smtplib blocks, so sending runs in a worker thread, and a
batch goes out over one connection.
"""

import asyncio
import logging
import smtplib
from email.message import EmailMessage
from email.utils import make_msgid
from typing import Iterable, List, Optional, Tuple

from app.core.config import config

logger = logging.getLogger(__name__)


def build(
    to: str,
    subject: str,
    text: str,
    html: str,
    image: Optional[bytes] = None,
    image_name: str = "image.jpg",
) -> EmailMessage:
    """A text + HTML message. With ``image``, the HTML may show it as
    ``<img src="cid:image">``; it is embedded, so it shows without remote images."""
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config.smtp_from
    message["To"] = to
    message.set_content(text)
    if image:
        cid = make_msgid(domain="lostfound.local")
        message.add_alternative(html.replace("cid:image", f"cid:{cid[1:-1]}"), subtype="html")
        message.get_payload()[1].add_related(
            image, maintype="image", subtype="jpeg", cid=cid,
            disposition="inline", filename=image_name,
        )
    else:
        message.add_alternative(html, subtype="html")
    return message


def _send_blocking(messages: List[EmailMessage]) -> Tuple[int, List[str]]:
    smtp_cls = smtplib.SMTP_SSL if config.smtp_ssl else smtplib.SMTP
    sent, failed = 0, []
    with smtp_cls(config.smtp_host, config.smtp_port, timeout=config.smtp_timeout_seconds) as smtp:
        if config.smtp_starttls and not config.smtp_ssl:
            smtp.starttls()
        if config.smtp_username:
            smtp.login(config.smtp_username, config.smtp_password)
        for message in messages:
            # One refused recipient must not stop the rest of the batch.
            try:
                smtp.send_message(message)
                sent += 1
            except smtplib.SMTPException as e:
                logger.warning("SMTP refused mail to %s: %s", message["To"], e)
                failed.append(message["To"])
    return sent, failed


async def send(messages: Iterable[EmailMessage]) -> int:
    """Send the messages; returns how many the server accepted. Raises when the
    server cannot be reached at all, so callers decide what a failure means."""
    batch = list(messages)
    if not batch:
        return 0
    sent, _ = await asyncio.to_thread(_send_blocking, batch)
    return sent
