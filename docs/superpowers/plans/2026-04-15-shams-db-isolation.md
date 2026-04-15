# Shams DB Isolation Plan

**Goal:** Move all `shams_*` tables and data from the shared Railway Postgres (currently used by both Shams and Rumi) to a dedicated `shams-db` Postgres in the same Railway project. Strict safety: full backup first, staging rehearsal before prod, rollback-safe until the very last step.

**Audit already complete:** Rumi codebase has zero references to `shams_*` tables (confirmed via grep across `.py`/`.js`/`.ts`/`.sql`/config). Safe to migrate.

**Downtime tolerance:** user approved brief (~5-10 min) Shams outage during Phase 3.

---

## Phase 1 — Preparation (no prod changes, safe)

- [ ] **Step 1.1: Full safety backup** — pg_dump the entire current shared DB to a timestamped file under `/Users/mj/code/Shams/backups/`. Retain until Phase 4 verification.
- [ ] **Step 1.2: Inventory every `shams_*` table** — query `information_schema` to list all tables and row counts. Save the list to `backups/shams-table-inventory-<ts>.txt`.
- [ ] **Step 1.3: Provision `shams-db` Postgres service** — Railway GraphQL API, in `aware-strength` project. Wait for `DATABASE_URL` to be available.
- [ ] **Step 1.4: Dump only the `shams_*` tables** — pg_dump with `--table=shams_*` patterns to a separate file. Verify file size + row counts match inventory.

## Phase 2 — Staging rehearsal

- [ ] **Step 2.1: Provision `shams-db-staging` Postgres service** (ephemeral — will be deleted after this phase).
- [ ] **Step 2.2: Restore Phase 1 dump into staging DB.**
- [ ] **Step 2.3: Verify row counts** — compare every table's row count against the inventory from Step 1.2.
- [ ] **Step 2.4: Smoke-test a local Shams instance against staging** — boot `app.py` locally with staging `DATABASE_URL`. Run a few queries:
    - `memory.recall("anything")`
    - List a few rows from `shams_email_archive`
    - Verify the new email-mining Claude tools work
- [ ] **Step 2.5: Delete `shams-db-staging`.**

## Phase 3 — Live migration (downtime window)

- [ ] **Step 3.1: Pause Shams** via Railway (stop the deployment temporarily).
- [ ] **Step 3.2: Fresh dump** of `shams_*` tables (captures anything written since Phase 1.4).
- [ ] **Step 3.3: Restore** fresh dump into the real `shams-db`.
- [ ] **Step 3.4: Verify row counts** match between old and new DBs for every `shams_*` table.
- [ ] **Step 3.5: Update Shams's `DATABASE_URL`** env var on Railway to point at `shams-db`.
- [ ] **Step 3.6: Resume Shams** — Railway redeploy.
- [ ] **Step 3.7: Smoke tests (live)**:
    - Telegram: send "status" to the bot, expect a response
    - Dashboard: load `app.myshams.ai`, confirm it renders
    - Email archive query via Shams chat
    - Tail Railway logs for any Postgres errors

## Phase 4 — Cleanup (after 24h of stable operation)

- [ ] **Step 4.1: Wait 24 hours** — observe Shams stability. If anything breaks, rollback by reverting `DATABASE_URL` to the old shared DB.
- [ ] **Step 4.2: Archive the dump files** off local disk.
- [ ] **Step 4.3: Drop `shams_*` tables** from the old shared (Rumi) DB with explicit `DROP TABLE IF EXISTS ... CASCADE` for each table on the inventory list.
- [ ] **Step 4.4: Verify Rumi still healthy** after drops.

## Rollback plan

- If Phase 3 fails **after** Step 3.5: revert `DATABASE_URL` to old DB, redeploy Shams. Data never touched until Phase 4.
- If Phase 3 fails **before** Step 3.5: nothing to roll back — old DB untouched, Shams never interrupted.
- If Phase 4 fails (drops): we have a full backup from Step 1.1 to restore from.

## What this plan does NOT do

- Does not rotate the Shams DB password (user declined).
- Does not change Rumi in any way (audit confirms no cross-dependencies).
- Does not migrate Shams code itself — only the data layer.
