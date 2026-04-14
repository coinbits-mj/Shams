# tests/test_email_mining.py
from __future__ import annotations

import pytest


@pytest.mark.usefixtures("setup_db")
class TestMemoryHelpers:
    def test_insert_email_archive_returns_id_and_is_idempotent(self):
        import memory

        email = {
            "account": "personal",
            "gmail_message_id": "test_msg_001",
            "gmail_thread_id": "test_thread_001",
            "from_addr": "a@b.com",
            "from_name": "A B",
            "to_addrs": ["me@me.com"],
            "subject": "Test",
            "date": "2026-04-13T00:00:00Z",
            "snippet": "hi",
            "body": "hello world",
            "category": "other",
            "priority": "P3",
            "entities": {"action_needed": False},
            "processed_model": "claude-sonnet-4-6",
        }

        id1 = memory.insert_email_archive(email)
        assert id1 is not None

        # Re-insert same message — should return existing id, not duplicate.
        id2 = memory.insert_email_archive(email)
        assert id2 == id1

    def test_insert_ap_invoice(self):
        import memory

        archive_id = memory.insert_email_archive({
            "account": "qcc",
            "gmail_message_id": "msg_ap_001",
            "gmail_thread_id": "t1",
            "subject": "Invoice",
            "category": "invoice",
            "priority": "P2",
            "entities": {},
        })
        inv_id = memory.insert_ap_invoice({
            "archive_id": archive_id,
            "vendor": "Sysco",
            "amount_cents": 124000,
            "currency": "USD",
            "invoice_number": "INV-001",
            "due_date": "2026-04-25",
            "notes": None,
        })
        assert inv_id is not None

    def test_insert_cx_complaint(self):
        import memory

        archive_id = memory.insert_email_archive({
            "account": "qcc",
            "gmail_message_id": "msg_cx_001",
            "gmail_thread_id": "t2",
            "subject": "Problem",
            "category": "customer_complaint",
            "priority": "P2",
            "entities": {},
        })
        cx_id = memory.insert_cx_complaint({
            "archive_id": archive_id,
            "customer_email": "c@c.com",
            "customer_name": "C",
            "issue_summary": "stale coffee",
            "severity": "med",
        })
        assert cx_id is not None

    def test_thread_escalation_tracking(self):
        import memory

        archive_id = memory.insert_email_archive({
            "account": "coinbits",
            "gmail_message_id": "msg_legal_001",
            "gmail_thread_id": "thread_legal_xyz",
            "subject": "Legal",
            "category": "coinbits_legal",
            "priority": "P1",
            "entities": {},
        })
        assert memory.thread_already_escalated("thread_legal_xyz") is False
        memory.record_thread_escalation("thread_legal_xyz", "coinbits_legal", archive_id)
        assert memory.thread_already_escalated("thread_legal_xyz") is True

    def test_backfill_cursor(self):
        import memory

        assert memory.get_backfill_cursor("personal") is None
        memory.set_backfill_cursor("personal", "page_token_abc")
        assert memory.get_backfill_cursor("personal") == "page_token_abc"
        memory.set_backfill_cursor("personal", "page_token_def")
        assert memory.get_backfill_cursor("personal") == "page_token_def"


class TestClassifier:
    """Tests classifier output shape and category coverage.

    Uses mocked anthropic client; no real API calls.
    """

    def test_classify_returns_expected_shape(self, monkeypatch):
        import email_mining

        # Mock the anthropic call to return a known classification.
        def fake_call(messages, system):
            return '{"category":"invoice","priority":"P2","entities":{"vendor":"Sysco","amount_cents":124000,"currency":"USD","invoice_number":"INV-001","due_date":"2026-04-25"}}'

        monkeypatch.setattr(email_mining, "_call_sonnet", fake_call)

        result = email_mining.classify_and_extract({
            "from_addr": "billing@sysco.com",
            "subject": "Invoice INV-001",
            "snippet": "Your invoice for $1,240.00 is attached.",
            "body": "Dear customer, please find attached invoice INV-001 for $1,240.00 due 2026-04-25.",
        })

        assert result["category"] == "invoice"
        assert result["priority"] == "P2"
        assert result["entities"]["vendor"] == "Sysco"
        assert result["entities"]["amount_cents"] == 124000

    def test_classify_unknown_category_falls_back_to_other(self, monkeypatch):
        import email_mining

        def fake_call(messages, system):
            return '{"category":"not_a_real_category","priority":"P3","entities":{}}'

        monkeypatch.setattr(email_mining, "_call_sonnet", fake_call)
        result = email_mining.classify_and_extract({
            "from_addr": "x@y.com", "subject": "hi", "snippet": "hi", "body": "hi"
        })
        assert result["category"] == "other"
        assert result["priority"] == "P3"

    def test_classify_malformed_json_returns_error_category(self, monkeypatch):
        import email_mining

        def fake_call(messages, system):
            return "this is not json at all"

        monkeypatch.setattr(email_mining, "_call_sonnet", fake_call)
        result = email_mining.classify_and_extract({
            "from_addr": "x@y.com", "subject": "hi", "snippet": "hi", "body": "hi"
        })
        assert result["category"] == "_error"
