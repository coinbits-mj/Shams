"""Recall.ai client — stub for meeting bot development.

Will be replaced by Task 2 implementation.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def create_bot(meeting_url: str, bot_name: str = "Shams Notetaker", join_at: str | None = None) -> dict | None:
    """Create a Recall.ai bot to join a meeting. Stub — returns None."""
    logger.warning("recall_client.create_bot called but not yet implemented")
    return None


def get_bot(bot_id: str) -> dict | None:
    """Get bot status. Stub."""
    return None


def get_transcript(bot_id: str) -> list:
    """Get transcript. Stub."""
    return []
