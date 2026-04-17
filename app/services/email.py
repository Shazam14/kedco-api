import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


def _smtp_cfg():
    host = os.getenv("SMTP_HOST")
    if not host:
        return None
    return {
        "host":     host,
        "port":     int(os.getenv("SMTP_PORT", "587")),
        "user":     os.getenv("SMTP_USER", ""),
        "password": os.getenv("SMTP_PASS", ""),
        "from":     os.getenv("SMTP_FROM", os.getenv("SMTP_USER", "")),
        "to":       os.getenv("ADMIN_EMAIL", ""),
    }


def notify_edit_request(txn_id: str, requested_by: str, proposed: dict, note: str | None):
    cfg = _smtp_cfg()
    if not cfg or not cfg["to"]:
        return

    changes = ", ".join(f"{k} → {v}" for k, v in proposed.items())
    body = (
        f"Cashier {requested_by} has submitted an edit request for transaction {txn_id}.\n\n"
        f"Proposed changes:\n{changes}\n"
        + (f"\nNote: {note}\n" if note else "")
        + "\nPlease log in to review and approve or reject this request."
    )

    msg = MIMEMultipart()
    msg["From"]    = cfg["from"]
    msg["To"]      = cfg["to"]
    msg["Subject"] = f"[Kedco FX] Edit request for {txn_id} by {requested_by}"
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP(cfg["host"], cfg["port"]) as s:
            s.starttls()
            if cfg["user"]:
                s.login(cfg["user"], cfg["password"])
            s.sendmail(cfg["from"], cfg["to"], msg.as_string())
    except Exception:
        pass  # never fail the request because email failed
