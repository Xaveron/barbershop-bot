# Production Migration Runbook — 0003 → 0010 (Phase 6.5)

> **REAL PRODUCTION WAS NOT TOUCHED DURING PHASE 6.5.** Every command, count, and test result in
> this document (except where explicitly marked "on real production") was produced against
> disposable scratch databases on a development Postgres instance. The real `barbershop` database
> was only ever read twice, read-only, to confirm it stayed at migration `0003` throughout — see
> `docs/MIGRATION_0010_REHEARSAL.md` for that rehearsal's full record.

> ## ⚠ ENTRYPOINT HAZARD — read this before running ANY `docker compose` command against the `bot` service
>
> **`docker-entrypoint.sh` unconditionally runs `alembic upgrade head` before executing whatever
> command you asked for.** Its actual content is:
> ```sh
> set -e
> alembic upgrade head
> ...
> exec "$@"
> ```
> This means **`docker compose run bot <command>` — for ANY `<command>`, including one that looks
> purely like inspection or an administrative one-off — is NOT a read-only operation.** The
> migration step runs first, unconditionally, against whatever `DATABASE_URL` that service resolves
> to (production's, in the `bot` service's normal configuration), before your intended `<command>`
> ever executes.
>
> This is not theoretical: on 2026-09-16, exactly this happened for real (see §12). An operator
> intended to run `docker compose run --rm bot alembic heads` as a read-only check of a freshly
> built image's migration metadata. The entrypoint's forced `alembic upgrade head` ran first, using
> the `bot` service's real production `DATABASE_URL`, and migrated the real production database from
> `0003` to `0013` — before `alembic heads` was ever reached. No data was lost and the deployment was
> recovered (§12), but this must never happen again through the same mistake.
>
> **The only safe patterns for inspecting or running one-off commands against the `bot` image are:**
> 1. **`--entrypoint` override** — replaces `docker-entrypoint.sh` entirely, so the auto-migration
>    never runs: `docker run --rm --entrypoint alembic -e DATABASE_URL=<dummy> <image> heads`, or
>    `docker compose run --rm --entrypoint python bot -m app.register_bot --tenant-id <uuid>`.
> 2. **Host-side commands** — run directly on the host machine, never inside any container, against
>    the database's host-mapped port (`docker-compose.yml` binds Postgres to `127.0.0.1` for exactly
>    this). See §6.
> 3. **`docker compose exec <service> <command>`** (not `run`) — attaches to an *already-running*
>    container and does **not** re-invoke `ENTRYPOINT` at all. Safe for read-only queries against the
>    already-running `db`/`redis` services (e.g. `docker compose exec -T db psql ...`). Do not rely on
>    this for the `bot` service specifically if you need it to reflect a newly built image — `exec`
>    only sees whatever image the currently-running container already has.
>
> The **only** two places in this whole document where invoking the real entrypoint against
> production is intentional and correct are §5 step 5 (the actual migration) and §5 step 11
> (starting the new build, once the database is already confirmed at `0013`, making that
> entrypoint's migration step a safe no-op).

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
live" for a multi-migration jump, and (see the ENTRYPOINT HAZARD box at the top of this document,
and §12) it means **no `docker compose run bot <anything>` is ever read-only**. Run the migration as
its own explicit, observed step instead (§5), using the exact image/command discipline described
there — never a bare `docker compose run bot <command>` for inspection.

## 5. Production sequence (🔴 — only after §2 is fully done and §5 has been rehearsed in 🟡)

**Read the ENTRYPOINT HAZARD box at the top of this document first.** The order below is
deliberate: the image is built *before* anything is stopped or migrated, so that when the
migration actually runs, it unambiguously runs from an image that contains `0004`-`0013` — never
from whatever image happened to be sitting on disk already (§12 is exactly what goes wrong
otherwise). `register_bot` is not optional and must run before the new bot is started — see the
explanation below the command block.

```bash
# 1. Fresh backup, before touching anything.
./tools/backup.sh

# 2. Build the new image FIRST — before the bot is even stopped, before any
#    migration runs. This is a purely local build; it does not touch any
#    running container or the database.
docker compose build bot

# 3. Confirm the image you just built actually contains through 0013, WITHOUT
#    touching production — --entrypoint override, dummy DATABASE_URL, no real
#    connection is made:
docker run --rm --entrypoint alembic \
    -e DATABASE_URL=postgresql+asyncpg://x:x@localhost/x \
    -e BOT_TOKEN=0000000000:AA0000000000000000000000000000000 \
    barber_rshop-bot:latest heads
# Expect: "0013 (head)". If you see anything else, STOP — see the STOP
# CONDITIONS below. Do not proceed to step 4.

# 4. NOW stop the old bot — no writers during migration.
docker compose stop bot

# 5. Run the migration as its own explicit step, using the image built (and
#    verified) in steps 2-3. `docker compose run` still invokes the entrypoint
#    (which is exactly what you want here — this is the one deliberate,
#    observed migration step), against whatever image is currently tagged for
#    this service, which is the one you just built:
docker compose run --rm bot alembic upgrade head

# 6. Verify the revision landed correctly — read-only, via the already-running
#    db container (docker compose exec, not run — no entrypoint involved):
docker compose exec -T db psql -U barber -d barbershop -tAc \
    "SELECT version_num FROM alembic_version;"
# Expect exactly: 0013. If not, STOP — see STOP CONDITIONS. Do not proceed.

# 7. Run the production verifier — FROM THE HOST, not inside any container.
#    scripts/ is not baked into the Docker image (see §6) — this must run
#    against the database's host-mapped port.
DATABASE_URL=postgresql+asyncpg://barber:<password>@localhost:5432/barbershop \
    python scripts/verify_production_migration.py
# Expect: 0 FAIL. WARNs are fine only if they match §6's documented, expected
# ones. Any FAIL — STOP, see STOP CONDITIONS.

# 8. Identify the migrated tenant — read-only:
docker compose exec -T db psql -U barber -d barbershop -c \
    "SELECT id, name, status FROM tenants;"
# Expect exactly one row. Use the ACTUAL returned UUID below — never invent
# or assume it.

# 9. Register the existing bot with that tenant — MANDATORY, not optional
#    (see explanation below). --entrypoint override bypasses the auto-migration
#    (already done in step 5; this must not run it again on a whim):
docker compose run --rm --entrypoint python bot \
    -m app.register_bot --tenant-id <ACTUAL_TENANT_UUID>
# Then verify, read-only:
docker compose exec -T db psql -U barber -d barbershop -c \
    "SELECT telegram_bot_id, tenant_id, is_active FROM telegram_bot_identities;"
# Expect exactly one row, is_active = t, tenant_id matching step 8. If
# registration fails or this doesn't come back as expected — STOP.

# 10. Bootstrap the first PlatformOperator, IF ADMIN_ID/ADMIN_IDS is configured
#     and you want the platform control plane's explicit record (not required
#     for the tenant's own /admin panel — migration 0005 already seeded a
#     tenant_owner staff row from ADMIN_ID at migration time):
docker compose run --rm --entrypoint python bot -m app.bootstrap_platform_admin
# Then verify, read-only:
docker compose exec -T db psql -U barber -d barbershop -c \
    "SELECT role, is_active FROM platform_operators;"
# If ADMIN_ID is not configured, or you deliberately don't want this yet,
# skip this step and record explicitly in your own change log that it was
# skipped and why — do not skip it silently.

# 11. Only now start the new bot. The entrypoint's own alembic upgrade head
#     will run again here — since the DB is already at 0013 (step 6), this is
#     the one place besides step 5 where triggering the entrypoint is correct,
#     and it is expected to be a safe no-op, not a real migration:
docker compose up -d bot

# 12. Smoke test against the live bot (§8) — a real human with a real
#     Telegram client, not simulated.

# 13. Monitor logs.
docker compose logs -f bot
```

**`register_bot` (step 9) is mandatory, not a nice-to-have, and must happen before step 11.**
`app/bot/middlewares/bot_identity.py::BotIdentityMiddleware` has no fallback for a bot with no
`telegram_bot_identities` row: `if identity is None: ... return None` — the update is silently
dropped. After `0011` lands, if the bot is started (step 11) before it is registered (step 9), the
container will look healthy (running, no crash) while **silently rejecting every single update**
from real customers. This is exactly the intended design (per
`docs/BOT_IDENTITY_ARCHITECTURE.md`) — there is deliberately no "default tenant" fallback anymore —
so the fix is procedural, not a code change: always register before starting.

### STOP conditions — do not improvise past these

Stop the whole procedure and investigate/report instead of guessing forward if, at any point:

- the built image's `alembic heads` (step 3) does not report `0013`;
- the post-migration revision (step 6) is not exactly `0013`;
- `scripts/verify_production_migration.py` (step 7) reports any `FAIL`, or a `WARN` you don't
  recognize as one of the documented expected ones;
- exactly one tenant is not returned in step 8 (zero, or more than one);
- `register_bot` (step 9) exits non-zero, or the follow-up query doesn't show exactly one active
  identity row pointing at the correct tenant;
- `bootstrap_platform_admin` (step 10) exits non-zero when it was expected to succeed;
- the new bot (step 11) fails to start, restarts unexpectedly, or its logs show any exception,
  traceback, or a "неизвестного/отключённого bot_id" rejection warning;
- any smoke test (step 12) fails because of application behavior.

In every case above: **do not modify migration files, application code, or the schema to force it
to pass. Do not run `alembic downgrade`.** Stop, capture the exact error, and follow §9 (restore
from the backup taken in step 1, or the more recent one from §12 if that's the actual current
state) rather than improvising a fix mid-cutover.

## 6. Verification script

**Run this from the host machine, never from inside a container.** `scripts/` is not part of the
installed `app` package (`pyproject.toml`'s `packages = ["app"]`) and the `Dockerfile` never `COPY`s
it — no built image, however recently rebuilt, contains `scripts/verify_production_migration.py`.
`docker compose run`/`exec bot python scripts/verify_production_migration.py` will fail with a
"file not found" error regardless of the image. Run it directly on the host instead, pointed at the
database's host-mapped port (bound to `127.0.0.1` in `docker-compose.yml` for exactly this):

```bash
DATABASE_URL=postgresql+asyncpg://barber:<password>@localhost:5432/barbershop \
    python scripts/verify_production_migration.py
```

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

This restore-based approach — never `alembic downgrade` — is not just a recommendation: §11
exercised exactly this restore path for real (a real production backup, restored into an isolated
instance) and it worked; no downgrade migration in this chain has ever been run against anything
but a scratch database, and `0012`/`0013`'s downgrades are known to be lossy by design (see their
own `downgrade()` functions), so they remain out of scope for a real rollback.

**Restoring an older backup also erases any `telegram_bot_identities`/`platform_operators` rows
created after that backup was taken.** These are ordinary table rows like any other — a restore
doesn't selectively preserve them. Concretely: if you restore the backup from §5 step 1 (taken
*before* `register_bot`/`bootstrap_platform_admin` ran) after those steps have already run, the
restored database will not know about that bot registration or platform operator at all — you must
re-run §5 steps 9-10 again after the restore, once you bring that restored database forward to a
schema those commands expect. The same is true in reverse: if you restore a *post*-registration
backup (e.g. one taken during §12's recovery), it already contains those rows and nothing further
is needed on that front — but always re-verify with the same queries from §5 steps 9-10 rather than
assuming either way.

## 10. Known risks / open questions for the operator

- Real production row counts are unknown to this phase — the risk table in §3 assumes a small
  single-shop dataset. Confirm via §2.3 before trusting the "negligible/low" assessments at scale.
  (Phase 10B's real rehearsal, §11, confirms the actual production dataset — 2 barbers, 4 services,
  12 users, 5 appointments — is indeed at this small end of the range.)
- A real production backup/restore cycle, and the full `0003`→`0013` jump against it, has now been
  exercised for real — see §11. This closes the gap this bullet used to describe; it is kept here
  only so the history of "this was once unverified" isn't lost.
- **Superseded by §12.** This bullet used to say the running container's build was only *inferred*
  to be pre-multi-tenancy, not confirmed directly. It has since been confirmed directly (the running
  image's own `app/database/migrations/versions/` was inspected and found to contain only `0001`-
  `0003`), and as of §12's recovery, production has already been migrated to `0013` and is running a
  build containing `0001`-`0013` with a registered bot identity and a bootstrapped platform operator.
  Before any *future* maintenance action, don't assume this document's original `0003`-baseline
  framing still applies — re-confirm the actual current revision and running image the same way §12
  did, rather than trusting this file's earlier sections' "production is at `0003`" framing at face
  value.
- `README.md`'s own local-testing instructions set `TEST_DATABASE_URL`/`DATABASE_URL` to a database
  named `barbershop` — on any machine where that name is the real compose database (as in the
  environment this phase ran in), following those instructions literally would run migrations and
  mutating tests against production. This was not fixed in this phase (out of scope), but should be
  fixed before anyone follows that README section against a real deployment host.
- `CREATE INDEX`/`ADD CONSTRAINT` statements throughout the chain are not `CONCURRENTLY` — fine at
  small scale, worth revisiting only if §2.3's counts turn out to be large.

## 11. Phase 10B — real backup/restore rehearsal, exact `0003`→`0013` jump

Unlike §1-§10 above (which cover `0003`→`0010`, Phase 6.5, rehearsed only on scratch/reconstructed
data — see `docs/MIGRATION_0010_REHEARSAL.md`), this section records a rehearsal that ran the real
target of the eventual cutover: the actual production database (`barbershop_db`'s `barbershop` DB,
via `tools/backup.sh`, unmodified — no `INSERT`/`UPDATE`/`DELETE`/`ALTER`/`DROP` was ever issued
against it), restored into a disposable, isolated `postgres:16-alpine` container
(`barbershop_migration_rehearsal_0013`, unrelated to and never connected to any application
container), then migrated through the full current chain, `0003`→`0013`, not just `0003`→`0010`.

**What was confirmed, for real, not on synthetic data:**

- The real production backup, taken via the unmodified `tools/backup.sh`, restores cleanly and
  independently confirms production's own `alembic_version` is `0003` (read directly from the
  backup file's own `COPY public.alembic_version` data — not merely assumed).
- `alembic upgrade head` against the restored copy applies `0003`→`0004`→`0005`→`0006`→`0007`→
  `0008`→`0009`→`0010`→`0011`→`0012`→`0013` in exact sequence, no skips, no manual stamping, in
  under one second on this dataset (2 barbers, 4 services, 12 users, 5 appointments, 12 working
  schedules, 4 notifications, 0 schedule exceptions — the real production dataset, confirmed small,
  as §3/§10 always assumed but never verified until now).
- Every pre-existing row survived the jump with an identical count on the other side; the
  auto-created tenant/branch/subscription/owner-staff rows appeared exactly once, matching `0004`/
  `0007`/`0009`/`0010`'s backfill design.
- `python scripts/verify_production_migration.py` against the migrated, restored copy: 45/47 PASS,
  2 WARN (`telegram_bot_identities`/`platform_operators` both empty — expected and correct, since
  this production deployment predates bot-identity/platform-operator provisioning entirely and
  neither `python -m app.register_bot` nor `python -m app.bootstrap_platform_admin` has been run
  against it yet), 0 FAIL.
- No cross-tenant leakage, no orphaned `tenant_id`, the EXCLUDE booking constraint and the
  tenant-owner partial unique index both survived intact, `audit_log_entries.tenant_id` is nullable,
  and `tenants.default_language`/`staff_members.language` hold only supported values.

**What this does not change:** the disposable rehearsal container was removed immediately after
recording these results; the real production database was never written to, and the real bot was
never stopped, restarted, or pointed at anything other than what it already was. This rehearsal
proves the migration path and the backup/restore path both work against this deployment's actual
data — it does not itself perform the production cutover described in §5; that remains a separate,
deliberate action for the operator to schedule.

## 12. Incident record — accidental entrypoint-triggered production migration (2026-09-16)

**What happened:** during a preflight step intended to be read-only (inspecting a freshly built
image's own migration metadata via `docker compose run --rm bot alembic heads`), the container's
`ENTRYPOINT` (`docker-entrypoint.sh`) ran its unconditional `alembic upgrade head` first, using the
`bot` service's real production `DATABASE_URL`. Because the image being used had just been rebuilt
and contained migrations through `0013`, this actually executed the full `0003`→`0013` chain
against the real production database — before the intended `alembic heads` inspection ever ran.
This is the exact hazard now called out at the top of this document. No `alembic downgrade` was
attempted at any point; §9's guidance was followed throughout.

**Verified impact:** zero data loss — every pre-existing row count (`barbers=2`, `services=4`,
`users=12`, `appointments=5`, `working_schedules=12`, `schedule_exceptions=0`, `notifications=4`)
was confirmed identical before and after. The migration's own backfills produced exactly the
expected one tenant, one owner `staff_members` row, and one `legacy`-equivalent subscription. The
live bot container did not crash or restart during the incident itself — it continued running its
old, pre-`0004` build against the new schema for a window before being deliberately stopped as the
first recovery action, per the "stop the old build immediately" principle now reflected in §5.

**Recovery performed, in full, and independently verified at each step:**

1. Old bot stopped (`docker compose stop bot`), confirmed exited cleanly.
2. Fresh backup taken of the now-`0013` state (`./tools/backup.sh`) — gzip-integrity-verified,
   non-empty, its own `alembic_version` confirmed `0013`. The original pre-incident `0003` backup
   was preserved, not deleted.
3. Current revision re-confirmed as `0013` via read-only query; all core row counts re-confirmed
   unchanged.
4. The already-built new image was independently confirmed (via `--entrypoint` override with a
   dummy, non-production `DATABASE_URL`, and via `docker create`/`cp` file inspection — no
   production contact) to contain migrations `0001`-`0013`, `app/register_bot.py`, and
   `app/bootstrap_platform_admin.py`.
5. The single migrated tenant was identified by its actual returned UUID via a read-only query —
   never assumed or invented.
6. `python -m app.register_bot --tenant-id <that UUID>`, run via `--entrypoint python` (bypassing
   the auto-migration wrapper), succeeded; `telegram_bot_identities` verified to contain exactly one
   active row pointing at that tenant.
7. `ADMIN_ID` was confirmed present (by variable name only, value never printed); with it present,
   `python -m app.bootstrap_platform_admin`, run the same `--entrypoint python` way, succeeded;
   `platform_operators` verified to contain exactly one active `platform_admin` row.
8. The new bot was started (`docker compose up -d bot`); its entrypoint's own `alembic upgrade
   head` ran again but was a confirmed no-op (database already at `0013`); startup logs showed the
   bot validating its own token, the scheduler configuring 3 jobs for the 1 real tenant, and
   polling starting successfully — zero errors, zero exceptions, zero "unknown bot_id" rejection
   warnings in the logs at any point afterward.
9. **Not performed as part of this recovery: a real, human-operated Telegram smoke test.** The
   recovery confirmed the bot process is healthy, registered, and receiving no rejection warnings,
   but an actual `/start`/booking/`/admin` walkthrough by a human with a real Telegram client is
   still the outstanding, recommended next action and should not be skipped just because the
   automated checks above were clean.

**Why this must not recur:** the entrypoint's behavior itself was not changed (out of scope for
this documentation-only correction, and not something to fix by weakening `set -e`'s fail-closed
migration-on-start behavior for routine restarts) — the fix is procedural: every command in this
document that touches the `bot` service now either uses `--entrypoint` override, runs on the host,
uses `docker compose exec` against an already-running container, or is one of the two deliberate,
labeled points (§5 steps 5 and 11) where invoking the real entrypoint is intentional.
