"""DocuSeal e-signature API client — self-hosted document signing."""

from __future__ import annotations

import base64
import logging
import requests
from config import DOCUSEAL_API_URL, DOCUSEAL_API_TOKEN

logger = logging.getLogger(__name__)


def _headers() -> dict:
    return {
        "X-Auth-Token": DOCUSEAL_API_TOKEN,
        "Content-Type": "application/json",
    }


def _post(path: str, data: dict) -> dict | None:
    if not DOCUSEAL_API_URL or not DOCUSEAL_API_TOKEN:
        logger.warning("DocuSeal not configured")
        return None
    try:
        r = requests.post(f"{DOCUSEAL_API_URL}/api{path}",
                         json=data, headers=_headers(), timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.error(f"DocuSeal POST {path}: {e}")
        return None


def _get(path: str, params: dict | None = None) -> dict | list | None:
    if not DOCUSEAL_API_URL or not DOCUSEAL_API_TOKEN:
        return None
    try:
        r = requests.get(f"{DOCUSEAL_API_URL}/api{path}",
                        headers=_headers(), params=params, timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.error(f"DocuSeal GET {path}: {e}")
        return None


# ── Templates ──────────────────────────────────────────────────────────────

def create_template_from_pdf(name: str, pdf_bytes: bytes) -> dict | None:
    """Upload a PDF and create a signing template."""
    b64 = base64.b64encode(pdf_bytes).decode()
    return _post("/templates", {
        "name": name,
        "documents": [{"name": name, "file_base64": b64}],
    })


def list_templates(limit: int = 20) -> list:
    """List available templates."""
    result = _get("/templates", {"limit": limit})
    return result if isinstance(result, list) else []


def get_template(template_id: int) -> dict | None:
    return _get(f"/templates/{template_id}")


# ── Submissions (send for signing) ─────────────────────────────────────────

def send_for_signature(template_id: int, signers: list[dict],
                       send_email: bool = True, message: str = "") -> dict | None:
    """Send a document for signing.

    signers: [{"email": "...", "name": "...", "role": "First Party"}]
    """
    data = {
        "template_id": template_id,
        "send_email": send_email,
        "submitters": signers,
    }
    if message:
        data["message"] = message
    return _post("/submissions", data)


def create_and_send(name: str, pdf_bytes: bytes, signers: list[dict],
                    send_email: bool = True, message: str = "") -> dict | None:
    """One-shot: upload PDF as template, then send for signing."""
    # Create template
    template = create_template_from_pdf(name, pdf_bytes)
    if not template:
        return None
    template_id = template.get("id")
    if not template_id:
        return None

    # Send for signing
    submission = send_for_signature(template_id, signers, send_email, message)
    if submission:
        submission["template_id"] = template_id
    return submission


def get_submission(submission_id: int) -> dict | None:
    """Check submission status."""
    return _get(f"/submissions/{submission_id}")


def list_submissions(status: str | None = None, limit: int = 20) -> list:
    """List all submissions."""
    params = {"limit": limit}
    if status:
        params["status"] = status
    result = _get("/submissions", params)
    return result if isinstance(result, list) else []


def download_signed_pdf(submission_id: int) -> bytes | None:
    """Download the signed PDF."""
    if not DOCUSEAL_API_URL or not DOCUSEAL_API_TOKEN:
        return None
    try:
        r = requests.get(
            f"{DOCUSEAL_API_URL}/api/submissions/{submission_id}/download",
            headers=_headers(), timeout=30)
        r.raise_for_status()
        return r.content
    except Exception as e:
        logger.error(f"DocuSeal download: {e}")
        return None


def is_configured() -> bool:
    return bool(DOCUSEAL_API_URL and DOCUSEAL_API_TOKEN)
