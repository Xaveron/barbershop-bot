# Tenant Isolation Audit — Phase 1

**Scope:** full codebase (`app/`, `tests/`, `tools/`), not limited to files changed in Phase 1.
**Method:** manual review of every repository/service/handler that touches tenant-owned data,
grep-based sweeps for risky patterns (`session.get(`, bulk `update(`, `session.delete(`,
`.join(`, raw `text()` SQL, any place `tenant_id` is assigned), two independent fresh-eyes
reviews (one on the migration specifically, one hunting for the "unchecked foreign-id write"
bug class across all repositories and handlers), and empirical verification: migration applied
to a disposable database, downgraded, re-upgraded, plus the full test suite (255 tests) run
against it. **The production database was not touched at any point during this audit.**

**Outcome:** 3 real gaps found and fixed (2 MEDIUM-severity cross-tenant write risks, 1 MEDIUM
cross-tenant read risk in the notification scheduler), 1 MEDIUM model/migration drift issue
fixed, 1 LOW operational note logged (not fixed — see rationale). Every other checklist item
passes. Regression tests were added for all three fixed gaps.

---

## Checklist summary

| # | Item | Status |
|---|---|---|
| 1 | Every tenant-owned SELECT has tenant scoping | ✅ PASS |
| 2 | Every UPDATE has tenant scoping | ✅ PASS |
| 3 | Every DELETE has tenant scoping | ✅ PASS |
| 4 | Every point lookup avoids unsafe `session.get()` | ✅ PASS (already fixed in Phase 1) |
| 5 | No repository can be instantiated without `tenant_id` | ✅ PASS |
| 6 | No service can access tenant-owned data without tenant context | ✅ PASS |
| 7 | No handler can pass a Telegram-user-supplied `tenant_id` | ✅ PASS |
| 8 | No UUID from callback data can reach another tenant's object | ⚠️ **FAIL → FIXED** (2 sites) |
| 9 | Booking creation/cancellation remain tenant-scoped | ✅ PASS |
| 10 | Scheduler jobs are tenant-scoped | ⚠️ **FAIL → FIXED** (1 site) |
| 11 | Background tasks cannot lose TenantContext | ✅ PASS (after fix to #10) |
| 12 | DB constraints remain correct after migration | ✅ PASS |
| 13 | All migrations are reversible | ✅ PASS |
| 14 | Production data migration/backfill is safe | ✅ PASS, 1 LOW operational note |
| 15 | No cross-tenant joins that leak data | ✅ PASS (1 MEDIUM drift issue, unrelated to joins, fixed) |

---

## FAIL items (fixed)

### F1 — `ScheduleRepository.set_day()` created cross-tenant-referencing rows — **MEDIUM**

**Files/functions:** `app/database/repositories/schedule.py:33` (`set_day`), reached from
`app/bot/handlers/admin/schedule.py:128` (`save_hours`) via FSM state populated in `ask_hours`
(`_parse_barber_weekday`, line 362).

**What was wrong:** `set_day(barber_id, weekday, start, end)` looked up an existing
`WorkingSchedule` by `(tenant_id=self.tenant_id, barber_id, weekday)`. If none existed, it
**created** a new one with `tenant_id=self.tenant_id, barber_id=barber_id` — without ever
checking that `barber_id` actually belongs to `self.tenant_id`. "No row found" is
indistinguishable from "this barber isn't mine" in that query, so a `barber_id` belonging to a
different tenant would silently produce a `WorkingSchedule` row pointing at a foreign tenant's
barber. `barber_id` reaches this method from `callback_data`/FSM state — a value that, while
gated behind `IsAdmin`, is still attacker-shaped input from a Telegram update, not a value the
server derived itself. Contrast with `BookingService.create_appointment`
(`app/services/booking.py:108-113`), which calls `self.barbers.get_active(barber_id)` — a
tenant-scoped lookup — and rejects on `None` *before* using the id further. `set_day` had no
equivalent gate.

**Exploitability today:** low — requires an authenticated admin of the one existing tenant to
forge `callback_data` referencing another tenant's barber UUID, and Phase 1 has exactly one
tenant in production, so there is no second tenant's barber to target yet. The finding matters
because this exact code path becomes exploitable the moment a second tenant exists in the same
database, which is precisely what this audit was commissioned to catch before Phase 2 builds on
top of it.

**Fix applied:** added `ScheduleRepository._barber_belongs_to_tenant()` and made `set_day()`
return `None` (instead of creating a row) when the barber isn't owned by `self.tenant_id`.
Updated `save_hours` to treat `None` as "Барбер не найден." — the exact same message this file
already shows for the analogous failure in `show_week`/`show_weekday`, so this is not a UX
change, just closing a code path that previously had no defined behavior for this case.

**Test added:** `tests/test_integration_booking.py::test_schedule_set_day_rejects_barber_from_another_tenant`.

### F2 — `ScheduleRepository.upsert_exception()` — same bug class — **MEDIUM**

**Files/functions:** `app/database/repositories/schedule.py:94` (`upsert_exception`), reached
from `app/bot/handlers/admin/schedule.py:387` (`_save_exception`) via `scope` stored in FSM
state from `add_exception_pick_date` (line 245).

Identical shape to F1: `_find_exception(barber_id, exception_date)` can't distinguish "no
exception yet for my barber" from "not my barber", so it would create a
`ScheduleException(tenant_id=self.tenant_id, barber_id=<foreign>)`.

**Fix applied:** same guard (`_barber_belongs_to_tenant`) added to `upsert_exception()`,
returning `None` on ownership failure. `_save_exception()` now treats `None` as failure
(already-existing "Не удалось сохранить исключение." wording — no UX change).

**Test added:** `tests/test_integration_booking.py::test_schedule_upsert_exception_rejects_barber_from_another_tenant`.

**Confirmed NOT present elsewhere:** an independent pass over every repository `.create()`/
`.set_*()`/`.upsert_*()`/`.schedule()` method and every handler write site (barbers, services,
appointments, notifications) found no other instance of this pattern — every other write either
takes no externally-supplied foreign id, or already validates it via a tenant-scoped `get()`/
`get_active()` before use (e.g. `NotificationRepository.schedule()` takes a raw
`appointment_id` with no internal check, but its only caller,
`BookingService._plan_reminders`, always passes an id that was already resolved through a
tenant-scoped path).

### F3 — `NotificationRepository.list_due()` was not tenant-scoped — **MEDIUM**

**Files/functions:** `app/database/repositories/notification.py:73` (`list_due`), called from
`app/services/notifications.py:69` (`NotificationService.dispatch_due`), itself invoked by the
scheduler job `app/scheduler/jobs.py:send_due_reminders` (which already receives `tenant_id`).

**What was wrong:** `notifications` intentionally has no `tenant_id` column (design decision:
it's reached only via `appointment_id`, already tenant-consistent, for every method *except*
this one). `list_due()` is different — it's a system-wide "what's due right now" scan with no
already-known appointment to anchor on, so the "reached via a tenant-scoped appointment"
reasoning didn't actually apply to it. It selected due notifications across **every** tenant.
`NotificationService.dispatch_due()` would then process all of them using the *one* configured
bot/token/settings (shop name, address, timezone, language) — meaning a due notification
belonging to a different tenant would be sent, using this tenant's bot, with this tenant's shop
details baked into the message text, to that other tenant's real Telegram user.

**Exploitability today:** dormant, same reasoning as F1/F2 — one tenant exists in production
today. Becomes a real cross-tenant data leak (wrong shop name/address delivered to a real
customer under someone else's brand) the moment a second tenant row exists.

**Fix applied:** `list_due()` now takes a required `tenant_id` parameter and filters on
`Appointment.tenant_id == tenant_id` (via the join already present for the `Appointment` status
checks). `dispatch_due()` passes `self.tenant_id` (already available — `NotificationService`
already required `tenant_id` from the Phase 1 work).

**Test added:** `tests/test_integration_booking.py::test_notification_list_due_is_scoped_to_tenant`.

---

## Other fix (not a FAIL, but corrected while auditing)

### Model/migration default drift on `Tenant.timezone` / `Tenant.currency` — **MEDIUM**

**File:** `app/database/models/tenant.py`.

An independent review of the migration noticed that `0004_add_tenants.py` creates
`tenants.timezone`/`tenants.currency` with a `server_default`, but the ORM model only declared a
Python-side `default=`. `app/database/migrations/env.py` runs with `compare_server_default=True`,
so a future `alembic revision --autogenerate` would see this as drift and generate a spurious
migration attempting to drop the server defaults it thinks shouldn't be there. Not a tenant
isolation bug, but exactly the kind of thing that causes a bad autogenerated migration to slip
into a later PR unnoticed. **Fixed** by adding matching `server_default` values to the model
columns — no migration change needed since the database already has the correct defaults.

---

## WARNINGS (logged, not fixed)

### W1 — Migration 0004 holds locks for its full duration — **LOW**

`env.py` runs the whole migration in one transaction, so the `ACCESS EXCLUSIVE` lock each
`op.add_column`/`op.create_foreign_key` takes is held until the entire migration commits — across
all 6 tables' backfills and every constraint/index rebuild, not released incrementally per table.
On a large production table this would be a real availability window. **Not changed**, because:
splitting into per-table transactions would reduce lock time but introduce a worse failure mode
(a mid-migration crash could leave the schema half-migrated, needing manual cleanup instead of a
clean automatic rollback), and at this project's actual scale (one small barbershop's data) the
lock duration in practice is milliseconds. Worth revisiting if/when a tenant's table sizes grow
large enough for this to matter, or before a phase that does this kind of migration against a
much bigger dataset.

### W2 — No DB-level constraint ties `appointments.tenant_id`/`working_schedules.tenant_id`/etc. to their referenced barber's/service's own `tenant_id` — **LOW**

Every write path that matters is now application-verified (F1/F2 closed the two gaps that
weren't), but there is no composite foreign key or trigger that would make the *database itself*
reject a row where, say, `appointment.tenant_id != barber.tenant_id` for the referenced barber.
Today this can't happen because every code path that creates such a row goes through a
tenant-scoped lookup first. This is a "belt" without a second "suspenders" — acceptable for
Phase 1 given the application-layer guarantee is now complete and tested, but worth considering
for Phase 2 if new write paths are added, since a composite FK would make this class of bug
structurally impossible rather than a matter of code review discipline.

---

## PASS items — detail

- **#1/#2/#3 (SELECT/UPDATE/DELETE scoping):** every method in
  `AppointmentRepository`, `ServiceRepository`, `BarberRepository`, `UserRepository`,
  `ScheduleRepository` filters by `self.tenant_id`, including the one bulk `UPDATE`
  (`AppointmentRepository.mark_past_as_completed`) and every `session.delete()` call (each
  preceded by a tenant-scoped `get()` in its caller). `NotificationRepository`'s `DELETE`
  (`drop_pending`) and its two `INSERT` helpers are scoped indirectly via `appointment_id`,
  which is always sourced from an already tenant-verified `Appointment` (confirmed by the
  independent handler sweep, see F2's "confirmed not present elsewhere" note).
- **#4 (`session.get()`):** grep across `app/` confirms zero remaining calls to
  `session.get(<TenantOwnedModel>, id)` outside of code comments explaining why it was replaced.
  All tenant-scoped `.get()` methods use `select().where(id ==, tenant_id ==)`.
- **#5 (can't instantiate without tenant_id):** `TenantScopedRepository.__init__(self, session,
  tenant_id)` — `tenant_id` is a required positional parameter; Python itself raises `TypeError`
  if a caller omits it. Grep confirms no repository is constructed with only `(session)` except
  `NotificationRepository` and `TenantRepository`, both intentionally on plain `BaseRepository`
  (see design decision 6 in the Phase 1 plan).
- **#6 (services require tenant context):** `BookingService`, `ScheduleService`, `StatsService`,
  `ExportService`, `NotificationService` all require `tenant_id` in `__init__`.
- **#7 (tenant_id never from the user):** `tenant_id` is assigned exactly once in the whole
  codebase from live data — `app/bot/middlewares/user.py:33`, `tenant_id = data["tenant_id"]` —
  which is populated once at process startup (`app/main.py`, from `resolve_default_tenant_id()`,
  a DB query with no user input involved) and merged into every update's DI data by aiogram.
  Grep confirms no handler parses `tenant_id` out of `callback_data`, FSM state, or any other
  Telegram-supplied value.
- **#9 (booking tenant-scoped):** `create_appointment`/`cancel_appointment`/
  `reschedule_appointment`/`mark_no_show` all operate through `self.appointments`/`self.barbers`/
  `self.services` (tenant-scoped repos); ownership checks (`appointment.user_id != user.id`) are
  layered on top for client-initiated actions.
- **#10/#11 (scheduler + background tasks), after F3:** `send_due_reminders`,
  `schedule_return_reminders`, `complete_past_appointments` (`app/scheduler/jobs.py`) all receive
  `tenant_id` from `build_scheduler()` (`app/scheduler/setup.py`), itself given the one
  process-wide `tenant_id` resolved at startup — the same value used everywhere else, so a
  background job can't end up with a different or missing tenant context than the rest of the
  process.
- **#12/#13 (constraints/reversibility):** verified both by static comparison (every
  `op.drop_constraint`/`op.drop_index` name in `0004` matches the actual name created in `0001`,
  confirmed against `NAMING_CONVENTION` in `app/database/base.py`) and empirically — applied
  0001→0004 on a disposable database, ran the full test suite, downgraded 0004, re-upgraded,
  re-ran the full suite: identical result (single tenant row, 255/255 tests passing) both times.
- **#14 (backfill safety):** the nullable-add → `UPDATE` → `NOT NULL` → FK → index sequence runs
  inside Alembic's single transaction, so no writer can race the backfill and insert a `NULL`
  `tenant_id` row mid-migration. `TENANT_OWNED_TABLES` is a hardcoded literal tuple (confirmed,
  not derived from any input), so the f-string used to build the per-table `UPDATE` statement is
  not an injection risk.
- **#15 (cross-tenant joins):** every `.join()` in the repository layer starts from an
  already-tenant-filtered anchor table (`Appointment.tenant_id == self.tenant_id` before joining
  to `Service`/`Barber`/`User` for `top_services`/`top_barbers`/`list_for_export`), so the joined
  rows can't belong to another tenant as long as the data itself is consistent — which F1/F2 now
  guarantee at the write side too.

---

## Changed files

- `app/database/repositories/schedule.py` — added `_barber_belongs_to_tenant`, guarded
  `set_day`/`upsert_exception` (F1, F2)
- `app/bot/handlers/admin/schedule.py` — handle the new `None` return from `set_day`/
  `upsert_exception` (F1, F2)
- `app/database/repositories/notification.py` — `list_due()` now requires `tenant_id` (F3)
- `app/services/notifications.py` — `dispatch_due()` passes `self.tenant_id` to `list_due()` (F3)
- `app/database/models/tenant.py` — added `server_default` to `timezone`/`currency` (drift fix)
- `tests/test_integration_booking.py` — 3 new regression tests (see below)

## New tests

1. `test_schedule_set_day_rejects_barber_from_another_tenant`
2. `test_schedule_upsert_exception_rejects_barber_from_another_tenant`
3. `test_notification_list_due_is_scoped_to_tenant`

## Test count and result

255 tests passed (was 252 before this audit), 0 failed, applied against a disposable database on
the same Postgres instance — **the production database was never modified**. Migration chain
0001→0004 applied cleanly, downgraded and re-upgraded cleanly, full suite re-passed after each
step. `ruff check app/ tests/` — clean.
