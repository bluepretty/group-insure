"""Statement delivery by email (Stage 11).

Sends one policy's reconciliation statement (as a PDF attachment) to a single
recipient through the configured SMTP host. The sender never loops over many
policies: each call handles exactly one policy_id and one email, which keeps the
"confirm-to-send" contract honest — an underwriter clicks send on one policy,
and one email goes out.
"""
import smtplib
import ssl
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.audit import record_log
from app.services.statements import build_statement, render_statement_pdf


class EmailError(RuntimeError):
    """Sent failure other than a bad address (SMTP disabled, no destination,
    or the SMTP send itself failing)."""


def _build_email(
    *, to_email: str, subject: str, body: str, attachment_bytes: bytes,
    attachment_filename: str,
) -> MIMEMultipart:
    """Assemble a multipart email with one binary attachment."""
    message = MIMEMultipart()
    message["From"] = settings.email_from
    message["To"] = to_email
    message["Subject"] = subject
    message.attach(MIMEText(body, "plain"))

    payload = MIMEBase("application", "pdf", _name=attachment_filename)
    payload.set_payload(attachment_bytes)
    payload.add_header("Content-Disposition", "attachment", filename=attachment_filename)
    message.attach(payload)
    return message


def send_statement(
    db: Session,
    *,
    policy_id: int,
    to_email: str | None = None,
    actor_id: int | None = None,
) -> dict:
    """Send ``policy_id``'s statement to ``to_email`` (or its policyholder email).

    Returns a dict describing the sent message. Raises :class:`EmailError` when
    SMTP is disabled, when there is no destination address, or when the SMTP send
    fails; raises :class:`ValueError` for an unknown policy_id.
    """
    stmt = build_statement(db, policy_id=policy_id)

    if not settings.smtp_enabled:
        raise EmailError(
            "SMTP is not configured; set GROUP_INSURE_SMTP_ENABLED=1 to send "
            "statements by email"
        )

    recipient = (to_email or stmt["policyholder_email"] or "").strip()
    if not recipient:
        raise EmailError(
            "No email address to send to; the policyholder has no recorded "
            "email address"
        )

    subject = f"Policy Statement {stmt['policy_number']}"
    filename = f"statement-{stmt['policy_number']}.pdf"
    body = (
        f"Dear {stmt['policyholder_name']},\n\n"
        f"Please find attached your policy reconciliation statement for "
        f"{stmt['policy_number']}.\n\n"
        f"Policy period: {stmt['start_date']} to {stmt['end_date']}\n"
        f"Total billed:  {stmt['total_invoiced']:.2f}\n"
        f"Total paid:    {stmt['total_paid']:.2f}\n"
        f"Outstanding:   {stmt['balance_outstanding']:.2f}\n\n"
        "This statement was generated automatically by the Group Insurance "
        "Admin Platform."
    )

    message = _build_email(
        to_email=recipient,
        subject=subject,
        body=body,
        attachment_bytes=render_statement_pdf(stmt),
        attachment_filename=filename,
    )

    context = ssl.create_default_context()
    try:
        if settings.smtp_use_tls:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as server:
                server.ehlo()
                server.starttls(context=context)
                server.ehlo()
                if settings.smtp_user:
                    server.login(settings.smtp_user, settings.smtp_password)
                server.sendmail(settings.email_from, [recipient], message.as_string())
        else:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as server:
                if settings.smtp_user:
                    server.login(settings.smtp_user, settings.smtp_password)
                server.sendmail(settings.email_from, [recipient], message.as_string())
    except smtplib.SMTPException as exc:
        raise EmailError(f"SMTP send failed: {exc}") from exc

    record_log(
        db,
        action="statement_sent",
        actor_id=actor_id,
        entity="Statement",
        entity_id=policy_id,
        details=f"to={recipient} policy={stmt['policy_number']}",
    )
    return {
        "policy_id": policy_id,
        "to": recipient,
        "subject": subject,
        "attachment": filename,
    }
