"""Deal pipeline tools."""
from __future__ import annotations

from tools.registry import tool


@tool(
    name="create_deal",
    description="Add a new deal/opportunity to the pipeline. Use when Scout finds an acquisition target, real estate listing, partnership opportunity, or any money-making prospect.",
    agent="wakil",
    schema={
        "properties": {
            "title": {"type": "string", "description": "Deal title (e.g. 'Red House Roasters Acquisition')"},
            "deal_type": {"type": "string", "enum": ["acquisition", "real_estate", "partnership", "investment", "vendor", "other"]},
            "value": {"type": "number", "description": "Estimated deal value in dollars"},
            "contact": {"type": "string", "description": "Key contact person"},
            "source": {"type": "string", "description": "How we found this (Scout research, email, referral, etc.)"},
            "location": {"type": "string", "description": "Physical location if applicable"},
            "next_action": {"type": "string", "description": "Next step to take"},
            "score": {"type": "integer", "description": "Opportunity score 1-10 (10 = best)"},
            "notes": {"type": "string", "description": "Additional context"},
        },
        "required": ["title"],
    },
)
def create_deal(title: str, deal_type: str = "acquisition", value: float = 0, contact: str = "",
                source: str = "", location: str = "", next_action: str = "", score: int = 0, notes: str = "") -> str:
    import memory

    deal_id = memory.create_deal(
        title=title,
        deal_type=deal_type,
        value=value,
        contact=contact,
        source=source,
        location=location,
        next_action=next_action,
        score=score,
        notes=notes,
    )
    memory.log_activity("scout", "deal_created", f"Deal #{deal_id}: {title}")
    memory.create_notification("deal_created", f"New deal: {title}", source, "deal", deal_id)
    return f"Deal #{deal_id} added to pipeline: {title}"


@tool(
    name="update_deal",
    description="Update a deal's stage, score, next action, or other details. Use to advance deals through the pipeline.",
    agent="wakil",
    schema={
        "properties": {
            "deal_id": {"type": "integer"},
            "stage": {"type": "string", "enum": ["lead", "researching", "evaluating", "loi", "due_diligence", "closing", "closed", "dead"]},
            "value": {"type": "number"},
            "next_action": {"type": "string"},
            "score": {"type": "integer"},
            "notes": {"type": "string"},
        },
        "required": ["deal_id"],
    },
)
def update_deal(deal_id: int, stage: str = None, value: float = None, next_action: str = None,
                score: int = None, notes: str = None) -> str:
    import memory

    kwargs = {}
    if stage is not None:
        kwargs["stage"] = stage
    if value is not None:
        kwargs["value"] = value
    if next_action is not None:
        kwargs["next_action"] = next_action
    if score is not None:
        kwargs["score"] = score
    if notes is not None:
        kwargs["notes"] = notes
    memory.update_deal(deal_id, **kwargs)
    memory.log_activity("shams", "deal_updated", f"Deal #{deal_id} → {kwargs.get('stage', 'updated')}")
    return f"Deal #{deal_id} updated."
