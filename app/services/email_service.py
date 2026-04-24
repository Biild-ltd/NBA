"""Email service — async SMTP via aiosmtplib.

Supports password reset emails. Errors are logged but never surfaced to the
caller (we always return success to prevent email enumeration).
"""
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib

from app.config import settings

logger = logging.getLogger(__name__)


async def send_password_reset(to_email: str, reset_link: str) -> None:
    """Send a password-reset email with a one-hour expiry link."""
    plain = (
        "You requested a password reset for your NBA ID Portal account.\n\n"
        f"Click the link below to set a new password (valid for 1 hour):\n{reset_link}\n\n"
        "If you did not request this, you can safely ignore this email.\n\n"
        "— Nigerian Bar Association ID Portal"
    )
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:520px;margin:0 auto;padding:32px 24px">
      <div style="background:#1A5C2A;padding:16px 24px;border-radius:8px 8px 0 0">
        <h2 style="color:#fff;margin:0;font-size:18px">NBA ID Portal — Password Reset</h2>
      </div>
      <div style="background:#fff;border:1px solid #e5e7eb;border-top:none;
                  padding:28px 24px;border-radius:0 0 8px 8px">
        <p style="color:#374151;margin-top:0">
          You requested a password reset for your NBA ID Portal account.
        </p>
        <p style="color:#374151">
          Click the button below to set a new password. This link expires in
          <strong>1 hour</strong> and can only be used once.
        </p>
        <div style="text-align:center;margin:28px 0">
          <a href="{reset_link}"
             style="background:#1A5C2A;color:#fff;text-decoration:none;
                    padding:12px 28px;border-radius:6px;font-weight:600;
                    display:inline-block">
            Reset my password
          </a>
        </div>
        <p style="color:#6b7280;font-size:13px">
          If the button does not work, copy and paste this link into your browser:<br/>
          <a href="{reset_link}" style="color:#1A5C2A;word-break:break-all">{reset_link}</a>
        </p>
        <hr style="border:none;border-top:1px solid #e5e7eb;margin:24px 0"/>
        <p style="color:#9ca3af;font-size:12px;margin:0">
          If you did not request a password reset, you can safely ignore this email.
          Your password will not change.
        </p>
      </div>
    </div>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "NBA ID Portal — Password Reset"
    msg["From"] = settings.SMTP_FROM
    msg["To"] = to_email
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html, "html"))

    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            username=settings.SMTP_USER,
            password=settings.SMTP_PASSWORD,
            start_tls=True,
        )
        logger.info("Password reset email sent to %s", to_email)
    except Exception as exc:
        logger.error("Failed to send password reset email to %s: %s", to_email, exc)
