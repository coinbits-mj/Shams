"""DocuSeal (e-signature) tools."""
from __future__ import annotations

from tools.registry import tool


@tool(
    name="send_for_signature",
    description="Send a document for e-signature via DocuSeal. Use when Maher needs someone to sign a document — contracts, retainers, LOIs, NDAs, etc. Specify the signers and Shams handles the rest.",
    agent="wakil",
    schema={
        "properties": {
            "document_name": {"type": "string", "description": "Name of the document (e.g. 'Retainer Agreement - Somerville')"},
            "signers": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "email": {"type": "string"},
                    },
                    "required": ["name", "email"],
                },
                "description": "List of people who need to sign",
            },
            "message": {"type": "string", "description": "Optional message to include in the signing email"},
            "file_id": {"type": "integer", "description": "Optional: Shams file ID to use as the document"},
        },
        "required": ["document_name", "signers"],
    },
)
def send_for_signature(document_name: str, signers: list, message: str = "", file_id: int = None) -> str:
    import docuseal_client
    import memory

    if not docuseal_client.is_configured():
        return "DocuSeal not configured. Add DOCUSEAL_API_URL and DOCUSEAL_API_TOKEN to environment."

    signer_list_api = [{"email": s["email"], "name": s["name"], "role": "First Party"} for s in signers]

    # If file_id provided, get the document content
    if file_id:
        f = memory.get_file(file_id)
        if f and f.get("transcript"):
            # For now, create from template name — actual PDF upload needs binary
            pass

    # List templates to find matching one, or instruct to upload via dashboard
    templates = docuseal_client.list_templates()
    matching = [t for t in templates if document_name.lower() in (t.get("name") or "").lower()]
    if matching:
        result = docuseal_client.send_for_signature(
            matching[0]["id"], signer_list_api, send_email=True,
            message=message)
        if result:
            memory.log_activity("shams", "signature_sent",
                f"Sent '{document_name}' to {', '.join(s['name'] for s in signers)} for signature")
            memory.create_notification("signature_sent",
                f"Sent for signature: {document_name}",
                ", ".join(s["email"] for s in signers), "", None)
            signer_display = "\n".join(f"  - {s['name']} ({s['email']})" for s in signers)
            return f"Signature request sent!\nDocument: {document_name}\nSigners:\n{signer_display}\n\nThey'll receive an email with a signing link."
        return "Failed to send signature request. Check DocuSeal configuration."
    else:
        template_names = ", ".join(t.get("name", "?") for t in templates[:5]) if templates else "none"
        return f"No template found matching '{document_name}'. Upload the PDF first via the Signatures page in the dashboard, then try again.\nAvailable templates: {template_names}"


@tool(
    name="check_signatures",
    description="Check the status of pending signature requests. Shows who has signed and who hasn't.",
    agent="wakil",
    schema={
        "properties": {
            "limit": {"type": "integer", "description": "How many to check (default 5)", "default": 5},
        },
    },
)
def check_signatures(limit: int = 5) -> str:
    import docuseal_client

    if not docuseal_client.is_configured():
        return "DocuSeal not configured."
    submissions = docuseal_client.list_submissions(limit=limit)
    if not submissions:
        return "No signature requests found."
    lines = []
    for s in submissions:
        status = s.get("status", "unknown")
        submitters = s.get("submitters") or []
        signer_status = ", ".join(
            f"{sub.get('name', sub.get('email', '?'))}: {sub.get('status', '?')}"
            for sub in submitters
        )
        lines.append(f"#{s.get('id')} — {status} | {signer_status}")
    return "Signature requests:\n" + "\n".join(lines)
