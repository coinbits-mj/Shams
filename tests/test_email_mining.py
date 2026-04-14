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


@pytest.mark.usefixtures("setup_db")
class TestRouter:
    def test_route_invoice_creates_ap_queue_row(self):
        import email_mining, memory, db

        archive_id = memory.insert_email_archive({
            "account": "qcc",
            "gmail_message_id": "msg_route_inv_001",
            "gmail_thread_id": "t_inv",
            "subject": "Invoice",
            "category": "invoice",
            "priority": "P2",
            "entities": {},
        })
        email_mining.route_extracted(
            archive_id=archive_id,
            category="invoice",
            entities={"vendor": "Odeko", "amount_cents": 85000, "currency": "USD",
                      "invoice_number": "ODK-42", "due_date": "2026-05-01"},
        )
        with db.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT vendor, amount_cents, invoice_number FROM shams_ap_queue WHERE archive_id = %s", (archive_id,))
                row = cur.fetchone()
        assert row == ("Odeko", 85000, "ODK-42")

    def test_route_customer_complaint_creates_cx_row(self):
        import email_mining, memory, db

        archive_id = memory.insert_email_archive({
            "account": "qcc",
            "gmail_message_id": "msg_route_cx_001",
            "gmail_thread_id": "t_cx",
            "subject": "stale",
            "category": "customer_complaint",
            "priority": "P2",
            "entities": {},
        })
        email_mining.route_extracted(
            archive_id=archive_id,
            category="customer_complaint",
            entities={"customer_email": "c@c.com", "customer_name": "C",
                      "issue_summary": "stale beans", "severity": "high"},
        )
        with db.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT customer_email, severity FROM shams_cx_log WHERE archive_id = %s", (archive_id,))
                row = cur.fetchone()
        assert row == ("c@c.com", "high")

    def test_route_deal_pitch_calls_create_deal(self, monkeypatch):
        import email_mining

        captured = {}
        def fake_create_deal(**kwargs):
            captured.update(kwargs)
            return 42
        monkeypatch.setattr("memory.create_deal", fake_create_deal)

        email_mining.route_extracted(
            archive_id=1,
            category="deal_pitch",
            entities={"title": "Red House Roasters buyout",
                      "deal_type": "acquisition",
                      "contact": "broker@x.com"},
            source_subject="Possible sale",
        )
        assert captured["title"] == "Red House Roasters buyout"
        assert captured["deal_type"] == "acquisition"

    def test_route_noise_does_nothing(self):
        import email_mining
        # Should not raise, no side effects.
        email_mining.route_extracted(archive_id=None, category="newsletter", entities={})


class TestArchiver:
    def test_archive_skips_priority_categories(self, monkeypatch):
        import email_mining

        called = {"archive": False, "mark_read": False}
        monkeypatch.setattr("google_client.archive_email", lambda *a, **kw: called.update({"archive": True}) or True)
        monkeypatch.setattr("google_client.mark_read", lambda *a, **kw: called.update({"mark_read": True}) or True)

        for cat in email_mining.PRIORITY_CATEGORIES:
            called["archive"] = False
            called["mark_read"] = False
            result = email_mining.archive_in_gmail("personal", "msg1", category=cat)
            assert result is False, f"priority category {cat} should NOT archive"
            assert called["archive"] is False
            assert called["mark_read"] is False

    def test_archive_skips_personal(self, monkeypatch):
        import email_mining
        monkeypatch.setattr("google_client.archive_email", lambda *a, **kw: True)
        monkeypatch.setattr("google_client.mark_read", lambda *a, **kw: True)
        assert email_mining.archive_in_gmail("personal", "msg1", category="personal") is False

    def test_archive_skips_error(self, monkeypatch):
        import email_mining
        monkeypatch.setattr("google_client.archive_email", lambda *a, **kw: True)
        monkeypatch.setattr("google_client.mark_read", lambda *a, **kw: True)
        assert email_mining.archive_in_gmail("personal", "msg1", category="_error") is False

    def test_archive_noise_calls_gmail(self, monkeypatch):
        import email_mining

        calls = []
        monkeypatch.setattr("google_client.archive_email", lambda acct, mid: calls.append(("archive", acct, mid)) or True)
        monkeypatch.setattr("google_client.mark_read", lambda acct, mid: calls.append(("mark_read", acct, mid)) or True)

        result = email_mining.archive_in_gmail("coinbits", "msgXYZ", category="newsletter")
        assert result is True
        assert ("archive", "coinbits", "msgXYZ") in calls
        assert ("mark_read", "coinbits", "msgXYZ") in calls

    def test_archive_respects_dry_run(self, monkeypatch):
        import email_mining

        monkeypatch.setenv("EMAIL_MINING_DRY_RUN", "true")
        calls = []
        monkeypatch.setattr("google_client.archive_email", lambda *a: calls.append("archive") or True)
        monkeypatch.setattr("google_client.mark_read", lambda *a: calls.append("mark_read") or True)

        result = email_mining.archive_in_gmail("coinbits", "msgXYZ", category="newsletter")
        assert result is False, "dry-run should not touch Gmail"
        assert calls == []
