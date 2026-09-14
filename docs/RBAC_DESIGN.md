# RBAC Design — Phase 2

## 1. Audit of the current model (before this phase)

- **Telegram users**: one `User` model (`app/database/models/user.py`) represents every human —
  today used only for customers. Columns: `telegram_id`, `full_name`, `username`, `phone`,
  `language_code`, `is_blocked`, plus `tenant_id` (required, `UniqueConstraint(tenant_id,
  telegram_id)`). No role/permission column.
- **Admin identification**: 100% a process-wide env var. `Settings.admin_id`/`admin_ids`
  (`app/config/settings.py`) parses `ADMIN_ID` into a tuple of Telegram ids; `is_admin(id)` is a
  membership check. **Zero database representation, not tenant-aware** — one global list shared
  by every tenant in the process.
- **Where admin checks happen**: exactly one place, `app/bot/handlers/admin/__init__.py`, which
  attaches `IsAdmin()` (`app/bot/middlewares/admin.py`) to the whole admin router, gating ~40
  handlers across 7 files (`menu`, `services`, `barbers`, `schedule`, `appointments`, `reports`,
  `editing`). No other independent authorization check exists anywhere; every other `is_admin`
  reference in the codebase is a `bool` threaded into client keyboards purely to show/hide the
  "Admin panel" button.
- **Are users tenant-scoped already?** Yes — `User.tenant_id` and `Barber.tenant_id` are both
  required (Phase 1), each with `UniqueConstraint(tenant_id, telegram_id)`.
- **Do barber/staff identities already exist?** `Barber` has a nullable `telegram_id` column that
  is **completely unused** — zero read sites anywhere in the codebase outside its own model/
  constraint definition. There is no barber-login mechanism today.
- **Which handlers require authorization?** All ~40 admin handlers (full list in the Phase 2
  implementation plan / git history). Client-facing handlers (booking, appointments, info, common)
  need no role check — they already do row-ownership filtering (e.g. a client can't cancel someone
  else's appointment), which is a different concern from RBAC (see §6).
- **Audit log**: none exists.

## 2. Roles

```
SUPER_ADMIN     — platform-level, NOT a role a database row can hold (see §3)
TENANT_OWNER    — tenant-level, full access to their own tenant
TENANT_ADMIN    — tenant-level, full operational access, no billing
MANAGER         — tenant-level, operational management, limited staff visibility
RECEPTIONIST    — tenant-level, day-to-day bookings/customers
BARBER          — tenant-level, own schedule/bookings, limited customer visibility
```

`Role` is a Python `enum.StrEnum` in `app/database/models/staff.py`. It intentionally has **five**
members, not six — `SUPER_ADMIN` is not in it.

## 3. Why `SUPER_ADMIN` is not a `StaffMember` role

The spec requires: "a tenant admin cannot create or assign SUPER_ADMIN." The strongest way to
guarantee that is structural, not procedural: `SUPER_ADMIN` stays exactly what it is today —
membership in the `ADMIN_ID` env var, checked by the unmodified `IsAdmin` filter and
`Settings.is_admin()`. No code path in the application writes to that env var; no database column
can hold that value, because `Role`'s Python enum simply doesn't define it (`Role("super_admin")`
raises `ValueError`). This means the invariant holds even against a future bug in some
staff-management code — there is no `role` value that bug could ever set to reach platform level.

`SUPER_ADMIN` bypasses every permission check (see `AuthorizationService.has_permission`, §5) but
this phase adds no super-admin-only feature or panel — it remains exactly as capable as today's
`ADMIN_ID`, just formally named for what it now means now that tenant-level roles exist
underneath it.

## 4. Permissions

```
MANAGE_TENANT         MANAGE_STAFF        VIEW_STAFF
MANAGE_SERVICES       MANAGE_SCHEDULE     MANAGE_BOOKINGS
MANAGE_CUSTOMERS      VIEW_CUSTOMERS      VIEW_ANALYTICS
MANAGE_SETTINGS       MANAGE_SUBSCRIPTION
```

The 9 requested permissions, plus `VIEW_STAFF` and `VIEW_CUSTOMERS` — added because the requested
role matrix distinguishes "manage" from "view" for Manager ("limited staff access") and
Barber/Receptionist ("view relevant customers"); a single coarse `MANAGE_STAFF`/`MANAGE_CUSTOMERS`
bit can't express that distinction.

**Not wired to any handler this phase**: `VIEW_STAFF`, `MANAGE_TENANT`, `MANAGE_SETTINGS`,
`MANAGE_SUBSCRIPTION`. No read-only staff list, tenant-settings screen, or billing screen exists
yet for them to gate — they exist in the enum and the matrix because the requested permission list
and role matrix call for them, and are proven by a direct unit test of the matrix
(`tests/test_authorization.py`), not by a bot-reachable code path. This is stated here explicitly
rather than left implicit.

## 5. Role → permission matrix

| Permission | OWNER | ADMIN | MANAGER | RECEPTIONIST | BARBER |
|---|:-:|:-:|:-:|:-:|:-:|
| MANAGE_TENANT | ✅ | ✅ | | | |
| MANAGE_STAFF | ✅ | ✅ | | | |
| VIEW_STAFF | ✅ | ✅ | ✅ | | |
| MANAGE_SERVICES | ✅ | ✅ | ✅ | | |
| MANAGE_SCHEDULE | ✅ | ✅ | ✅ | ✅ | |
| MANAGE_BOOKINGS | ✅ | ✅ | ✅ | ✅ | |
| MANAGE_CUSTOMERS | ✅ | ✅ | ✅ | | |
| VIEW_CUSTOMERS | ✅ | ✅ | ✅ | ✅ | ✅ |
| VIEW_ANALYTICS | ✅ | ✅ | ✅ | | |
| MANAGE_SETTINGS | ✅ | ✅ | | | |
| MANAGE_SUBSCRIPTION | ✅ | | | | |

`SUPER_ADMIN` (not a row, see §3): every permission, in every tenant, always.

Rationale per role, tied to what this application actually does today:
- **TENANT_OWNER**: every permission — the legal owner of the tenant, including the one thing
  `TENANT_ADMIN` doesn't get (`MANAGE_SUBSCRIPTION` — billing is Phase 3, but the matrix already
  needs to separate "runs the business" from "pays the bill").
- **TENANT_ADMIN**: everything except `MANAGE_SUBSCRIPTION`, matching the requested matrix's
  "manage staff/services/schedule/bookings/customers/settings/analytics."
  `MANAGE_TENANT`/`MANAGE_STAFF` are included per the requested matrix even though no
  tenant-settings/full staff-CRUD UI is built this phase.
- **MANAGER**: `VIEW_STAFF` (not `MANAGE_STAFF` — "limited staff access" per the requested
  matrix) plus the full operational set this app has today: services, schedule, bookings,
  customers, analytics.
- **RECEPTIONIST**: `MANAGE_BOOKINGS` + `VIEW_CUSTOMERS` — day-to-day desk work only, per "no
  billing, no role administration" in the requested matrix.
- **BARBER**: `VIEW_CUSTOMERS` only, in the permission matrix, matching "view relevant customers."
  "View own schedule"/"manage own bookings" from the requested matrix are **resource-scoped**, not
  role-permission-scoped — see §6 — because they mean "own," not "all," which a flat permission
  bit can't express; the scoping primitive for this exists and is tested
  (`AuthorizationService.can_manage_own_barber_resource`) but is not wired into a live handler
  this phase since no barber-login flow exists to drive it (see §9).

## 6. Authorization ≠ tenant isolation ≠ resource ownership — three separate, all-mandatory checks

- **Tenant isolation** (Phase 1): "can this Telegram user's request touch tenant B's data at
  all?" Enforced by `TenantScopedRepository` requiring `tenant_id` in its constructor and every
  query filtering on it — unrelated to who the user is within their own tenant.
- **Authorization** (this phase): "does this user's role grant the permission this operation
  needs, inside their own tenant?" Enforced by `RequirePermission`/`AuthorizationService`.
- **Resource ownership** (this phase, extending the pattern client-booking already uses — e.g. a
  client can only cancel their own appointment, never someone else's): "even with the right
  permission, is this the specific resource this user is allowed to touch?" For staff, the
  concrete case in the requested spec is a `BARBER` only managing their own schedule, not another
  barber's — `AuthorizationService.can_manage_own_barber_resource(staff, barber_id)`.

All three are independent and all are checked where relevant — none substitutes for another. A
`RECEPTIONIST` passes tenant isolation (they're a real member of tenant A) and has
`MANAGE_BOOKINGS`, but has no `MANAGE_STAFF` permission at all, at any resource scope.

## 7. Telegram security (never trust client-supplied ids)

Every sensitive operation resolves the *acting* identity from `event.from_user.id` (Telegram's own
signed field, not application-controlled) and looks up the current tenant's `StaffMember` row for
it server-side — never from `callback_data`, FSM state, or any other value that round-trips
through the client. `callback_data`/FSM-state UUIDs (a target `barber_id`, `service_id`, etc.)
are treated purely as "which resource does the request claim to be about" and are resolved through
tenant-scoped repository lookups before use, exactly like Phase 1 already established for
`barber_id`/`service_id` in the booking flow, and like the Phase 1.5 audit fix applied to
`ScheduleRepository.set_day`/`upsert_exception`.

## 8. Migration strategy

`0005_add_staff_rbac.py` (after `0004`, previous migrations untouched): creates `staff_members`
and, in the same migration, maps the *existing* `ADMIN_ID` env var into real rows for the one
tenant that exists today. The **first** id listed in `ADMIN_ID` becomes `TENANT_OWNER`; every
other id becomes `TENANT_ADMIN`. This is the only signal available — `Settings.admin_ids` treats
every entry identically today, so order is the one piece of information carried forward. **This
is an operational decision an operator should sanity-check before running the migration in
production** if `ADMIN_ID` currently lists more than one id and the order doesn't reflect who the
actual owner is.

The tenant is resolved by querying the `tenants` table directly (the same logic
`app/database/tenants.py:resolve_default_tenant_id` uses at runtime), not by re-deriving it from
`Settings` the way migration `0004` did — by the time `0005` runs, the real tenant row from `0004`
already exists, so there's exactly one correct row to attach staff to.

The insert uses `ON CONFLICT DO NOTHING` on `(tenant_id, telegram_id)`, so re-running the
migration (or running it after someone has already manually inserted a matching row) does not
create duplicates. `downgrade()` drops the table and its enum type — no data is preserved across a
downgrade, which is correct for a purely additive table with no other table depending on it.

`0006_add_audit_log.py` is a separate, independent migration for `audit_log_entries` — kept apart
from the RBAC data migration so either can be reasoned about or rolled back without the other.

## 9. Backward compatibility strategy

- The *existing* tenant owner (today's sole `ADMIN_ID` entry) keeps working identically: they
  still pass `IsAdmin`/`settings.is_admin()` as `SUPER_ADMIN`-equivalent for this codebase's
  purposes, which makes `AuthorizationService.has_permission(..., is_super_admin=True)` return
  `True` unconditionally — so every new `RequirePermission` filter on every admin sub-router
  passes for them exactly as `IsAdmin` alone did before. No existing admin workflow changes.
- `data["is_admin"]` (used only to show/hide the "Admin panel" keyboard button) is *widened*, not
  replaced: `is_admin OR (active staff row exists)`. The existing admin's value doesn't change.
- The existing "no rights" UX (`app/bot/handlers/fallback.py`'s `denied_admin_callback`/
  `denied_admin_command`) is reused unmodified — it already fires for anything the admin router's
  filters reject, at any nesting level, so a new lower-privilege role hitting a permission they
  lack produces the same response a non-admin does today.
- No customer-facing flow changes at all — booking, cancellation, rescheduling, reminders are
  untouched by this phase.
- No existing test needed to change; four `IsAdmin`-focused tests and three end-to-end
  admin-gating tests were traced through the new design and confirmed to keep passing unmodified
  (documented in the Phase 2 completion report).

## 10. What this phase deliberately does not build

Branches, billing/subscriptions, multi-bot, Mini App, onboarding, analytics dashboards (per
explicit instruction) — plus, surfaced during design: no staff-management UI/bot commands (the
`StaffService` exists and is tested but nothing calls it from a Telegram handler yet), no barber
self-service chat flow (the resource-ownership primitive exists and is unit-tested but isn't wired
into a live path, since there's no barber-login mechanism to drive it), `admin_menu_kb()` is not
made role-aware (every staff member still sees every button; tapping one they lack permission for
hits the existing "no rights" fallback).
