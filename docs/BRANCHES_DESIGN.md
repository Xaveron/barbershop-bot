# Branches Design — Phase 3

## 1. Audit of the current model (before this phase)

Before this phase the domain was implicitly single-location per tenant: `Barber`, `Service`,
`WorkingSchedule`, `ScheduleException`, and `Appointment` all knew nothing about "where." A tenant
operating more than one physical shop had no way to represent it. `Tenant` already carried
`shop_address`/`shop_phone`/`timezone`/`currency` (Phase 1) as a stopgap "one location" model —
those columns become the seed data for each tenant's first `Branch` in this phase's migration, but
otherwise stay exactly as unused by business logic as they were before.

## 2. `Branch` and its associations

`Branch` (`app/database/models/branch.py`) is `TenantScopedMixin` + `UUIDPrimaryKeyMixin` +
`TimestampMixin`, matching every other tenant-owned entity's shape: `name`, `address`, `phone`,
`maps_url`, `timezone` (default `Europe/Chisinau`), `currency` (default `MDL`), `is_active`.
`UniqueConstraint(tenant_id, name)` — unique per tenant, not globally.

Three association tables, each following the same shape (`TenantScopedMixin` +
`UUIDPrimaryKeyMixin` + `TimestampMixin` — this codebase has no precedent for composite-PK tables;
every table has a surrogate UUID `id`, so these follow suit):

- **`barber_branches`** (`barber_id`, `branch_id`) — a barber may work at one or more branches.
  `UniqueConstraint(tenant_id, barber_id, branch_id)`.
- **`branch_services`** (`branch_id`, `service_id`, `is_active`) — **absence of a row means
  "available everywhere."** The migration backfill creates one row per existing branch×service
  pair with `is_active=true`, so nothing changes for today's tenants. A row with `is_active=false`
  is how an admin would later narrow a specific service out of a specific branch. New services
  created after this migration have no row for any branch — they read as "available everywhere"
  under the current default-permissive semantics, which is deliberate but worth remembering if
  that default is ever flipped. `UniqueConstraint(tenant_id, branch_id, service_id)`.
- **`staff_branches`** (`staff_member_id`, `branch_id`) — RBAC branch-scoping (§6).
  `UniqueConstraint(tenant_id, staff_member_id, branch_id)`.

`app/database/repositories/branch.py` (`BranchRepository(TenantScopedRepository)`) provides
`get`/`get_active`/`list_active`/`list_all`/`create` (same shape as `BarberRepository`), plus
`assign_barber`/`assign_service` (both return `None` — the established "belongs to tenant" guard
pattern, see §5 — if either id belongs to another tenant, rather than silently creating a
cross-tenant-referencing row), `barber_works_at_branch`, `service_available_at_branch`,
`list_for_barber`, and `accessible_branch_ids_for_staff`.

## 3. The two invariants this phase had to get right

**(1) The EXCLUDE constraint stays keyed on `barber_id` alone — never `(barber_id, branch_id)`.**
A barber is one physical person who cannot be in two places at once. Keying the constraint
(`excl_appointments_barber_no_overlap`) on `(barber_id, branch_id)` instead of `barber_id` alone
would *permit* the same barber to be double-booked across two branches at overlapping times — a
real bug, not a false positive. `Appointment.branch_id` is informational/filtering, validated at
the application layer (`barber_works_at_branch`), never folded into the physical overlap
constraint. `tests/test_integration_branches.py::test_double_booking_is_rejected_across_branches`
is the regression test for this.

**(2) A barber's *busy intervals* stay branch-agnostic; only their *working hours/exceptions*
become branch-scoped.** `AppointmentRepository.list_for_barber_between` (busy time for slot
computation) does **not** filter by `branch_id` — a barber's booked time anywhere blocks slots
everywhere, exactly like before this phase. Only `ScheduleRepository.list_week`/`list_exceptions`
(working *hours*) are branch-filtered, because hours genuinely differ per branch (a barber might
work 9–13 at branch A and 14–18 at branch B) while occupancy doesn't. Getting this backwards would
either reopen the double-booking hole in (1) or produce nonsensical availability.
`test_available_slots_differ_per_branch_for_same_barber` is the regression test for this.

## 4. Schema changes to existing tables

- `WorkingSchedule` gains `branch_id` (NOT NULL, FK `branches.id` CASCADE). Uniqueness becomes
  `uq_working_schedules_barber_id_branch_id_weekday (barber_id, branch_id, weekday)`.
- `ScheduleException` gains `branch_id` (**NOT NULL**). "Global" (`barber_id IS NULL`) now means
  "branch-wide," not "tenant-wide" — a genuinely multi-branch tenant's locations can have
  independent holidays/closures. Both partial unique indexes gain `branch_id`:
  `uq_schedule_exceptions_barber_date (tenant_id, branch_id, barber_id, exception_date) WHERE
  barber_id IS NOT NULL`, `uq_schedule_exceptions_global_date (tenant_id, branch_id,
  exception_date) WHERE barber_id IS NULL`.
- `Appointment` gains `branch_id` (NOT NULL, FK `branches.id` **RESTRICT** — matches
  `barber_id`/`service_id`'s RESTRICT; never actually blocks anything since branches are
  deactivated, never deleted). New index `ix_appointments_tenant_id_branch_id_starts_at` on
  `(tenant_id, branch_id, starts_at)`, mirroring the existing `ix_appointments_tenant_id_starts_at`
  — the natural next filter once branch-aware admin views exist.

## 5. Migration and backward compatibility

`0007_add_branches.py` (after `0006`): creates the 4 new tables; adds `branch_id` nullable to the
3 existing tables; **loops over every existing tenant row** (unlike `0004`, which only ever needed
one tenant), creating one default branch per tenant named "Основной филиал," sourced from that
tenant's own `shop_address`/`shop_phone`/`timezone`/`currency` columns; backfills that tenant's own
`working_schedules`/`schedule_exceptions`/`appointments` rows with its new branch id; populates
`barber_branches` (every existing barber → the new branch) and `branch_services` (every existing
service → the new branch) for that tenant. Then sets NOT NULL, adds FKs/indexes, swaps the
`WorkingSchedule`/`ScheduleException` uniqueness. Idempotent via `ON CONFLICT DO NOTHING` on the
branch insert (`tenant_id, name`) and the two association-table inserts, plus `WHERE branch_id IS
NULL` guards on the backfill `UPDATE`s. `downgrade()` reverses everything in dependency order.

Every currently-deployed (single-branch) tenant ends up with exactly one active branch after this
migration, and every barber/service/schedule/appointment row is correctly linked to it — from the
client's perspective, nothing changes (see §7).

The "belongs to tenant" guard pattern used throughout Phase 1/2
(`ScheduleRepository._barber_belongs_to_tenant`) is reused and extended here:
`_branch_belongs_to_tenant`, `_barber_works_at_branch`, `_barber_and_branch_valid` in
`ScheduleRepository`, and `BranchRepository._belongs_to_tenant`/`assign_barber`/`assign_service`.

## 6. Branch-scoped authorization — a 4th independent check

Extending §6 of `docs/RBAC_DESIGN.md`: branch scope is a 4th independent, composable check
alongside tenant isolation / role permission / resource ownership.
`AuthorizationService.can_access_branch(staff, branch_id, *, accessible_branch_ids, is_super_admin)`
is a pure `@staticmethod` like its three siblings — it takes an already-fetched set rather than
doing its own I/O, so the DB lookup (`BranchRepository.accessible_branch_ids_for_staff`) happens
once per handler at the call site, not buried inside the auth primitive. `TENANT_OWNER`/
`TENANT_ADMIN` (and the platform `SUPER_ADMIN`) return `True` immediately — they see every branch
of their tenant without a single `staff_branches` row; every other role needs an explicit row.

This phase delivers the primitive and its pattern (the same "inline check layered on top of the
router-level `RequirePermission`" pattern Phase 2's `reports.py`/`editing.py` already established),
but does **not** wire it into every branch-touching admin handler — `admin/schedule.py` doesn't yet
have a branch-picker UI to check the primitive against (see §9).

`Permission.MANAGE_BRANCHES` is the new permission gating branch CRUD
(`app/bot/handlers/admin/branches.py`). It has no backing Postgres enum column (only `Role` does),
so adding it needed no migration; `TENANT_OWNER`/`TENANT_ADMIN` get it automatically through their
existing `frozenset(Permission)`-based construction in `ROLE_PERMISSIONS`.

## 7. Client-facing UX: zero change for single-branch tenants

`BookingSG` gains a `branch` state before `service`. `render_branch_or_skip()` is the crux of the
"no UX change today" guarantee: if the tenant has 0 or 1 active branches, it silently stores that
branch in FSM state and proceeds straight to the service picker — no new screen, no new tap, for
every currently-deployed tenant. Only a tenant with 2+ active branches sees the new picker
(`branches_kb`, mirroring `services_kb`/`barbers_kb` exactly — 📍 emoji buttons, back to main menu).

`render_barbers` is filtered to barbers assigned to the chosen branch
(`BarberRepository.list_active_for_branch`, joining `barber_branches`) — showing an unbookable
barber and only failing at confirm time would be bad UX, and barber-branch assignment is core to
this phase. `render_services` filtering by `branch_services` is **deferred** (see §9) — the
default-everywhere backfill makes it a non-issue for any tenant that hasn't touched branch-service
assignment.

`_load_selection` resolves the branch alongside service/barber; `render_days`/`render_times`/
`choose_time` construct `ScheduleService(session, settings, tenant_id, branch.id)`;
`confirm_booking` passes `branch_id=branch.id` into `BookingService.create_appointment`. "Мои
записи" needs zero changes — an existing `Appointment` already carries its own `branch_id`.

A newly created barber (`admin/barbers.py`) is auto-assigned to the tenant's sole active branch
when there is exactly one — the same "no UX/behavior change for single-branch tenants" principle
applied to the admin side. A tenant that has actually created a second branch has no admin UI to
assign a new barber to a specific branch (see §9) and would need direct data access for that today.

## 8. Service-layer signature changes

`branch_id` is **not** a `dispatcher["branch_id"]` process-wide DI constant like `tenant_id` — a
tenant can have multiple branches, so which one applies is a per-booking decision, exactly like
`service_id`/`barber_id` (chosen in a flow, carried in FSM state, re-resolved from the DB before
use, never trusted as a bare value).

- `ScheduleService.__init__` gains a required `branch_id` (right after `tenant_id`). `self.tz`
  stays `settings.tz`, completely unchanged — `Branch.timezone` is written by the migration but not
  read by any business logic this phase, the same status `Tenant.timezone` already had.
- `BookingService.__init__` keeps its existing signature (`session, settings, tenant_id`) — it does
  **not** store `branch_id`, since `cancel_appointment`/`mark_no_show` operate on an
  already-branch-tagged row. `create_appointment` gains `branch_id` as a keyword parameter,
  validates `barber_works_at_branch` right after the existing `barber.get_active` check (raising
  `BookingError("error.barber_not_at_branch")` on failure — no row created), and builds its
  `ScheduleService` locally with that `branch_id`. `reschedule_appointment` (and the client/admin
  reschedule handlers in `app/bot/handlers/appointments.py`) build their local `ScheduleService`
  using `appointment.branch_id` — the branch never changes on reschedule.

## 9. Out of scope (explicit)

- `barber_services` ("this barber provides this service") — a separate dimension unrelated to
  branches, belongs to a different later phase. Any active barber can still perform any active
  service, unchanged.
- Admin UI to toggle `branch_services.is_active`, or to assign an existing/new barber to a specific
  branch — the tables, backfill, and read-path checks exist; no screen to edit them is built. In
  practice this means every barber created through the delivered UI ends up assigned to at most one
  branch (whichever is the tenant's sole active branch at creation time); the many-to-many
  `barber_branches` model itself supports more, reachable today only via direct repository calls
  (as the test suite does) or future admin UI.
  `admin/schedule.py` resolves "the branch" for a barber via `BranchRepository.list_for_barber`
  and uses the first result — correct for every barber reachable through the delivered UI, and a
  documented simplification for the (currently UI-unreachable) case of a barber linked to more than
  one branch. A full branch-picker UI for schedule/exceptions is the natural next increment.
- `render_services` branch-filtering in the client flow (deferred nice-to-have; default-permissive
  `branch_services` semantics make it a non-issue today).
- Per-branch timezone actually wired into scheduling/UTC-conversion logic (`Branch.timezone`
  exists and is populated, but not read by business logic — same status `Tenant.timezone` had).
- Branch-aware UI overhaul of `admin/schedule.py`/`admin/appointments.py` (branch picker before
  barber picker, branch column in appointment lists) — the authorization primitive (§6) and pattern
  are delivered; the full UI rewiring is the natural next increment, not required for this phase's
  schema/authorization/booking-correctness goals.
- Branches cannot be hard-deleted (deactivation only, `admin/branches.py`) — by design, to avoid
  orphaning history, not a gap.
- Billing, subscriptions, multi-bot, onboarding, Mini App, analytics, payments, UI redesign,
  Phase 4.

## 10. Tests

`tests/test_integration_branches.py` (new): branch isolation between tenants and IDOR on
`BranchRepository.get()`; `assign_barber`/`assign_service` reject a barber/branch/service belonging
to another tenant; `BookingService.create_appointment` rejects a barber not assigned to the given
branch (`error.barber_not_at_branch`, no `Appointment` row created); the double-booking-across-
branches regression (§3.1); the multi-branch-availability regression (§3.2).

Existing suites updated to satisfy the new NOT NULL `branch_id` columns:
`tests/test_integration_booking.py`, `tests/test_handlers_flow.py`, `tests/test_scheduler.py` —
every fixture that creates a `WorkingSchedule`/`ScheduleException`/`Appointment` now also creates a
`Branch` (and a `BarberBranch` link) and threads `branch_id` through. No existing test's assertions
changed in substance; one query-count budget
(`test_booking_keeps_query_count_bounded`) moved from `<= 10` to `<= 11` to account for the new
`barber_works_at_branch` check in `create_appointment`.
