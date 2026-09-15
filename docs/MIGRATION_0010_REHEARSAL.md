# Migration 0010 Rehearsal — Phase 6.5

Record of the rehearsals actually run for this phase. Everything below happened on disposable
scratch databases (`phase65_fresh`, `phase65_legacy_prod`) created on the same development
Postgres server as the real `barbershop` database, and both were dropped at the end. **The real
`barbershop` database was never written to.** No real production backup was available in this
environment, so §2 below is a *reconstructed* approximation of "production at `0003`," not an
actual restored backup — running this same sequence against a genuine restored production backup
is still required before the real cutover (see `docs/PRODUCTION_MIGRATION_RUNBOOK.md` §2.5).

## 1. Fresh database, `0001` → `0010`

```
CREATE DATABASE phase65_fresh OWNER barber;
DATABASE_URL=postgresql+asyncpg://barber:barber@localhost:5432/phase65_fresh alembic upgrade head
```

Result: all ten migrations applied cleanly in sequence (`<base>→0001→...→0010`), no errors.

```
python scripts/verify_migration_0010.py
```
→ **33/33 checks passed** (every table, the EXCLUDE constraint, the owner-uniqueness index, the
billing catalog and backfill shape, and zero cross-tenant leakage — trivially true here since only
the one bootstrap tenant from `0004`'s own seed exists).

```
pytest -q
```
→ **405 passed** (356 pre-existing + 49 from Phase 6's own billing suite — same count Phase 6
finished on).

```
ruff check app tests scripts
```
→ clean.

## 2. Realistic "production at 0003" database, migrated to `0010`

A second scratch database, `phase65_legacy_prod`, was migrated to **`0003` only** (`alembic
upgrade 0003`), then seeded directly with raw SQL matching that exact pre-multi-tenancy schema (no
`tenant_id`/`branch_id` anywhere — those columns don't exist yet at `0003`): 3 barbers (one
inactive), 4 services, a Mon–Sat 10:00–19:00 weekly schedule for both active barbers, one
schedule exception (a day off), 5 customers, 7 appointments spanning every status
(`confirmed`/`completed`/`cancelled`/`no_show`), and 3 pending reminder notifications. This is the
closest available proxy for what a live single-shop deployment sitting at `0003` plausibly looks
like.

**Before counts:**

| table | count |
|---|---|
| barbers | 3 |
| services | 4 |
| users | 5 |
| working_schedules | 12 |
| schedule_exceptions | 1 |
| appointments | 7 (confirmed 3, completed 2, cancelled 1, no_show 1) |
| notifications | 3 |

**The actual jump being rehearsed**, run with realistic shop environment variables set
(`SHOP_NAME`, `SHOP_ADDRESS`, `SHOP_PHONE`) to demonstrate migration `0004`'s dependency on
`get_settings()` at migration-run time:

```
DATABASE_URL=postgresql+asyncpg://barber:barber@localhost:5432/phase65_legacy_prod \
SHOP_NAME="Barbu Shop" SHOP_ADDRESS="ул. Тестовая 1" SHOP_PHONE="+373 60 000 000" \
alembic upgrade head
```

Result: `0003 → 0004 → 0005 → 0006 → 0007 → 0008 → 0009 → 0010`, **completed in under 2 seconds**
(`real 0m1.981s`) on this dataset. This is a real timing on real (if small) relational data, not a
theoretical estimate — but it does not by itself prove anything about a dataset orders of magnitude
larger; see the runbook's §3 for the per-migration lock analysis this timing supports.

**After counts** (identical — nothing lost):

| table | count |
|---|---|
| barbers | 3 |
| services | 4 |
| users | 5 |
| working_schedules | 12 |
| schedule_exceptions | 1 |
| appointments | 7 (confirmed 3, completed 2, cancelled 1, no_show 1) |
| notifications | 3 |

**Tenant/billing shape after migration:**

```
    name    |  slug   |  plan  | status | branches | barber_branch_links
------------+---------+--------+--------+----------+---------------------
 Barbu Shop | default | legacy | active |        1 |                   3
```

The one bootstrap tenant landed on `legacy`/`active` (every limit unlimited, all four features
enabled), got exactly one auto-created branch, and all three barbers (including the inactive one)
were linked to it — matching migration `0007`'s backfill exactly. The seeded `SHOP_NAME`/
`SHOP_ADDRESS`/`SHOP_PHONE` environment variables were correctly read into `tenants.shop_name`/
`shop_address`/`shop_phone` — confirming the runbook's warning that this migration must be run with
the real production environment loaded.

```
python scripts/verify_migration_0010.py
```
→ **33/33 checks passed.**

```
pytest -q
```
→ **405 passed.**

## 3. Application-level smoke test against the migrated realistic data

Beyond the automated suite, this phase directly exercised the same startup path
`app/main.py::run()` uses, then a full booking cycle, against `phase65_legacy_prod` post-migration:

- `resolve_default_tenant_id()` (the exact function the real bot calls at startup) resolved the
  bootstrap tenant without error.
- The pre-existing branch/barber/service/customer rows (created before the migration, under the
  old schema) loaded correctly through the current ORM models.
- `EntitlementService.has_feature()` returned `True` for all four features and
  `LimitService.get_limit()` returned `None` (unlimited) for all five limits — the Legacy plan
  behaving exactly as designed for a pre-existing tenant.
- A brand-new appointment was created end-to-end through `BookingService.create_appointment` on
  this migrated data.
- A second booking attempt on the identical slot was correctly rejected with
  `SlotUnavailableError` — the double-booking `EXCLUDE` constraint and advisory-lock path are
  intact after the full `0003→0010` jump.

## 4. Cleanup and final production check

```
DROP DATABASE phase65_fresh;
DROP DATABASE phase65_legacy_prod;
```

Both scratch databases were dropped. The real `barbershop` database was re-checked read-only
immediately afterward:

```
SELECT version_num FROM alembic_version;   -- 0003, unchanged
\l                                          -- database list unchanged, no phase65_* databases present
```

## 5. What this rehearsal does not prove

- Real production row counts and their effect on lock duration — this dataset is small by design.
- That a genuine `pg_dump`/restore cycle works against the real production data (no real backup was
  available in this environment).
- Anything about the actual currently-deployed bot build's behavior — it was never inspected
  directly in this phase (see the runbook's inference about it in §10 of
  `docs/PRODUCTION_MIGRATION_RUNBOOK.md`).

These are exactly the gaps `docs/PRODUCTION_MIGRATION_RUNBOOK.md` §2.5 asks the operator to close
by re-running this same sequence against a real restored backup before the actual cutover.
