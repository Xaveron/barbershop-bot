# Production Migration Runbook — 0003 → 0010 (Phase 6.5)

> **REAL PRODUCTION WAS NOT TOUCHED DURING PHASE 6.5.** Every command, count, and test result in
> this document (except where explicitly marked "on real production") was produced against
> disposable scratch databases on a development Postgres instance. The real `barbershop` database
> was only ever read twice, read-only, to confirm it stayed at migration `0003` throughout — see
> `docs/MIGRATION_0010_REHEARSAL.md` for that rehearsal's full record.

This document has three zones. Read the label on every command block before running it.

- 🟢 **LOCAL/SCRATCH** — a throwaway database, safe to break, safe to drop.
- 🟡 **STAGING / RESTORED PRODUCTION COPY** — a restored backup running in an *isolated* Postgres
  instance that is not the production server and is not reachable by the real bot. Mistakes here
  cost you a re-restore, not customer data.
- 🔴 **REAL PRODUCTION** — the actual `barbershop_db` container / database the live bot uses.
  Every command in this zone is written to be run once, deliberately, by a human who has completed
  every step before it.

## 1. What is being shipped

Migrations `0004`→`0010` (multi-tenancy, RBAC, audit log, branches, barber-service opt-out,
tenant lifecycle, billing/subscriptions) plus application commit `4690991`. Production is
currently at `0003`. There is no partial-rollout path — see §4.

## 2. Pre-flight checklist (🟡 before touching anything real)

Run every item before scheduling a production window.

1. **Back up production** using the existing tool, from the real host:
   ```
   ./tools/backup.sh
   ```
   This runs `pg_dump -U barber -d barbershop --clean --if-exists | gzip`, checks the archive
   isn't truncated, and prints the exact restore command. Confirm the printed file size looks
   plausible for your actual data volume, not just >1KB.

2. **Verify the backup is restorable** — restore it into an *isolated* instance, never onto the
   real server:
   ```
   # 🟡 a separate scratch Postgres (a new container, or a new database on a
   # non-production server) — never `docker compose exec db psql ... -d barbershop`
   gunzip -c backups/barbershop_<timestamp>.sql.gz | psql -U barber -d <isolated_restore_db>
   ```
   Then confirm it's actually usable:
   ```
   psql -U barber -d <isolated_restore_db> -c "SELECT version_num FROM alembic_version;"
   psql -U barber -d <isolated_restore_db> -c "SELECT count(*) FROM appointments;"
   ```
   The version must read `0003`. If `alembic_version` doesn't exist at all, the backup predates
   even the initial schema tracking — stop and investigate before proceeding.

3. **Record real row counts** against that restored copy (not against production directly — no
   need to add read load to the live server for this):
   ```
   psql -U barber -d <isolated_restore_db> -c "
     SELECT 'barbers' t, count(*) FROM barbers
     UNION ALL SELECT 'services', count(*) FROM services
     UNION ALL SELECT 'users', count(*) FROM users
     UNION ALL SELECT 'appointments', count(*) FROM appointments
     UNION ALL SELECT 'working_schedules', count(*) FROM working_schedules
     UNION ALL SELECT 'schedule_exceptions', count(*) FROM schedule_exceptions
     UNION ALL SELECT 'notifications', count(*) FROM notifications;"
   ```
   Save this output — it's what you diff against after migrating (§7). §3's risk table assumes a
   dataset in the hundreds-to-low-thousands of rows per table (typical for one shop). If any count
   is dramatically larger, re-read §3's `0004`/`0007` rows before proceeding — the lock durations
   assessed there scale with row count and haven't been measured at a larger size.

4. **Confirm the environment migration `0004` will actually run under matches production.**
   `0004` calls `get_settings()` at migration time to seed the tenant's `shop_name`/`shop_address`/
   `shop_phone`/`timezone`/`currency` from whatever `.env`/environment is active during the
   migration run. If you run migration from a shell or container with stale/example env values,
   the one-time seed will be wrong (fixable afterward via the admin panel, but avoid it — see the
   rehearsal in `docs/MIGRATION_0010_REHEARSAL.md` §2 for a demonstration of this exact dependency).

5. **Rehearse the actual jump on the restored copy** (🟡): run the full sequence in §5 against
   `<isolated_restore_db>` first, including the verification script (§6) and smoke tests (§8).
   This phase rehearsed the jump only on a *reconstructed* pre-`0004` dataset (no real backup was
   available in the environment this phase ran in) — running it once against your actual restored
   backup, with actual row counts and actual historical data, is not optional before touching real
   production.

## 3. Migration-by-migration risk (0004–0010)

| Migration | Operation | Lock risk | Data risk | Impact | Recommendation |
|---|---|---|---|---|---|
| `0004` | `ADD COLUMN tenant_id` (nullable) on 6 tables | Metadata-only, near-instant regardless of size | None | None | Safe as-is |
| `0004` | `UPDATE {table} SET tenant_id = ...` (backfill, 6 tables incl. `appointments`) | `ROW EXCLUSIVE` while running; blocks concurrent writers to touched rows | None (idempotent single value) | Brief write pause proportional to row count | Confirm real row counts first (§2.3); stop the bot before running (§4) so there are no concurrent writers to contend with |
| `0004` | `ALTER COLUMN tenant_id SET NOT NULL` (6 tables incl. `appointments`) | `ACCESS EXCLUSIVE` for the full-table NULL-check scan | None | Blocks **all** reads and writes on that table for the scan's duration | Same mitigation — bot must be stopped; for a small shop this is sub-second, unverified at larger scale |
| `0004` | New unique constraints (`uq_services_tenant_id_name`, `uq_users_tenant_id_telegram_id`, `uq_barbers_tenant_id_telegram_id`) replacing global-unique ones | Brief `ACCESS EXCLUSIVE`/validation scan | None (drops old constraint after data already satisfies the new one, since there's one tenant) | Low, same table sizes as above | Safe as-is |
| `0005` | `CREATE TABLE staff_members` (+ optional seed row per `ADMIN_ID`) | None (new table) | None | None | Safe as-is |
| `0006` | `CREATE TABLE audit_log_entries` | None (new table) | None | None | Safe as-is |
| `0007` | `CREATE TABLE branches/barber_branches/branch_services/staff_branches` + per-tenant backfill loop (default branch, links, `branch_id` on 3 existing tables) | Same `NOT NULL`-after-backfill pattern as `0004`, on `working_schedules`/`schedule_exceptions`/`appointments` | None | Same shape/size as `0004`'s appointments risk | Same mitigation |
| `0007` | New composite indexes (`ix_appointments_tenant_id_branch_id_starts_at`, etc.) | Plain `CREATE INDEX`, not `CONCURRENTLY` — blocks writes to the table for the build | None | Low for small tables | Acceptable for a single-shop dataset; would need `CONCURRENTLY` (run outside a transaction) if the appointments table is large — not verified either way here |
| `0008` | `CREATE TABLE barber_services` (empty, opt-out semantics — no existing barber/service behavior changes) | None | None | None | Safe as-is |
| `0009` | `ADD COLUMN tenants.status` + backfill `'active'` via `server_default`, then drop the default | Same `ACCESS EXCLUSIVE` pattern, but on `tenants` (tiny table — one row per shop) | None | Negligible | Safe as-is |
| `0009` | `CREATE UNIQUE INDEX ... WHERE role = 'tenant_owner'` on `staff_members` | Brief, `staff_members` is small | None (only one owner will exist pre-migration) | Negligible | Safe as-is |
| `0010` | `CREATE TABLE plans/plan_features/plan_limits/subscriptions` + catalog seed + per-tenant Legacy-subscription backfill | None (new tables; backfill is one `INSERT ... ON CONFLICT DO NOTHING` per tenant, tenant count is tiny) | None — Legacy plan is unlimited by design, no existing branch/staff/service is deactivated or deleted | Negligible | Safe as-is |

General notes that apply across the table: none of these migrations use `CREATE INDEX
CONCURRENTLY` (it cannot run inside Alembic's default transactional-DDL wrapping without extra
configuration this project doesn't have) — acceptable at the row counts a single-shop bot is
expected to have, worth re-examining if real counts from §2.3 turn out to be large.
`excl_appointments_barber_no_overlap` (the double-booking EXCLUDE constraint) is never redefined
by any of these migrations — confirmed by reading `0001` through `0010`; `barber_id` alone
continues to resolve to exactly one tenant throughout the whole chain, so the constraint's
guarantee is intact before, during, and after the jump.

## 4. Deployment ordering — evidence, not a guess

Two options exist in general for a schema change like this: migrate-then-deploy, or deploy a
backward-compatible app version first and migrate later. **Only the first is possible here**:

- **New code cannot start against the `0003` schema.** `app/main.py::run()` calls
  `resolve_default_tenant_id()` (`app/database/tenants.py`), which runs
  `SELECT ... FROM tenants` via `TenantRepository.get_default()`. The `tenants` table doesn't
  exist before `0004`. The new build's very first startup step crashes.
- **Old code cannot keep working once `0004` lands.** `0004` makes `tenant_id NOT NULL` with no
  server-side default on `users`/`barbers`/`services`/`working_schedules`/`schedule_exceptions`/
  `appointments`. The old build's INSERT statements don't know to supply it, so every new
  booking/customer/barber/service creation starts failing the instant the migration commits, even
  though the process itself keeps running.

There is no mixed-version window that works in either direction. The only safe sequence is:
**stop the bot completely → run the full migration → start the new build.** Budget for the bot
being offline for the whole window (§5's rehearsed timing was under 2 seconds for the migration
step itself on a small dataset, so the window is dominated by your own verification steps, not the
migration).

**Do not rely on the default `docker-entrypoint.sh` behavior for this cutover.** It runs
`alembic upgrade head` unconditionally before starting the bot on every container start — fine for
routine single-version bumps, but it gives you no checkpoint between "migration ran" and "bot is
live" for a 7-migration jump. Run the migration as its own explicit, observed step instead (§5).

## 5. Production sequence (🔴 — only after §2 is fully done and §5 has been rehearsed in 🟡)

```bash
# 1. Stop the bot — no writers during migration.
docker compose stop bot

# 2. One more backup, immediately before the real change.
./tools/backup.sh

# 3. Run the migration as its own step (bypasses the entrypoint's fused
#    migrate-then-start behavior deliberately — see §4).
docker compose run --rm bot alembic upgrade head

# 4. Verify before declaring success (§6).
docker compose run --rm -e DATABASE_URL="$DATABASE_URL" bot \
    python scripts/verify_production_migration.py

# 5. Only now bring the new build up.
docker compose up -d --build bot

# 6. Smoke test against the live bot (§8), then watch logs.
docker compose logs -f bot
```

If step 3 or step 4 fails, **do not proceed to step 5** — see §9.

## 6. Verification script

`scripts/verify_production_migration.py` (formerly `verify_migration_0010.py`, superseded — that
script's `EXPECTED_HEAD` predated migrations `0011`-`0013` and would misreport a correct `0013`
database as a failure) is read-only (no `INSERT`/`UPDATE`/`DELETE` anywhere in it) and checks,
against whatever `DATABASE_URL` you point it at: `alembic_version` is at `0013`; every table
introduced by `0004`-`0012` exists; the double-booking `EXCLUDE` constraint and the tenant-owner
partial unique index both exist; every tenant has exactly one subscription resolving to a known
plan; zero cross-tenant leakage across every branch/barber/service/staff association table; the
`telegram_bot_identities` FK/uniqueness/row validity from `0011`; the `platform_operators`
uniqueness/row validity and `audit_log_entries.tenant_id` nullability from `0012`; and the
`tenants.default_language`/`staff_members.language` column shape and supported-language values from
`0013`. Each check prints `PASS`, `WARN` (worth a look, not a failure — e.g. no bots/platform
operators registered yet), or `FAIL`. It exits non-zero only if something actually failed. Run it
against the restored copy during rehearsal and against production immediately after the real
migration (§5 step 4) — never skip it because the migration "looked like it worked."

## 7. Post-migration data integrity check

Re-run the same counts query from §2.3 against the now-migrated database and diff against the
saved pre-migration output:

```bash
psql -U barber -d <target_db> -c "
  SELECT 'barbers' t, count(*) FROM barbers
  UNION ALL SELECT 'services', count(*) FROM services
  UNION ALL SELECT 'users', count(*) FROM users
  UNION ALL SELECT 'appointments', count(*) FROM appointments
  UNION ALL SELECT 'working_schedules', count(*) FROM working_schedules
  UNION ALL SELECT 'schedule_exceptions', count(*) FROM schedule_exceptions
  UNION ALL SELECT 'notifications', count(*) FROM notifications;"
```

No count may be lower than before. Additionally confirm the billing backfill did what it should:

```bash
psql -U barber -d <target_db> -c "
  SELECT t.name, p.code AS plan, s.status,
         (SELECT count(*) FROM branches b WHERE b.tenant_id = t.id) AS branches
  FROM tenants t
  JOIN subscriptions s ON s.tenant_id = t.id
  JOIN plans p ON p.id = s.plan_id;"
```

Expect exactly one row, `plan = legacy`, `status = active`, `branches >= 1`. A `legacy` plan has
every limit unlimited by design (see `docs/BILLING_DESIGN.md`) — the shop cannot be newly blocked
from creating another branch/barber/service/staff member/appointment as a side effect of this
migration.

## 8. Smoke tests (run against the live bot after step 5)

Use the existing Telegram bot UI, as a real user and as the admin:

- [ ] Bot responds to `/start` (tenant resolution + `ACTIVE` tenant path both exercised).
- [ ] Client booking flow: service → barber → date → time → confirm creates a real appointment.
- [ ] Attempting to book an already-taken slot is rejected (double-booking protection).
- [ ] Cancel and reschedule an existing appointment both work and notify correctly.
- [ ] `/admin` opens for the real admin `ADMIN_ID`; a non-admin cannot open it (RBAC).
- [ ] Admin can view branches/barbers/services (branch isolation intact).
- [ ] Admin's "💳 Тариф" screen shows plan `Legacy`, status `Активна`, all features ✅, all limits
      `∞` (billing entitlement/limit checks).
- [ ] CSV export and the stats/analytics screen both still work (both gated by
      `Feature.CSV_EXPORT`/`Feature.ANALYTICS`, both present on Legacy).
- [ ] A reminder scheduled for the near future actually sends (`Feature.REMINDERS`, present on
      Legacy).

These are the same flows already covered by `tests/test_integration_booking.py`,
`tests/test_integration_branches.py`, `tests/test_integration_billing.py`, and
`tests/test_handlers_flow.py` — this checklist exists for a human to re-confirm them against the
one thing the automated suite can't see: the real bot process talking to the real Telegram API.

## 9. Rollback strategy

**Production rollback is not "run the downgrade migrations."** Concretely: `0003`'s own
`downgrade()` is a no-op — it does not remove the enum value it added, so even the *chain itself*
doesn't round-trip cleanly. Downgrade migrations are exercised in this project only on scratch or
restored copies (see `docs/MIGRATION_0010_REHEARSAL.md`), never as a production procedure.

If something goes wrong:

1. **Stop the bot immediately** if it hasn't already crashed (`docker compose stop bot`).
2. **Assess**: did the migration itself fail (transaction rolled back automatically — Alembic runs
   the whole `upgrade head` run in one transaction, so a mid-way failure leaves the database
   exactly as it was at `0003`), or did it succeed but the application/smoke tests reveal a
   problem?
3. **Prefer a forward fix** if the migration completed and the schema is correct but application
   behavior is wrong — fix and redeploy the application, don't unwind the schema.
4. **Restore from the pre-migration backup** (§5 step 2) only if the database itself is actually
   broken (a migration failed partway in a way that left it inconsistent, or a step was run
   against the wrong target). Restore into a fresh instance, verify it with §6 and §7, then point
   the bot at it.
5. **Deploy an application version compatible with whatever schema you end up running** — if you
   restore to a pre-`0004` backup, that means redeploying the pre-multi-tenancy build, not the new
   one (see §4's compatibility evidence — the new build cannot run against that schema at all).

## 10. Known risks / open questions for the operator

- Real production row counts are unknown to this phase — the risk table in §3 assumes a small
  single-shop dataset. Confirm via §2.3 before trusting the "negligible/low" assessments at scale.
- No real production backup/restore cycle was exercised in this phase (none was available in this
  environment) — §2's steps 1-2 must be performed for real, once, before the actual cutover.
- The currently-running `barbershop_bot` container is inferred (from §4's compatibility analysis,
  not from inspecting it directly) to be a pre-multi-tenancy build, since it could not have
  survived `docker-entrypoint.sh`'s auto-migration if it were already on `0004`+. Confirm what
  build is actually running before scheduling the window.
- `README.md`'s own local-testing instructions set `TEST_DATABASE_URL`/`DATABASE_URL` to a database
  named `barbershop` — on any machine where that name is the real compose database (as in the
  environment this phase ran in), following those instructions literally would run migrations and
  mutating tests against production. This was not fixed in this phase (out of scope), but should be
  fixed before anyone follows that README section against a real deployment host.
- `CREATE INDEX`/`ADD CONSTRAINT` statements throughout the chain are not `CONCURRENTLY` — fine at
  small scale, worth revisiting only if §2.3's counts turn out to be large.
