# 2026-10-19 — Scheduled scouts, 8am watchdog, fixes from last round

**Engine (kdavis-microsaas-engine):** be1f58f, 17d15ff, 5cf2e98 (prod = main HEAD).
**Platform:** 3fffacd (LinkedIn image fallback). **DecodedSix:** 4810ff3 (discovery schedule).

## What shipped
- In-process schedules: pain rescan (Sundays, after the scout), Hacker News (3rd), partners + VC (1st, partners <= 20 Brave queries). Lock row: `mse_scheduled_job_runs`.
- Seven more pain phrases. The rescan reads each lead's own posting and only boosts for new phrases.
- Partners lane ordered: VC platform > compliance/audit > fractional CISO > AI agency.
- 8am LinkedIn enrollment: one audit row per run, per-lead skips in `mse_dm_enrollment_skips` (shown on the Write desk), and an 08:45 MST alert email if the run is missing or failed.
- Cloud Decoded lead finder: the trigger and run use a reconnecting DB client (the Oct 11 run was lost to a dropped connection).
- LinkedIn dispatcher: falls back to the checkout's image when the backend 404s; post 37304cce published.
- DecodedSix discovery: every 4 hours in-process, with a heartbeat row.
- Staging mse-api now has its own Supabase project.
- Brave ledger now counts domain-lookup queries (October was under by 67; corrected).

## If this fails next time
- Scheduler: `select * from mse_scheduled_job_runs order by claimed_at desc`.
- 8am run: `audit_log where action='linkedin_dm_sequences_run'`; alerts: `action='dm_8am_alert_sent'`.
- DecodedSix: its `audit_log where action='discovery_cycle'`.
