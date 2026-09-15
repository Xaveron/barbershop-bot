# Tenant Onboarding Design — Phase 5

## 1. Current bootstrap model (before this phase)

Every tenant that has ever existed in this codebase got there through a one-time **migration-time**
data seed, not a runtime action:

- Migration `0004_add_tenants.py` unconditionally inserts exactly one `Tenant` row (from
  `Settings.shop_name`/`timezone`/`default_currency`) the first time the migration chain runs
  against a database.
- Migration `0005_add_staff_rbac.py` unconditionally maps every id in `ADMIN_ID` into a
  `StaffMember` row for that one tenant (`TENANT_OWNER` for the first id, `TENANT_ADMIN` for the
  rest).
- `app/database/tenants.py::resolve_default_tenant_id`, called exactly once at bot startup
  (`app/main.py`), reads `TenantRepository.get_default()` (the oldest tenant by `created_at`) and
  — before this phase — **raised `RuntimeError`** if none existed, treating "zero tenants" as a
  fatal misconfiguration rather than a state to recover from.
- Branches, services, staff, and schedules for that tenant then had to be built one at a time
  through the admin panel (`admin/branches.py`, `admin/services.py`, `admin/barbers.py`,
  `admin/schedule.py`, `admin/staff.py` — all complete as of Phase 4). There was no guided,
  sequenced flow, no way to tell "still being configured" apart from "serving real customers," and
  nothing stopped a half-configured tenant from answering `/start` exactly like a fully-configured
  one.

This is why "create a tenant without SQL" was still an open problem going into Phase 5, even though
every *piece* needed to configure one already existed.

## 2. Target onboarding model

Phase 5 does not change how many tenants one bot process serves — still exactly one, resolved once
at startup (`app/main.py`'s `tenant_id = await resolve_default_tenant_id(session_factory,
settings)`). What changes:

- `Tenant` gains an explicit `status` (§3), so "still being set up" is a real, queryable fact
  instead of an assumption.
- `resolve_default_tenant_id` gains a `settings` parameter and, when it finds zero tenants, now
  **creates one** (via `TenantOnboardingService.create_tenant`, seeded the same way migration
  `0004` seeds one) with `status=ONBOARDING` instead of raising. Zero-tenant is now a recoverable
  starting state, not a fatal one — the literal "new tenant can be created without manually
  inserting rows into PostgreSQL" requirement, exercised at the one place a tenant's absence is
  actually detected today.
- A new `TenantOnboardingService` (`app/services/onboarding.py`) provides the reusable,
  tenant-id-parameterized operations onboarding needs: readiness validation, owner creation,
  activation, and tenant creation itself — built entirely on repositories/services that already
  existed (`BranchRepository`, `ServiceRepository`, `BarberRepository`, `ScheduleRepository`,
  and `StaffService.create_staff`, written in Phase 2 and never wired to any handler until now).
- A minimal Telegram wizard (`app/bot/handlers/onboarding.py`) sequences those existing
  capabilities — it does not duplicate them. Creating the first branch still goes through
  `BranchRepository.create`; creating the first service still goes through
  `ServiceRepository.create`; and so on.
- `cmd_start` (`app/bot/handlers/common.py`) is the single place that branches on tenant status,
  so every other handler keeps assuming "the tenant I'm scoped to is real and open for business" —
  exactly as before.

## 3. Tenant lifecycle / state

New `TenantStatus` enum (`app/database/models/tenant.py`): `ONBOARDING`, `ACTIVE`, `SUSPENDED`.
Backed by a native Postgres enum (`tenant_status`) and a NOT NULL `Tenant.status` column, added in
migration `0009_add_tenant_status.py`.

**Migration safety** (existing tenants must not become invisible or broken): the column is added
with `server_default='active'`, so every row that exists at migration time — including the one
production tenant — becomes `ACTIVE` in the same statement, in one metadata-only pass. Immediately
after, the migration runs `ALTER COLUMN status DROP DEFAULT`. From that point on there is no
column-level default; the *model* supplies one instead (`Tenant.status` has Python-side
`default=TenantStatus.ONBOARDING`). This is deliberate: a single server-side default would apply
identically to "the existing tenant this migration is backfilling" and "a tenant someone creates
tomorrow," which is exactly the distinction that matters. Splitting it — a one-time SQL default for
the backfill, a Python default for everything that comes after — makes both cases correct without
one masking the other.

`SUSPENDED` exists only as the future-compatible slot the brief asked for. No code path in this
phase transitions a tenant into it, and no behavior is conditioned on it — it is inert until a
future (billing-related) phase gives it meaning.

**Where status is checked**: exactly one place, `cmd_start`. Not `ACTIVE` → route to onboarding or
a "still being set up" message (§10) depending on who's asking. Every other handler in the
codebase is unchanged and still implicitly assumes an active, fully-configured tenant — true for
100% of tenants that can currently reach them, since a customer never gets past `cmd_start`'s gate
otherwise.

## 4. Owner creation

The first owner of a tenant is a `StaffMember` row with `role=Role.TENANT_OWNER` — the existing
RBAC model, unchanged (`app/database/models/staff.py`). No parallel identity/auth system.

**The ADMIN_ID bridge** (temporary, narrow, documented per the brief's explicit ask): when a
tenant is not `ACTIVE` and has **zero** `StaffMember` rows at all, the first Telegram user in
`ADMIN_ID` to send `/start` is granted `TENANT_OWNER` for that tenant, via
`TenantOnboardingService.ensure_owner` → `StaffService.create_staff` (`app/services/staff.py` —
already existed, already did a guarded create + `AuditLogEntry` + commit, was simply never called
by any handler before this phase). This is **not** a platform-role promotion: `Role` still has no
`SUPER_ADMIN` member (Phase 2's structural guarantee is untouched), `ADMIN_ID` still means
platform-level `SUPER_ADMIN` exactly as before, and once the owner row exists, the "zero staff"
precondition is permanently false for that tenant — the bridge cannot fire again, and every further
onboarding action is gated by `Permission.MANAGE_TENANT` like any other tenant-scoped operation.

**Preventing duplicate owners**: two safeguards, not one.
1. A **partial unique index** (migration `0009`): `uq_staff_members_tenant_id_owner` — `(tenant_id)
   UNIQUE WHERE role = 'tenant_owner'`. At most one `tenant_owner` row per tenant, enforced by
   Postgres. This is the authoritative guarantee; it holds even if application code has a bug.
2. `TenantOnboardingService.ensure_owner` checks for an existing owner first (fast path, no
   exception in the common case), and if a race still slips through (two `/start`s landing at
   nearly the same moment), catches the resulting `IntegrityError`, rolls back, and re-fetches the
   real owner instead of raising or silently creating a second row.

## 5. Onboarding state machine

Deliberately **not** a stored "current step." Every step in the brief's own state machine
(`OWNER_CREATED`, `BRANCH_CREATED`, `SERVICES_CONFIGURED`, `STAFF_CONFIGURED`,
`SCHEDULE_CONFIGURED`, `READY_TO_ACTIVATE`) is answered by a live query against real data, not a
flag that could drift from it:

| Step | Derived from |
|---|---|
| Owner created | `StaffRepository.get_owner()` returns a row |
| Branch created | `BranchRepository.list_active()` is non-empty |
| Services configured | `ServiceRepository.list_active()` is non-empty |
| Staff configured | an active `Barber` is linked (`barber_branches`) to an active `Branch` |
| Schedule configured | that barber has ≥1 `WorkingSchedule` row at that branch |

This single table is implemented once, in `TenantOnboardingService.validate_ready`, and used by
*both* the wizard (to decide what to show next) and the activation gate (to decide whether
`ACTIVATE` is actually allowed) — never two slightly different definitions of "done." It is the
brief's own offered escape hatch ("if tenant fields are sufficient, do not create an unnecessary
table") taken all the way: no `OnboardingSession` table, no `Tenant.onboarding_step` column, and as
a direct consequence, no way for stored progress to say "step 3 done" while the row that was
supposed to prove it has since been deleted or never actually committed. Resuming after a bot
restart, re-opening the wizard, and re-invoking the same step twice all reduce to the same
read-only recomputation.

## 6. Initial branch creation

Wizard step 2 (`OnboardingSG.branch_name` → `.branch_timezone` → `.branch_currency` in
`app/bot/handlers/onboarding.py`) collects a name, then a timezone, then a currency, and calls the
existing `BranchRepository.create(name=..., timezone=..., currency=...)` — unchanged model, no
second branch system. `BranchRepository.create` gained a `currency` parameter this phase (it
already had `timezone`, added in Phase 4), following the exact same "default from the tenant's own
value if not given" shape as the existing `timezone` parameter (`app/database/repositories/branch.py`).

Timezone and currency are validated by two new functions in `app/utils/validators.py` —
`validate_timezone` and `validate_currency` — that are straight extractions of the checks
`Settings._validate_timezone`/`_validate_currency` already perform (`ZoneInfo(value)`, catch
`ZoneInfoNotFoundError`; three-letter alpha code), now reusable outside Pydantic. Only real IANA
identifiers are accepted (`Europe/Chisinau`, `Europe/Bucharest`, ...) — never a raw offset like
`UTC+2` — so `Branch.tz` (Phase 4) keeps producing DST-correct results the moment scheduling reads
it; there is no separate "onboarding timezone" representation to keep in sync with the real one.
`Tenant.timezone`/`Tenant.currency` are offered as the pre-filled defaults (user can send `-` to
accept them), but the persisted `Branch.timezone`/`Branch.currency` is what becomes authoritative
for that branch, exactly as Phase 4 already established for timezone alone.

## 7. Initial services / staff

- **Service** (wizard step 3): one `Service` via the existing `ServiceRepository.create(...)`.
  `currency` is set from the branch just created (`branch.currency`) rather than
  `Settings.default_currency` — the one deliberate, minimal piece of currency wiring this phase
  adds. It does not touch `admin/services.py`'s general "add service" flow, which intentionally
  keeps defaulting from `Settings` — out of scope, unchanged. No `BranchService` row is written:
  Phase 4's opt-out default ("no row = available everywhere") already makes the new service
  available at the new branch for free.
- **Staff/barber** (wizard step 4): one `Barber` via the existing `BarberRepository.create(...)`,
  then `BranchRepository.assign_barber(...)` — the same "auto-assign to the tenant's sole branch"
  pattern `admin/barbers.py` already uses when creating a barber in a single-branch tenant (Phase
  3/4), reused rather than reinvented. `Barber.branch_id` does not exist and is not reintroduced —
  the assignment is a `barber_branches` row, so nothing prevents this barber from being assigned to
  more branches later through the existing admin UI. No `BarberService` rows are created either —
  same opt-out default (Phase 4 invariant, preserved exactly, not touched by this phase).

`StaffMember` and `Barber` stay the two distinct things they already were (RBAC identity vs.
booking/staff entity) — onboarding does not merge them or add a second staff concept. The owner
created in §4 is a `StaffMember` with no `Barber` attached unless they separately also add
themselves as a bookable barber through the normal admin flow — out of scope for the wizard itself.

## 8. Schedule setup

Wizard step 5 (`OnboardingSG.schedule_hours`) collects one working-hours range
(`10:00-19:00`-style, validated by the existing `validate_time_range`) and applies it to all seven
weekdays for the barber/branch pair just created, via the existing
`ScheduleRepository.set_day(barber_id, branch_id, weekday, start, end)` in a loop — the same
per-day primitive `admin/schedule.py` already uses, not a new schedule-writing path. This
deliberately does not replace or duplicate `admin/schedule.py`'s full per-weekday editor; onboarding
only needs *a* usable schedule to satisfy readiness and let the existing availability computation
(`ScheduleService`, Phase 4) return real slots. Refining hours per day, adding exceptions, or
setting up a second barber's different hours all remain jobs for the existing admin screens,
reachable the moment the tenant is `ACTIVE`.

Because `ScheduleService` already takes a resolved `Branch` (Phase 4) and reads `branch.tz`, the
schedule created here is timezone-correct and DST-safe with no special handling in the onboarding
code itself — it inherits Phase 4's fix by construction, simply by using the same repository.

## 9. Completion criteria (activation)

`TenantOnboardingService.validate_ready()` returns a structured `OnboardingReadiness(is_ready:
bool, missing: list[str])` — never a bare boolean. `missing` holds **i18n keys**
(`"onboarding.missing_branch"`, `.missing_service`, `.missing_barber`, `.missing_schedule"`), not
rendered text, so the wizard's review screen renders them in the owner's own language. The five
checks are exactly the table in §5; nothing beyond what the booking flow actually needs.

`TenantOnboardingService.activate(actor_telegram_id)`:
1. If the tenant is already `ACTIVE`, returns `is_ready=True` immediately — no-op, not an error
   (idempotent double-activation).
2. Otherwise re-runs `validate_ready()` itself — **never trusts that the wizard's last-shown review
   screen is still accurate**. A client tapping "Launch" is a request to re-check, not a command to
   flip the flag.
3. Only if ready: sets `status = ACTIVE`, writes one `AuditLogEntry("tenant.activated")`, commits.
   If not ready, returns the same structured result and writes nothing.

A tenant can never become `ACTIVE` because a button was pressed — only because the server,
independently, found every requirement satisfied at the moment of the call.

## 10. Authorization model

- **Tenant isolation**: every onboarding repository call goes through the same
  `TenantScopedRepository` subclasses used everywhere else (`BranchRepository`,
  `ServiceRepository`, `BarberRepository`, `ScheduleRepository`, `StaffRepository`) — never
  `session.get`. Nothing new here; onboarding adds no new isolation mechanism because none was
  needed.
- **Role permission**: `Permission.MANAGE_TENANT` (already defined in Phase 2, already granted to
  `TENANT_OWNER`/`TENANT_ADMIN` via `ROLE_PERMISSIONS`, checked by zero handlers before this
  phase) gates every onboarding mutation. The onboarding router itself carries **no** router-level
  permission filter — unlike every admin sub-router — because the ADMIN_ID-bridge handler in
  `cmd_start` must be able to reach the entry screen *before* any `StaffMember`, and therefore any
  permission, exists for that tenant. Instead, the two callback handlers that are independently
  reachable without going through that gate (`OnbCB(action="continue")` and
  `OnbCB(action="activate")` — Telegram callback_data can be sent by any client regardless of what
  screen produced the button) each call `AuthorizationService.require(staff,
  Permission.MANAGE_TENANT, ...)` inline, the same "weak router filter + strong inline check on the
  specific action" pattern already established in `admin/reports.py::export_csv` and
  `admin/staff.py::toggle_staff_branch`. The sequential text-input steps in between are ordinary
  FSM-state handlers: aiogram's FSM storage is keyed per Telegram (chat, user), so a user can only
  be "in" `OnboardingSG.branch_name`, etc., if a gated handler put them there — there is no way for
  a different, ungated user to inject a message into someone else's state.
- **Resource ownership / branch access**: not applicable yet in onboarding — every resource created
  is brand new and owned by the one tenant the acting user is already scoped to; there is no
  existing resource to misattribute.

## 11. Idempotency / retry behavior

- **Owner creation**: DB partial unique index + `ensure_owner`'s fetch-first/catch-`IntegrityError`
  fallback (§4). Two `/start`s at once produce one owner, not zero and not two.
- **Branch/service/barber/schedule creation**: each wizard step checks real data before prompting
  (§5's table) — if the tenant already has an active branch, the wizard shows the service step
  (or review) instead of asking to create a branch again. Double-tapping "Continue," restarting the
  bot mid-wizard, or navigating back to `/start` all reduce to the same recomputation and never
  re-create a resource that already exists. The existing unique constraints on `branches`
  (`tenant_id, name`) and `services` (`tenant_id, name`) are a second line of defense if a genuine
  double-submit ever reaches the database layer.
- **Activation**: idempotent by construction (§9.1) — calling `activate` on an already-`ACTIVE`
  tenant is a safe no-op, not a duplicate audit entry or an error.
- **`create_tenant`**: a plain insert; calling it twice makes two tenants (that is its job — it is
  the "create a *new* tenant" primitive, not an upsert). Nothing in this phase calls it more than
  once per intended tenant.

## 12. Security considerations

Every point in the brief's IDOR checklist, verified for this phase's actual surface area:
- No onboarding callback or FSM-stored value carries a cross-tenant-guessable id that matters —
  branch/service/barber ids created during onboarding are read back through the same tenant-scoped
  repository that created them, for display only, never trusted as "this belongs to the tenant I'm
  scoped to" without a fresh lookup.
- `staff_id`, `branch_id`, etc. are never taken from raw callback_data in this flow the way, say,
  `admin/appointments.py` must handle a forged appointment id — onboarding's callbacks
  (`OnbCB(action=...)`) carry only a fixed action string, no id, precisely to avoid that whole class
  of problem existing here at all.
- `AuthorizationService.require` (not just `has_permission`) is used at every independently
  reachable mutation point, raising rather than silently no-op'ing, matching the codebase's
  established convention.
- The ADMIN_ID bridge (§4) only ever grants `TENANT_OWNER` **for the one tenant this bot process
  serves** — it has no path to touch any other tenant's data, because there is no other tenant this
  process ever resolves a `tenant_id` for.

## 13. What remains intentionally out of scope

Telegram bot/webhook provisioning, BotFather automation, Stripe, billing, subscriptions, plans,
usage limits, a SaaS admin dashboard, a public signup website, any business logic conditioned on
`TenantStatus.SUSPENDED` (the value exists as a future-compatible slot only), multi-bot tenant
resolution (Phase 7 — see §14), per-branch timezone in `stats.py`/`export.py` (a Phase 4 known
limitation, unchanged by this phase), a "business name" edit step wired into the resumable
progression (§5's table intentionally has no such row — the wizard shows the current name once on
the entry screen; renaming is available through the ordinary admin flow once active, not specially
threaded into onboarding's derived-progress logic), and Phase 6 in general.

## 14. Future compatibility with multi-bot (Phase 7)

Nothing in `TenantOnboardingService` reads global process state — every method takes `tenant_id`
(and, where relevant, `telegram_id`/`actor_telegram_id`) as an explicit parameter, exactly as if it
were already being called from a request handler that resolves `tenant_id` per-update instead of
once at startup. The one place today's single-process assumption is still baked in is
`resolve_default_tenant_id`'s *caller* (`app/main.py`, which resolves one `tenant_id` for the
process's entire lifetime) — not the onboarding service layer itself. A future multi-bot rewrite
would replace *that* call site's "resolve once at startup" with "resolve per update" (e.g. from the
bot token or a routing table) and hand the result to the exact same `TenantOnboardingService`
methods used today; none of them would need to change. `TenantOnboardingService.create_tenant` is
already shaped for that world — it is the literal "provision tenant N" primitive a future platform
layer would call, just not wired to any live Telegram command yet, since no such command can mean
anything in a bot that only ever serves one tenant per process.
