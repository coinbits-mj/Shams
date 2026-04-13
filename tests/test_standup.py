"""Tests for overnight ops + morning standup."""
from __future__ import annotations


def test_config_has_overnight_and_standup_hours():
    import config
    assert hasattr(config, "OVERNIGHT_HOUR_UTC")
    assert hasattr(config, "STANDUP_HOUR_UTC")
    assert isinstance(config.OVERNIGHT_HOUR_UTC, int)
    assert isinstance(config.STANDUP_HOUR_UTC, int)
