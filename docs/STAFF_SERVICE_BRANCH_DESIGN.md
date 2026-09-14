# Staff / Service / Branch Relationships Design — Phase 4

## 1. Audit of the current model (before this phase)

Phase 3 shipped `Branch` and three association tables (`barber_branches`, `branch_services`,
`staff_branches`) but explicitly deferred wiring most of them into real behavior. Reading the code
directly (not assuming) surfaced the following before any Phase 4 change was made:

1. **`BranchRepository.service_available_at_branch` had a live semantics bug.** It returned
   `False` (unavailable) whenever no `branch_services` row existed at all, contradicting the
   model's own documented contract ("absence of a row means available everywhere"). The method was
   never called from anywhere in the codebase, so the bug never fired in practice. Fixed as part of
   this phase (§3).
2. **`barber_services` did not exist at all** — zero references anywhere in the code. Created fresh
   this phase (§3).
3. **`AuthorizationService.can_access_branch`/`BranchRepository.accessible_branch_ids_for_staff`**
   (built in Phase 3) were wired into zero handlers — branch-scoped RBAC was a documented-but-inert
   primitive. Wired into `admin/schedule.py` and `admin/appointments.py` this phase (§6).
4. **No admin UI existed** for assigning a barber to a branch, assigning staff to branches, or
   toggling a service's availability per branch. No staff list/management UI existed at all —
   `StaffMember` rows were only ever created by the Phase 2 migration seeding `ADMIN_ID`.
5. `admin/schedule.py`'s `_resolve_branch_for_barber` took `branches[0]` from a barber's assigned
   branches with a comment saying that was only safe because no UI could yet assign a barber to
   more than one branch — the concrete "one barber = one branch" assumption this phase removes.
6. Client `render_services`/`render_barbers` didn't filter by `branch_services`/(new)
   `barber_services` — Phase 3 explicitly deferred this.
7. `Appointment` had no `branch` relationship (unlike `barber`/`service`/`user`, all
   `lazy="joined"`), and virtually every timezone-sensitive computation used `Settings.tz` (a
   single global env var — effectively "server timezone"), never `Branch.timezone`/
   `Tenant.timezone`, despite those columns existing since Phase 1/3.
8. `admin/appointments.py` had zero branch-based access restriction — a `MANAGER`/`RECEPTIONIST`
   scoped to one branch could list/cancel/reschedule/no-show any appointment across the whole
   tenant.

## 2. `barber_services`: opt-out, matching `BranchService` — not strict membership

Absence of a `barber_services` row means the barber **can** perform the service — today's exact
behavior (any active barber can perform any active service; no restriction exists anywhere before
this phase). A row with `is_active=False` is an explicit admin opt-out for that one
(barber, service) pair.

This is a deliberate reading of "a barber can provide selected services," chosen over a literal
strict-membership model (absence = cannot perform) because strict membership would require
backfilling a full barber×service cross-product per tenant to avoid breaking every existing
tenant's booking flow on upgrade day, and would silently make every barber or service created
*after* the migration unbookable together until an admin manually wired up every combination.
Opt-out semantics need zero backfill — migration `0008` creates the table empty — and both new
barbers and new services keep working with each other with no admin action required, exactly like
before. `service_available_at_branch` and `BarberServiceRepository.barber_provides_service` share
one rule: "return `True` unless an explicit `is_active=False` row says otherwise."

No admin UI toggles `barber_services` this phase (see §9) — same status `branch_services` had
after Phase 3: table, backfill-free default, and server-side validation exist; the toggle screen
does not. The phase brief's admin-UX section only asked for branch toggles on barbers/staff/
services, not a barber↔service screen.

## 3. Migration `0008_add_barber_services.py`

Creates exactly one table, `barber_services` (`barber_id`, `service_id`, `is_active` default
`True`, `UniqueConstraint(tenant_id, barber_id, service_id)`, FKs CASCADE). No backfill loop — an
empty table is the correct starting state (§2). `downgrade()` drops the table. Does not touch
migration `0007`. No other schema changes were needed anywhere else: every `branch_id` column
required already existed from `0007`, and the new `Appointment.branch` relationship (§4) is
ORM-only.

## 4. Timezone: `Branch.tz`/`Tenant.tz`, and where `settings.tz` was actually replaced

`Branch` and `Tenant` both gained a `.tz -> ZoneInfo` computed property (mirroring the existing
`Settings.tz` property) — `ZoneInfo` handles DST transitions correctly by construction, so no
custom DST logic was needed, only routing the *right* zone to the *right* computation.
`Appointment` gained a `branch: Mapped[Branch] = relationship(lazy="joined")` (no migration — the
FK column already existed), and `AppointmentRepository._with_relations` now eager-loads it
alongside `user`/`barber`/`service`, so reading `appointment.branch.tz` never causes an extra
query.

`ScheduleService.__init__` now takes the resolved `Branch` object instead of a bare `branch_id`
(`ScheduleService(session, settings, tenant_id, branch)`) and sets `self.tz = branch.tz` — this is
the actual "wire `Branch.timezone` into scheduling" fix. Every call site already had the `Branch`
object in hand at construction time (client `booking.py`'s `_load_selection`; admin `schedule.py`'s
branch resolution, §6; `BookingService`, which now fetches the full `Branch` row via
`BranchRepository.get_active` — tightening the forged-callback story in the same motion, since a
bare bool check can't tell "branch doesn't exist" from "branch exists but barber isn't assigned to
it" apart, and now it does).

Timezone was fixed (replaced `settings.tz`) at every site that is either scheduling math or
formatting one specific appointment: `ScheduleService`; every `combine_local(day, time, tz)` that
turns a user's day+time pick into an absolute instant for booking/rescheduling (client
`booking.py::choose_time`, client `appointments.py`'s reschedule flow, admin `appointments.py`'s
single-appointment reschedule reuses the same client code); `appointment_card`/`appointment_line`
call sites (now pass `appointment.branch.tz`); `my_appointments_kb`/`admin_appointments_kb`, which
used to take one shared `tz` for a whole list of appointments that can now span branches with
different timezones — both now resolve `appointment.branch.tz` per row instead; `admin/schedule.py`'s
`today_in(settings.tz)` (exception-date validation) now uses the specific branch being edited.

**Deliberately left unchanged**: `app/services/stats.py`'s day/month boundary calculation and
`app/services/export.py`'s CSV timestamp formatting still use `settings.tz`. Both are tenant-wide,
cross-branch aggregates with no single "the branch" to resolve, and the phase brief explicitly
excludes analytics — stats.py is the closest thing to it in this codebase. Known limitation, not a
gap in the scheduling/booking-display fix this phase actually asked for.

## 5. Client booking flow: real branch+service+barber filtering

- `ServiceRepository.list_active_for_branch(branch_id)` (new): active services with no
  `branch_services` row OR an explicit `is_active=True` row (LEFT JOIN, opt-out). `render_services`
  uses this instead of the tenant-wide `list_active()`.
- `BarberRepository.list_active_for_branch_and_service(branch_id, service_id)` (new): INNER JOIN
  `barber_branches` (strict — barber must work at the branch) + LEFT JOIN `barber_services` with
  the opt-out exclusion. `render_barbers` uses this instead of the branch-only
  `list_active_for_branch`.
- `BookingService.create_appointment` gained two checks alongside the existing
  `barber_works_at_branch`: `service_available_at_branch` (now fixed, §1/§2) and a new
  `BarberServiceRepository.barber_provides_service`, each raising a distinct `BookingError`
  (`error.service_not_at_branch`, `error.barber_not_provide_service`) — closing every
  forged-callback combination the phase brief listed as must-fail. A fourth new check,
  `error.branch_unavailable`, covers a branch id that doesn't exist/isn't active at all (previously
  indistinguishable from "barber not at branch"). All checks are independent and all run
  server-side regardless of what the UI already filtered.

## 6. `admin/schedule.py`: real branch resolution instead of "take the first branch"

Barber picker → branch resolution (auto-skip if exactly one branch is both assigned to the barber
*and* accessible to the acting staff member, mirroring the client flow's own Phase 3 "auto-skip
when singular" pattern — zero extra taps for every currently-deployed single-branch tenant) →
branch picker only when more than one candidate remains → week view. Since Telegram's 64-byte
callback_data limit rules out encoding `barber_id|branch_id|weekday` together, `barber_id` and
`branch_id` are carried in FSM state for the rest of that schedule-editing session once resolved,
the same way client `booking.py` already carries `branch_id`/`service_id`/`barber_id`. Every
downstream handler (weekday view, set-hours, day-off) reads them back from `state.get_data()`
instead of re-deriving. `save_hours` deliberately does not `state.clear()` the barber/branch
context after saving — only the transient hours-input state — so setting hours for a second
weekday in the same session doesn't require re-picking the barber and branch.

The exceptions flow got the equivalent treatment: picking "a specific barber" or "the whole
branch" now also resolves/asks for a branch (mirroring the schedule flow's picker exactly) before
asking for a date, and `_save_exception` reads `branch_id` straight from FSM state instead of the
old single-branch-only `_resolve_branch_for_barber`/`_resolve_default_branch` helpers (both
deleted — no longer needed). The "🏠 Весь барбершоп" button label was also fixed to "🏠 Весь
филиал": Phase 3 already redefined a NULL-`barber_id` `ScheduleException` as branch-wide rather
than tenant-wide, but never updated this label to match — a small but real audit finding.

A forged `AdmDayCB`/`sch_set`/`sch_off` callback referencing a barber who doesn't actually work at
the `branch_id` held in FSM state is rejected by the existing `ScheduleRepository`
guards (`_barber_and_branch_valid`), unchanged from Phase 3 — no additional per-action branch check
was needed on top of that, since `branch_id` itself lives server-side in FSM state (not
client-forgeable) and is validated once, when it's chosen.

## 7. RBAC branch-scope enforcement: `admin/schedule.py` and `admin/appointments.py` only

`AuthorizationService.can_access_branch` needs an already-fetched accessible-branch-id set as
input by design (Phase 3) — `resolve_accessible_branch_ids(session, tenant_id, staff, *,
is_super_admin)` (new, `app/services/authorization.py`) is the one function that does that I/O:
returns `None` for `TENANT_OWNER`/`TENANT_ADMIN`/platform `SUPER_ADMIN` (meaning "unrestricted,"
distinct from an empty `frozenset()` meaning "assigned to nothing"), else the staff member's real
`staff_branches` set.

Wired into:
- `admin/schedule.py`: the branch candidates offered when resolving a barber's schedule/exceptions
  are filtered to this set (§6).
- `admin/appointments.py`: `AppointmentRepository.list_between`/`count_between` gained an optional
  `branch_ids` filter (`None` = unrestricted); the listing and bulk-cancel-by-day handlers pass the
  staff's accessible set when scoped; every per-appointment action (view/cancel/no-show/move)
  checks the target appointment's own `branch_id` against it before acting.

**Deliberately not wired into** `admin/barbers.py`/`admin/services.py` — their listings stay
tenant-wide. Barbers and services are tenant-owned resources that merely *have* per-branch
associations (a barber can belong to several branches at once, some accessible to a given manager
and some not — there's no unambiguous single answer for "can this manager edit this barber" once
that's true), not branch-owned resources themselves. Restricting those lists would be a separate,
ambiguous design problem the phase brief doesn't resolve, and risked turning into the "redesign the
entire admin interface" the brief explicitly said not to do.

## 8. Minimal admin UX additions

- **Barber ↔ branch** (extends the existing barber card in `admin/barbers.py`): a "📍 Филиалы"
  button → list of the tenant's branches with an assign/remove toggle per branch. Removing a
  barber's *last* branch is blocked (a barber with zero branches can't be scheduled or booked at
  all).
- **Service ↔ branch** (extends the existing service card in `admin/services.py`): a "📍 Филиалы"
  button → list of branches with an enable/disable toggle per branch, using the now-fixed
  `service_available_at_branch` for display. No "last branch" guard — a service disabled
  everywhere is just an unusually-configured service, not a broken one.
- **Staff ↔ branch** (new file `app/bot/handlers/admin/staff.py` — no staff admin UI existed at
  all before this phase): a "🧑‍💼 Сотрудники" entry in the admin menu → list of `StaffMember` rows
  → a staff card showing role +, for `MANAGER`/`RECEPTIONIST`/`BARBER` only (`TENANT_OWNER`/
  `TENANT_ADMIN` implicitly have every branch, no toggle list shown), a branch assign/remove toggle
  list with the same last-branch guard as barbers. Router-level filter `RequirePermission(VIEW_STAFF)`
  (so `MANAGER`, who has `VIEW_STAFF` but not `MANAGE_STAFF`, can see the list/cards), with an
  inline `AuthorizationService.require(staff, MANAGE_STAFF, ...)` check on the actual
  assign/remove-branch mutation — the same "weaker router filter + stronger inline check on the
  mutating action" pattern already used in `admin/reports.py`'s `export_csv` and
  `admin/editing.py`'s `apply_field_edit` from Phase 2. No staff creation or role-editing UI — out
  of scope; that's staff onboarding, not staff/branch relationships, and none existed before this
  phase either.

Both barber-branch and staff-branch toggle handlers carry the "which barber/staff" context in FSM
state (set once when entering the branch-list screen) rather than in callback_data, since a
`staff_id|branch_id` or `barber_id|branch_id` pair doesn't fit Telegram's 64-byte callback limit —
the same technique as §6.

## 9. Out of scope (explicit, matches the phase brief)

Billing, subscriptions, payments, multi-bot, onboarding, Mini App, SaaS dashboard, analytics,
staff creation/role-editing UI, an admin screen to toggle `barber_services` (server-side validation
and the opt-out table exist; no UI does, matching `branch_services`'s post-Phase-3 status),
branch-restricting `admin/barbers.py`/`admin/services.py` listings, per-branch timezone in
`stats.py`/`export.py`, Phase 5.

## 10. Tests

New `tests/test_integration_staff_service_branch.py` (existing `tests/test_integration_branches.py`
stays as the Phase 3 regression baseline, updated only where the `ScheduleService` signature change
required it — bare `branch_id` UUIDs became resolved `Branch` objects): barber/staff assigned to
multiple branches; the `service_available_at_branch` bug-fix regression (no row → available);
`barber_services` opt-out behavior plus the cross-tenant "belongs to tenant" guard rejection; the
three-way booking validation (branch+service+barber-provides, each failing independently); `MANAGER`/
`RECEPTIONIST` branch restriction on appointment listing/actions and on schedule/exception branch
resolution; branch timezone actually changing computed slot times; a DST-boundary regression
(Europe/Chisinau's last-Sunday-of-March/October transitions). Full existing suite must keep passing
unmodified in substance (only the mechanical `ScheduleService` call-site fixes and one query-count
budget change — see below — touch existing test files).

`test_booking_keeps_query_count_bounded` (Phase 3) moved from `<= 11` to `<= 14` to account for the
three new server-side checks in `create_appointment` (branch fetch, service-at-branch,
barber-provides-service).

## 11. Known limitations

- No admin UI for `barber_services` (§2/§9) — reachable only via direct repository calls today,
  same status `branch_services` had immediately after Phase 3.
- `admin/schedule.py` navigating "back" from the weekday-actions screen to the week view
  re-resolves the branch from scratch, which re-prompts the branch picker for a barber with more
  than one accessible branch (rather than remembering the just-picked one). Correct and secure,
  just not maximally smooth — acceptable for a first cut per the phase's "minimal admin flows,
  no full redesign" instruction.
- `stats.py`/`export.py` still use `settings.tz` (§4).
- Per-branch timezone is now read by scheduling and appointment display, but nothing yet lets an
  admin *change* a branch's timezone after creation through the bot UI (`admin/branches.py`'s
  field-edit list doesn't include `timezone`) — only `BranchRepository.create` sets it (defaulting
  to the tenant's own timezone). Editing it today requires direct data access. Not required by the
  phase brief, noted for completeness.
