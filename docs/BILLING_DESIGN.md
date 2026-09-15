# Billing Design — Phase 6

## 1. Architectural audit (before this phase)

Grepping the whole codebase for `plan|subscription|billing|payment|quota|feature.?flag`
before writing any code turned up exactly one relevant hit: `Permission.MANAGE_SUBSCRIPTION`
(`app/database/models/staff.py`), defined in Phase 2, granted to `TENANT_OWNER` only
(`ROLE_PERMISSIONS[Role.TENANT_ADMIN] = frozenset(Permission) - {MANAGE_SUBSCRIPTION}`), and never
read by any handler. Phase 6 is the first phase that actually uses it. Nothing else pre-existed —
this document describes genuinely new territory, not a rename or extension of something already
there.

One existing concept must **not** be confused with what Phase 6 adds:
`Settings.max_active_appointments` (`app/config/settings.py`), enforced in
`app/services/rules.py::ensure_within_limit`, is a global, per-**customer** cap on simultaneous
active bookings. It is a completely different axis from the new per-**tenant** SaaS plan limits
(`MAX_BRANCHES`, `MAX_STAFF`, `MAX_MONTHLY_APPOINTMENTS`, ...) introduced here. Both continue to
exist, independently, doing different jobs. (A test bug during this phase's own verification
briefly conflated the two — see §13.)

## 2. Architecture

```
Tenant ──1:1── Subscription ──N:1── Plan ──1:N── PlanFeature (Feature enum)
                    │                  └──1:N── PlanLimit   (LimitKey enum, value|NULL)
                    │
                    └── status: TRIALING/ACTIVE/PAST_DUE/CANCELED/EXPIRED

Usage: derived on demand from existing tables (COUNT/aggregate queries), never a
       denormalized counter.

Enforcement: EntitlementService.has_feature() / LimitService.assert_can_create()
             called from application/service-layer code (never only from a
             Telegram handler), raising transport-neutral BillingError subclasses
             that handlers translate to localized text.
```

Application code never asks "does this tenant have plan X" — it asks "can this tenant do Y right
now": `EntitlementService.has_feature(Feature.CSV_EXPORT)`,
`LimitService.assert_can_create(LimitKey.MAX_BRANCHES)`. The plan a tenant is on is an
implementation detail behind that question, not something callers branch on.

## 3. Models (`app/database/models/billing.py`)

**Global catalog — no `tenant_id`** (a plan belongs to the platform, not a tenant):

- `Plan(id, code, name, description, is_active, created_at, updated_at)` — `code` is the stable,
  human-chosen machine key (`"free"`, `"pro"`, `"legacy"`), never a database UUID, never a
  Stripe price ID.
- `PlanFeature(id, plan_id, feature)` — `feature` is the `Feature` enum; unique on
  `(plan_id, feature)`.
- `PlanLimit(id, plan_id, limit_key, value)` — `limit_key` is the `LimitKey` enum; `value` is
  `int | None`, unique on `(plan_id, limit_key)`; `CHECK (value IS NULL OR value >= 0)`.
  **`NULL` means unlimited** — not `0`, not `-1` — so "no limit" can never be confused with "limit
  of zero."

**Tenant-owned — exactly one row per tenant**:

- `Subscription(id, tenant_id, plan_id, status, current_period_start, current_period_end,
  canceled_at, created_at, updated_at)` — `UniqueConstraint(tenant_id)`. This is a *current state*
  table, not a history/ledger. A tenant cannot have two "current" subscriptions by construction
  (a plain unique constraint, no partial-index trickery needed — satisfies the brief's "enforce
  via DB constraint that only one subscription is current per tenant" literally). A historical
  ledger of plan/status changes is explicitly deferred: `AuditLogEntry` already records *that* a
  change happened (§10) which is enough until real payment events exist to populate a real ledger.

`current_period_start`/`current_period_end` are `DateTime(timezone=True)`, UTC-aware, and exist
for a future Stripe-driven billing cycle — **today's usage calculation does not read them** (see
§6). `Branch.timezone` is never used for anything billing-related; billing periods are a
completely separate axis from scheduling (per the brief's explicit instruction).

## 4. Feature vs. Limit

`Feature` (boolean — "can this tenant use X"): `BASIC_BOOKING`, `REMINDERS`, `CSV_EXPORT`,
`ANALYTICS`.

`LimitKey` (numeric — "how much X can this tenant have"): `MAX_BRANCHES`, `MAX_BARBERS`,
`MAX_STAFF`, `MAX_SERVICES`, `MAX_MONTHLY_APPOINTMENTS`.

`BASIC_BOOKING` is true on every seeded plan and nothing in the application checks it — it exists
as the template for how a universal feature is modeled (matching the brief's own example list),
and as a hook for a hypothetical future plan that *doesn't* include it.

**Deliberately excluded from `Feature`**:

- `MULTI_BRANCH` — the brief's own example feature list includes it, but in this codebase "can
  this tenant have more than one branch" is *entirely* captured by `MAX_BRANCHES`'s numeric value
  already. A separate boolean flag would be a second, independently-editable source of truth for
  the same fact (the flag could say "yes" while the limit says `1`) — one limit, one truth.
- Advanced RBAC / advanced schedule exceptions — both are core operational/security surface
  (Phase 2/4), not upsell-shaped boundaries. Gating either risks exactly the "accidental
  production lockout" the brief warns against, for functionality every existing tenant already
  depends on for free today.

No other features were added. The brief explicitly asks for "a small number of real features," not
an exhaustive catalog.

## 5. Subscription lifecycle

`SubscriptionStatus`: `TRIALING`, `ACTIVE`, `PAST_DUE`, `CANCELED`, `EXPIRED` — a fixed,
provider-independent set, not copied from Stripe's status names. Phase 6 code only ever
*assigns* `ACTIVE` (onboarding's default-plan creation, migration 0010's Legacy backfill,
`SubscriptionService.get_or_create_default`'s defensive fallback). The other four statuses exist
as valid, unit-tested states for `is_effectively_active()` (§6) — exactly like
`TenantStatus.SUSPENDED` was defined but never assigned in Phase 5 — future-compatible, not dead
code, since nothing in Phase 6 has a way to *cause* those transitions (no payment provider to fail
a charge or expire a trial yet).

`Tenant.status` (`ONBOARDING`/`ACTIVE`/`SUSPENDED`, Phase 5) and `Subscription.status` are **two
separate domains** and nothing in this phase links them. A tenant can be `Tenant.status=ACTIVE`
with `Subscription.status=PAST_DUE` (a grace period — still usable) — Phase 6 never automatically
forces `Tenant.status=SUSPENDED` because of subscription state, and no code path does the reverse
either.

### Grace period: `is_effectively_active()`

```python
def is_effectively_active(status: SubscriptionStatus) -> bool:
    return status in (TRIALING, ACTIVE, PAST_DUE)
```

A pure function, no I/O, fully unit-tested (`tests/test_integration_billing.py`'s truth-table
test). It implements the brief's own example ("PAST_DUE — tenant might still be usable during a
grace period") as a deterministic, testable rule, without dunning, payment retries, or a real
grace-period *duration* — none of which have anything to drive them without a payment provider.
**Nothing in Phase 6 currently calls this function to gate anything** (nothing can become
`PAST_DUE`/`CANCELED`/`EXPIRED` yet) — it exists, tested, for a future payment-webhook handler to
call before deciding whether to also touch `Tenant.status` (which it still must never do
automatically). This deferral is intentional, not an oversight.

## 6. Usage model

Usage for `MAX_BRANCHES`/`MAX_BARBERS`/`MAX_STAFF`/`MAX_SERVICES` is a plain aggregate query
against existing tables — active branches; barbers that are active **and** linked to at least one
active branch ("bookable," the same predicate as
`TenantOnboardingService._has_bookable_barber`, Phase 5); active `StaffMember` rows; active
services. One `COUNT` (or `COUNT(DISTINCT ...)` for barbers) per check — no denormalized counters,
no N+1.

`MAX_MONTHLY_APPOINTMENTS` usage is a `COUNT` of the tenant's appointments whose `starts_at` falls
in the **current UTC calendar month** — `[first-of-month 00:00 UTC, first-of-next-month 00:00
UTC)` — with status `CONFIRMED` or `COMPLETED` only, explicitly excluding `CANCELLED`/`NO_SHOW`.
This mirrors the exact `(CONFIRMED, COMPLETED)` tuple already used as "counts as real activity" in
`AppointmentRepository.summary`/`revenue_between`, and matches the brief's own recommendation
("prefer not counting canceled appointments unless the product strongly suggests otherwise" — it
doesn't here). One appointment is counted at most once by construction (one row, one status, one
`starts_at`).

**Why calendar-month, not `Subscription.current_period_start/end`**: with no payment provider,
`current_period_end` has nothing driving it forward — there is no renewal event to roll it over.
Treating it as the usage window today would mean "current period" silently drifts into the past
with no trigger to advance it. The period fields are still stored (UTC-aware) as the field a
future Stripe-driven billing cycle will populate and usage will switch to reading — documented
here as a deliberate, temporary simplification, not a bug.

## 7. Enforcement points

| Entity / action                         | Enforced in                                        | Check |
|------------------------------------------|-----------------------------------------------------|-------|
| Branch creation                          | `app/services/provisioning.py::BranchProvisioningService` | `MAX_BRANCHES` |
| Barber creation                          | `BarberProvisioningService`                          | `MAX_BARBERS` |
| Service creation                         | `ServiceProvisioningService`                         | `MAX_SERVICES` |
| Staff creation                           | `app/services/staff.py::StaffService.create_staff`   | `MAX_STAFF` |
| Appointment creation                     | `app/services/booking.py::BookingService.create_appointment` | `MAX_MONTHLY_APPOINTMENTS` |
| CSV export                               | `admin/reports.py::export_csv`                       | `Feature.CSV_EXPORT` |
| Stats/analytics screen                   | `admin/reports.py::show_stats`                       | `Feature.ANALYTICS` |
| Reminder dispatch (24h/2h/return)        | `app/services/notifications.py::NotificationService.dispatch_due` | `Feature.REMINDERS` |

`Branch`/`Barber`/`Service` had no pre-existing service layer (admin handlers called bare
repositories directly). Rather than checking limits inline in the handler (which a future
REST/Mini-App endpoint could bypass by calling the repository directly) or retrofitting a full
service layer for three simple entities, Phase 6 adds **one new file**,
`app/services/provisioning.py`, with three small classes — `BranchProvisioningService`,
`BarberProvisioningService`, `ServiceProvisioningService` (named to avoid colliding with the
existing `BranchService`/`BarberService` *models*, the Phase 3/4 opt-out association tables). Each
wraps exactly one repository `.create()` call with the matching `LimitService.assert_can_create()`
first. The admin handlers now call these instead of the bare repository — a one-line change per
handler — so a future API calling the same provisioning class cannot bypass the check either.
Commit ownership stays with the caller (matching the existing repository convention: repositories/
provisioning services `flush`, the calling handler `commit`s) — this matters for
`admin/barbers.py`, which does an additional auto-link insert after creating a barber, in the same
transaction.

`NotificationService.notify_new_appointment`/`notify_cancelled`/`notify_admins`/`notify_client`
are **not** gated by `Feature.REMINDERS` — these are operational notifications to the shop owner
(new booking, cancellation) and messages to a specific client (reschedule/cancel), not the
customer-facing pre-appointment reminder queue. Gating them would risk an owner silently stopping
to hear about new bookings on the free plan, which is exactly the "accidental production lockout"
the brief warns against. Only `dispatch_due` (the 24h/2h/return reminder queue) is gated, and it
fails silently (skip, don't raise) — a disabled feature not firing a reminder is correct product
behavior, not an error to surface.

`Feature.BASIC_BOOKING` gates nothing — booking itself is never paywalled.

**Fail-open default**: if a tenant has no `Subscription` row at all (a state that should not exist
after Phase 6 — every tenant gets one via onboarding or migration backfill, see §9), both
`EntitlementService.has_feature()` and `LimitService.get_limit()` fail **open** (feature available,
limit unlimited) rather than closed. This directly implements the brief's §43 ("if a feature isn't
defined in billing configuration, do not silently deny it") extended to the adjacent case of
missing billing *state* — the alternative (fail closed) would have silently broken every
pre-Phase-6 test fixture and any future code path that creates a `Tenant` without going through
onboarding, which is a worse failure mode than being too permissive in an anomalous state that
production code never produces.

## 8. Concurrency

The existing `app/services/booking.py::_advisory_lock_key` (module-private, truncates a UUID to a
signed bigint) was promoted to a shared `app/utils/locks.py::advisory_lock_key` — a pure function,
zero behavior change, one import-site update in `booking.py` (which still re-exports
`_advisory_lock_key` for backward compatibility with existing tests that import it by that name).

`LimitService.assert_can_create()` takes `pg_try_advisory_xact_lock` on
`advisory_lock_key(tenant_id) + <fixed offset 0-4 per LimitKey>` **before** counting usage, inside
the caller's existing transaction, with its own short bounded retry loop (8 attempts, exponential
backoff up to 200ms) — deliberately **not** sharing `BookingService._acquire_lock`'s retry
implementation (14 attempts, up to 400ms), since that code is proven and tested for the
booking hot path and the brief explicitly says not to replace or risk it. Only the trivial pure
`advisory_lock_key()` function itself is shared.

Two concurrent "create branch" requests for the same tenant serialize on that one lock; the second
sees the post-first-commit count, so the classic "both read count=2, both create, limit=3 becomes
4" race cannot happen. Different `LimitKey`s and different tenants never contend with each other
or with the existing barber/user booking locks — all key spaces are distinct by construction. No
global lock is used anywhere.

`MAX_MONTHLY_APPOINTMENTS` reuses this exact mechanism from inside
`BookingService.create_appointment`, called after the existing `_lock_user`/`_lock_barber`
advisory locks and slot-availability check, before the `Appointment` insert — all still inside the
one transaction `create_appointment` already manages. The pre-existing EXCLUDE constraint,
advisory locks, and tenant isolation are untouched; this adds one more independent check in the
same transaction.

Verified in `tests/test_integration_billing.py`: concurrent branch creation at the limit boundary
(`asyncio.gather`) produces exactly `limit` branches, never `limit + 1`; same shape for the
monthly-appointment limit.

## 9. Existing-tenant migration & backfill

Migration `0010_add_billing.py` (after `0009`, `0001`-`0009` untouched) creates `plans`,
`plan_features`, `plan_limits`, `subscriptions`, and seeds exactly three plans:

- **`free`** (default for tenants created from now on): `MAX_BRANCHES=1`, `MAX_BARBERS=2`,
  `MAX_STAFF=3`, `MAX_SERVICES=10`, `MAX_MONTHLY_APPOINTMENTS=100`; features `BASIC_BOOKING`,
  `REMINDERS`. `is_active=True`.
- **`pro`**: every limit `NULL` (unlimited); all four features. `is_active=True`.
- **`legacy`** (backfill-only, never customer-facing — `is_active=False`, excluded from
  `PlanRepository.list_active()`): every limit `NULL`; all four features.

The migration then loops over **every existing tenant row** (the same "could be more than one,
don't assume a single default" pattern already established in migrations `0007`/`0009`) and
inserts one `Subscription(plan=legacy, status=active, current_period_start=now())` per tenant,
idempotent via `ON CONFLICT (tenant_id) DO NOTHING`. No fake payment records, no forced payment
step — a plain, deterministic, reversible data backfill.

**Why `legacy`, not `free`, for backfill**: an existing tenant might already have two branches (a
real possibility this phase's own migration-verification run exercises deliberately). Backfilling
to `free` (`MAX_BRANCHES=1`) would immediately put such a tenant over its own "current" limit the
moment Phase 6 ships, for a cap that didn't exist when they created their second branch. Backfilling
to `legacy` (unlimited) makes the "existing tenants must not lose access" guarantee unconditional
and provable, not "probably fine because today's tenant happens to be small." No branch, barber,
staff row, or service is ever deleted or deactivated as a result of this migration.

`TenantOnboardingService.create_tenant` (Phase 5) gained one addition: after creating the `Tenant`
row, it creates the tenant's `Subscription(plan=free, status=active)` in the same transaction — so
every tenant that exists after Phase 6 ships has exactly one subscription from the moment it is
created; `SubscriptionService.get_or_create_default()`'s creation path stays a defensive fallback
that steady-state code should never need.

Enum creation note: all three new native Postgres enums (`billing_feature`, `billing_limit_key`,
`subscription_status`) are created implicitly by `op.create_table()` (as SQLAlchemy's DDL compiler
does for any new table with an `Enum`-typed column — see migration `0005`'s `staff_role`), **not**
via an explicit `.create(checkfirst=True)` call — that explicit form is only needed for
`op.add_column` on an *already-existing* table (see migration `0009`'s `tenant_status`), and
calling it here as well produced a `DuplicateObjectError` during this phase's own verification
(caught and fixed before commit — see §13).

## 10. RBAC

Reuses the existing `Permission.MANAGE_SUBSCRIPTION` (Phase 2) exactly as already granted —
`TENANT_OWNER` has it, `TENANT_ADMIN` explicitly does not
(`ROLE_PERMISSIONS[Role.TENANT_ADMIN] = frozenset(Permission) - {MANAGE_SUBSCRIPTION}`), no new
permission invented. `app/bot/handlers/admin/billing.py`'s router is gated by
`RequirePermission(Permission.MANAGE_SUBSCRIPTION)` at both `.message` and `.callback_query`
filters, the same mechanism every other admin sub-router already uses.
`SubscriptionService.change_plan()` itself does **not** check permissions — matching the
established `StaffService`/`BookingService` convention that services trust the caller to have
already called `AuthorizationService.require(...)`; the handler is the one enforcement point.

Platform `SUPER_ADMIN` (`ADMIN_ID`) passes the same `RequirePermission` filter (as it does for
every admin router) and additionally sees a "🔧 [dev] Change plan" control on the Тариф screen
that lets it assign *any* plan (including the non-customer-facing `legacy`) to the current
tenant via `SubscriptionService.change_plan`. This is the minimal, clearly-separated dev/test
mechanism the brief asks for — it does not create a second billing permission system, and
`TENANT_OWNER` is never made equivalent to `SUPER_ADMIN` (the extra control is gated by
`settings.is_admin(user_id)`, checked independently of `MANAGE_SUBSCRIPTION`).

`AuditLogEntry` gains two new `action` values: `"subscription.plan_changed"` (written by
`SubscriptionService.change_plan`, recording old/new `plan_id`) — no second audit log, no secrets
logged.

## 11. Security & tenant isolation

- `Plan`/`PlanFeature`/`PlanLimit` are global catalog tables with no `tenant_id` — cross-tenant
  reads of *catalog* data are fine and expected (every tenant reads the same `free`/`pro`/`legacy`
  rows).
- `Subscription` is `TenantScopedMixin`, and `SubscriptionRepository` (a `TenantScopedRepository`)
  exposes only `get()` — a bare `select(Subscription).where(tenant_id == self.tenant_id)`, no
  `subscription_id` parameter anywhere in the public API. There is nothing to pass a forged ID
  into; a caller can only ever ask "give me *my own* tenant's subscription." Tenant A's
  `LimitService`/`EntitlementService` can never read or count tenant B's branches/staff/services/
  appointments, because every usage query filters on `self.tenant_id`, and every repository
  involved is itself tenant-scoped.
- No payment data (card numbers, CVV, bank credentials, provider tokens) is stored anywhere in
  this schema — there is no field for any of it.
- Verified explicitly in `tests/test_integration_billing.py`: a tenant with zero branches sees
  usage `0` regardless of another tenant's branch count in the same database; a direct attempt to
  point a `Subscription` row at a nonexistent `plan_id` is rejected by the foreign key.
- Verified via a second, realistic migration run (§13): two independently-seeded tenants (one with
  2 branches, one with 1) both land on `legacy`/`active` with correct, non-overlapping usage counts
  after migration `0010`.

## 12. i18n

`FeatureNotAvailable`/`PlanLimitExceeded`/`SubscriptionInactive`/the base `BillingError` (all in
`app/services/billing.py`) carry an i18n key and structured params — the exact
`__init__(self, key, **params)` shape already used by `BookingError`/`AuthorizationError` — never
rendered text. `app/bot/billing_ui.py` is the one shared translation adapter: it turns a
`LimitKey`/`Feature`/`SubscriptionStatus` into a localized label and a `BillingError` into a
localized sentence, reused by every handler that can raise or display one (branch/barber/service
creation, booking, CSV export, analytics, the Тариф screen itself) instead of duplicating the
enum-to-label lookup in each handler file. `billing.*` keys exist in all three locales
(`ru`/`ro`/`en`) with matching `{placeholders}`, verified by the existing
`test_locales_have_identical_key_sets`/`test_placeholders_match_across_locales` tests. Four purely
templated keys (`billing.limit_line`, `billing.limit_line_unlimited`, `billing.feature_line_on`,
`billing.feature_line_off` — punctuation/placeholders/emoji only, no prose) are registered in that
test's pre-existing `SHARED_KEYS` allowlist for legitimately-identical-across-languages strings,
the same mechanism already used for `btn.faq`.

## 13. Testing & verification

- `tests/test_integration_billing.py`: 49 new tests covering plan catalog, subscription lifecycle
  (one-per-tenant DB constraint, `get_or_create_default`, `change_plan` + audit log),
  `is_effectively_active`'s truth table, entitlements (including cross-tenant isolation and the
  fail-open-without-subscription case), limits (`get_usage` for all five keys against real seeded
  data, `NULL` = unlimited), enforcement (branch/barber/service/staff/monthly-appointment denial at
  the limit), concurrency (branch and monthly-appointment limits under `asyncio.gather`), security/
  isolation, RBAC (`MANAGE_SUBSCRIPTION` permission matrix), Legacy-plan backfill semantics, and a
  booking regression smoke test on a Legacy-plan tenant.
- Two real bugs were caught and fixed during this phase's own verification, before commit:
  - `EntitlementService.has_feature()` initially failed *closed* (returned `False`) when a tenant
    had no subscription, silently disabling reminders for every pre-Phase-6 test fixture (which
    creates tenants directly, bypassing onboarding). Changed to fail *open*, matching
    `get_limit()`'s existing convention and the brief's own §43 guidance (see §7).
  - `SubscriptionService.get_or_create_default()` created a subscription via `flush()` but never
    `commit()`ed it, so calling it twice created two different rows instead of returning the same
    one the second time (only found because a test happened to call it twice in separate
    sessions). Fixed to commit when it creates a fallback subscription, and to assign the already-
    fetched `Plan` object onto the new `Subscription.plan` relationship manually (mirroring
    `BookingService.create_appointment`'s existing "assign relationships manually, an async lazy
    load after commit is not safe" pattern) so callers never trigger an async lazy-load.
  - A pre-existing regression test, `test_booking_keeps_query_count_bounded`, hard-codes an exact
    query count; adding the `MAX_MONTHLY_APPOINTMENTS` check legitimately adds two queries (an
    advisory-lock attempt and a subscription+plan lookup) for a tenant with no limit configured on
    that key. The test's asserted bound and explanatory comment were updated to `16` to reflect
    this real, intentional change — not loosened to hide an unrelated failure.
  - The migration's three new enums were initially created via an explicit
    `.create(checkfirst=True)` call *and* implicitly by `op.create_table()`, causing a
    `DuplicateObjectError` on a completely fresh database on the very first upgrade attempt. Fixed
    by removing the explicit calls (see §9's enum-creation note) — the bug was caught by this
    phase's own from-scratch migration verification before it could reach a shared or production
    database.
- Full migration verification, exclusively against disposable scratch databases on the same
  Postgres server as production (`phase6_fresh`, `phase6_existing` — both dropped after use, never
  the `barbershop` database):
  - Fresh database, `0001` → `0010`: seeded catalog verified row-by-row; full test suite (405
    tests: 356 pre-existing + 49 new) green.
  - `0010` downgraded to `0009` (billing tables and enums confirmed gone), re-upgraded to `0010`,
    full suite green again.
  - A second scratch database seeded at `0009` with two independent, realistic tenants (Tenant A:
    owner, 2 branches, a multi-branch barber, a service, a confirmed appointment; Tenant B: owner,
    1 branch, a different barber/service/appointment) plus the pre-existing default tenant from
    migration `0004`'s own seed — three tenants total. Migrated to `0010`: all three landed on
    `legacy`/`active` with every limit `NULL` and all four features; usage queries returned each
    tenant's own count with zero cross-contamination; Tenant A successfully created a third branch
    post-migration with no error. Full suite (405 tests) green against this database too.
  - The real `barbershop` production database was never connected to for any write in this phase.
    It was queried read-only twice (before and after this phase's work) purely to confirm its
    `alembic_version` and database list are unchanged.
- `ruff check app tests`: clean, before and after.

### An unrelated observation from this verification

The running `barbershop` production database (container `barbershop_db`) is currently at
migration `0003` — six migrations behind this codebase (`0004`-`0009` from Phases 1-5, plus this
phase's `0010`, have not been applied to it). This phase did not touch it and does not attempt to
fix this — it is noted here only because it was directly observed while confirming production
stayed untouched, and the project owner should be aware of it before relying on any Phase 1-6
feature in that environment.

## 14. Future work (explicitly out of scope for Phase 6)

- **Payment provider integration** (Stripe/Paddle/PayPal/YooKassa/etc.), the actual future
  architecture being:

  ```
  Stripe/Paddle webhook → Payment Adapter → SubscriptionService → Subscription → Plan
                                                                        │
                                                                        ▼
                                                          Entitlements → Tenant
  ```

  Phase 6 implements everything **below** the Payment Adapter box only. The adapter's job will be
  to translate provider webhook events into calls against the *existing*
  `SubscriptionService`/`Subscription` model — `change_plan`, and new methods for
  status transitions (`mark_past_due`, `cancel`, etc.) — without changing the schema described
  here, beyond possibly adding provider-identifier columns to `Subscription` when that integration
  is actually built.
- Payment webhooks, invoices, tax/VAT, refunds, dunning/payment retries, a real grace-period
  *duration*.
- Per-tenant custom plan overrides (a tenant getting a limit different from its plan's standard
  value) — deferred; today it is strictly `Tenant → Subscription → Plan`, no override table. When
  needed, this should be an additive `TenantPlanOverride`-style table consulted by
  `LimitService`/`EntitlementService` before falling back to the plan's value, not a mutation of
  the shared `Plan`/`PlanLimit` catalog rows.
- A historical subscription/plan-change ledger beyond what `AuditLogEntry` already records.
- Multi-bot / bot-identity-resolves-to-tenant architecture (Phase 7) — not built here, but every
  billing service in this phase is constructed as `(session, tenant_id)` with no dependency on a
  process-global tenant, `ADMIN_ID`, or a Telegram-process singleton, so a future multi-bot
  dispatcher can resolve bot → tenant → subscription → entitlements without any change to this
  domain.
- A public SaaS marketing site, a SaaS admin dashboard, or expanding `SUPER_ADMIN` beyond the
  minimal dev-only plan-switch control described in §10.
