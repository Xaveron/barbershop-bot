# Platform Control Plane — Phase 8

## 1. Before / After

**Before** (Phase 1-7): "platform" access was exactly one thing — `settings.is_admin(telegram_id)`
(the `ADMIN_ID` env var), checked inline as `is_super_admin` in roughly ten admin-handler files to
unconditionally bypass every tenant `Permission` check *within whichever tenant the current bot
resolved to*. There was no concept of "the platform" distinct from "an omnipotent user of the
currently-resolved tenant," and no live way to create/list/suspend a tenant or attach a bot at
all — `TenantOnboardingService.create_tenant` was a script-only primitive, `python -m
app.register_bot` a CLI script with no live UI.

```
ADMIN_ID (env var)
    │
    ▼
settings.is_admin(telegram_id)   (checked inline, ~10 handler files, each computing it itself)
    │
    ▼
is_super_admin=True  →  AuthorizationService.has_permission(...) always True, in THIS tenant
```

**After** (Phase 8): a separate, DB-backed platform identity, authorized independently of any
tenant, computed once per update and injected the same way `staff`/`is_admin` already are.

```
Telegram update → dedicated PLATFORM_BOT_TOKEN bot (never resolves to a tenant)
    │
    ▼
BotIdentityMiddleware: is_platform_bot=True, tenant_id=None
    │
    ▼
StaffContextMiddleware: is_super_admin = PlatformAuthorizationService.is_operator(telegram_id)
    │                    (DB-backed PlatformOperator lookup, ADMIN_ID only as a self-terminating
    │                     bootstrap fallback — see §4)
    ▼
RequirePlatformOperator (is_platform_bot AND is_super_admin) → platform router
    │
    ▼
TenantManagementService / BotProvisioningService / PlatformAuthorizationService
    (all explicit tenant_id per call, all audited)
```

Tenant `Role`/`Permission`/RBAC, booking, billing, onboarding, and the scheduler are all
**unchanged underneath this** — the control plane sits beside them, not inside them.

## 2. Platform role vs tenant role

These are two independent concepts that must never be merged:

| | Tenant `Role` | Platform `PlatformRole` |
|---|---|---|
| Model | `StaffMember.role` | `PlatformOperator.role` |
| Scope | one tenant (`tenant_id` required) | none (no `tenant_id` column at all) |
| Values | `TENANT_OWNER`/`TENANT_ADMIN`/`MANAGER`/`RECEPTIONIST`/`BARBER` | `PLATFORM_ADMIN` |
| Grants | that tenant's `Permission`s (`MANAGE_STAFF`, `MANAGE_TENANT`, …) | platform operations across all tenants |
| A member of one implies the other? | **No.** A `TENANT_OWNER` is not a platform operator; a platform operator is not automatically staff anywhere. | |

`SUPER_ADMIN` was never a real value in the tenant `Role` enum and still isn't — Phase 8
deliberately keeps it that way (`app/database/models/staff.py::Role`). Platform authorization is
never granted by holding a tenant role, no matter how privileged.

## 3. Platform identity — `PlatformOperator`

`app/database/models/platform.py`, table `platform_operators`:

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `telegram_user_id` | `BigInteger`, `UNIQUE` | the *Telegram user*, not a bot — see §7 |
| `role` | native enum `platform_role` | one member today: `PLATFORM_ADMIN` |
| `is_active` | `Boolean`, default `true` | inactive = fails closed, no fallback |
| `created_at`/`updated_at` | timestamps | |

Deliberately **no `tenant_id` column** — a platform operator is not owned by any tenant
(`TenantScopedMixin` is not used here). Deliberately **no bot token column anywhere** — same rule
Phase 7 established for `TelegramBotIdentity`.

## 4. `PlatformAuthorizationService` and the ADMIN_ID bootstrap window

`app/services/platform_authorization.py::is_operator(telegram_id)`:

1. If a `PlatformOperator` row exists for this `telegram_id` and `is_active` — **authorized**.
2. Otherwise, only if **zero** `PlatformOperator` rows exist anywhere (`any_exist() == False`) and
   `telegram_id` is in the legacy `ADMIN_ID` allowlist — **authorized** (the bootstrap window).
3. Otherwise — not authorized.

This makes `ADMIN_ID` **self-terminating, not a permanent bypass**: the condition in step 2 can
only ever go from `True` to `False` (once any real `PlatformOperator` row exists — created only by
the explicit `python -m app.bootstrap_platform_admin` script, never implicitly from a live
Telegram interaction — it never reverts to `True`). Before bootstrap, `ADMIN_ID` still works
exactly as it always has, so a fresh deployment isn't locked out of its own admin tooling on day
one. After bootstrap, `ADMIN_ID` is consulted for nothing — access is 100% DB-backed, auditable,
and per-identity (individually deactivatable, unlike an env var).

`require_operator(telegram_id)` raises `PlatformAuthorizationError` (same `key, **params` shape as
`BookingError`/`AuthorizationError`/`BillingError`) when not authorized.

## 5. Wiring `is_super_admin` — no per-handler platform checks

`StaffContextMiddleware` (which already does one DB lookup per update for `staff`) computes
`data["is_super_admin"] = await PlatformAuthorizationService(session, settings).is_operator(...)`
**once per update**, the same way `is_admin`/`staff` are already injected via aiogram's DI.
`AuthorizationService.has_permission`/`.require()`/`can_access_branch`/
`resolve_accessible_branch_ids`, `RequirePermission`, `IsStaff` keep their **exact existing
signatures** (`is_super_admin: bool = False`) — only where the value comes from changed, in every
one of the ~10 admin-handler files that used to compute `settings.is_admin(...)` inline
(`admin/appointments.py`, `admin/staff.py`, `admin/menu.py`, `admin/editing.py`,
`admin/reports.py`, `admin/billing.py`, `admin/schedule.py`, `common.py`, `onboarding.py`).

The existing `common.py::_handle_inactive_tenant` bridge (an `is_super_admin` user hitting an
empty tenant auto-bootstraps as `TENANT_OWNER` via `TenantOnboardingService.ensure_owner`) is
**preserved as-is** — only the source of `is_super_admin` changed, not the mechanism.

## 6. Tenant management — `TenantManagementService`

`app/services/tenant_management.py`, not tenant-scoped by construction (`tenant_id` is an explicit
parameter per call — it manages *many* tenants). Reuses existing Phase 5/6 machinery, never
duplicates it:

| Method | Behavior |
|---|---|
| `list_tenants()` / `get_tenant(id)` | `TenantOverview` (name, slug, status, timezone, currency, branch/staff/bot counts, plan code, subscription status) via a **fixed number of aggregate queries** regardless of tenant count — no N+1 (§9). No customer data, no secrets, no bot tokens. |
| `create_tenant(name, actor)` | Delegates to `TenantOnboardingService.create_tenant` → `Tenant(status=ONBOARDING)`. Slug is auto-derived from the name (slugified + random suffix, retried up to 5× against `slug_exists`) — the live UI asks for one field, not a separate technical slug. Writes `"tenant.created"`. |
| `activate_tenant(id, actor)` | **Direct pass-through** to `TenantOnboardingService.activate()` — the exact same readiness validation Phase 5 already uses. Works for both first activation (`ONBOARDING → ACTIVE`) and reactivation (`SUSPENDED → ACTIVE`): `activate()` only checks "already ACTIVE?" + readiness, never the prior status. Platform "activate" **cannot** bypass readiness — there is no separate emergency path. |
| `suspend_tenant(id, actor)` | New (nothing suspended before Phase 8). `ACTIVE → SUSPENDED` is the real transition; already-`SUSPENDED` is an idempotent no-op; `ONBOARDING → SUSPENDED` raises `TenantLifecycleError` (not a meaningful transition). Writes `"tenant.suspended"`. |
| `ensure_owner(id, telegram_id, actor)` | Direct pass-through to `TenantOnboardingService.ensure_owner` — owner uniqueness stays DB-enforced (`uq_staff_members_tenant_id_owner`, migration `0009`), unchanged. |
| `attach_bot` / `deactivate_bot` / `activate_bot` | Thin wrappers over `BotProvisioningService` (§7) plus the matching audit write. |

`TenantLifecycleError` mirrors `BookingError`'s shape (`key, **params` — translated by whichever
handler catches it, never a hardcoded message in the service).

## 7. Bot provisioning — one implementation, two callers

`app/services/bot_identity.py::BotProvisioningService`:

```python
async def attach(self, *, tenant_id, telegram_bot_id, username) -> tuple[identity, created]:
    existing = await self.identities.get_by_bot_id(telegram_bot_id)
    if existing is not None:
        if existing.tenant_id == tenant_id:
            return existing, False          # idempotent no-op — same tenant, run again safely
        raise BotAlreadyAssignedError(...)  # reject cross-tenant reassignment
    return await self.identities.create(...), True
```

Both `python -m app.register_bot --tenant-id <uuid>` (CLI, token from `BOT_TOKEN` env var, never a
CLI argument, never logged — unchanged from Phase 7) **and** the live `/platform → Bots` UI call
this exact same service — there is no second bot-registration implementation.

`deactivate()`/`activate()` toggle `TelegramBotIdentity.is_active` symmetrically — reactivating
needs no new token since the row already exists, so this is a safe, genuinely useful toggle rather
than a one-way switch.

**Deliberately excluded from the live UI**: attaching a *new* bot by typing its token into a
Telegram chat. The CLI's environment-variable handling already meets the "secure runtime
mechanism" bar; accepting a raw token as chat text would be a strict *downgrade* — Telegram's own
message history would retain the secret even though this app never logs it. The live "Bots" screen
only lists existing identities and toggles `is_active`.

## 8. Owner bootstrap

A platform operator creates a tenant (`ONBOARDING`, no staff yet), then assigns its owner via
`ensure_owner` — a pass-through to the existing Phase 5 `TenantOnboardingService.ensure_owner`,
which creates a `StaffMember(role=TENANT_OWNER)` (no second "owner" model) and re-queries on a
race rather than trusting a prior Python-side check. Owner uniqueness is enforced by the existing
partial unique index (migration `0009`), not by application logic — a duplicate `ensure_owner` call
safely returns the existing owner instead of erroring. The same Telegram account may legitimately
own more than one tenant (no cross-tenant unique constraint was added on identity) since nothing in
the product's existing design forbids it.

## 9. Tenant listing performance

`TenantManagementService._build_overviews()` runs a **fixed 4-5 queries total** (branch-count
`GROUP BY`, staff-count `GROUP BY`, bot-count `GROUP BY`, one subscription+plan join, plus the
initial tenant `SELECT`) regardless of how many tenants are listed — never one query per tenant.
Verified by `tests/test_integration_platform.py::test_list_tenants_uses_fixed_number_of_queries`
(a `before_cursor_execute` query counter, the same pattern
`tests/test_integration_booking.py::query_counter` already established).

## 10. Live `/platform` UI — dedicated platform bot

**Why a dedicated bot, not "any tenant bot + a permission check"**: a normal tenant bot must never
be able to "magically become" a platform bot, even if a permission check has a bug. A dedicated
bot gets *structural* isolation for free — a tenant bot's updates never even reach the platform
router, regardless of who is messaging it.

Configuration: an optional `PLATFORM_BOT_TOKEN` env var. Unset = no live platform UI at all (a
legitimate minimal state — the control plane still fully exists at the service/CLI layer). When
set, `app/main.py::run()` builds this bot alongside tenant bots (independent `get_me()`
validation, same as any tenant bot) and passes its `Bot.id` into `BotIdentityMiddleware` as
`platform_bot_id`.

`BotIdentityMiddleware` recognizes it by an exact `bot.id` match (configured once at `Dispatcher`
construction): `data["is_platform_bot"] = True`, `data["tenant_id"] = None`, skipping the
`TelegramBotIdentity` lookup entirely — there is nothing to look up. `UserContextMiddleware` /
`StaffContextMiddleware` gained a small null-safety guard each (`tenant_id = data.get("tenant_id")`,
skip `User`/`StaffMember` lookups when `None`) — new, previously-impossible state, not a rewrite of
either middleware.

`RequirePlatformOperator` (`app/bot/middlewares/permissions.py`) gates the platform router:
`is_platform_bot AND is_super_admin` — **both** required, neither alone is sufficient. It filters
`app/bot/handlers/platform/` (`menu.py`: menu, tenant list, tenant detail, activate, suspend,
create; `bots.py`: list bots, toggle active) via `router.message.filter(...)` /
`router.callback_query.filter(...)` on that sub-router only.

Every callback carries a `PlatformCB(action, arg)` — `arg` is **always re-resolved server-side**
(`parse_uuid` + a real repository/service lookup) before any mutation; nothing about which button
was shown to whom is treated as authorization (§Security).

**No dynamic runtime bot registration** (same limitation Phase 7 documented for tenant bots): a
newly attached bot needs a process restart to actually start polling — `attach_bot` only updates
DB state.

## 11. Bootstrap procedure

```
python -m app.bootstrap_platform_admin
```

For every id in `settings.admin_ids` (the existing `ADMIN_ID` comma-separated list), creates a
`PlatformOperator(role=PLATFORM_ADMIN, is_active=True)` unless one already exists for that id.
Idempotent — safe to run repeatedly, only ever adds missing rows. Writes a
`"platform_operator.created"` audit entry per operator created, self-attributed
(`actor_telegram_id` = the id being bootstrapped, since there is no other meaningful actor for a
bare CLI invocation). Not required to run against production in this phase — documented here as
the procedure a deployment runs once it wants to move off the `ADMIN_ID` bootstrap window.

## 12. ADMIN_ID — what remains, what changed

| | Before Phase 8 | After Phase 8 |
|---|---|---|
| Mechanism | env var, checked inline, forever | env var, checked only until step 2 of `is_operator()` (§4) permanently closes |
| Scope of effect | bypassed tenant `Permission` checks directly | seeds exactly one thing: whether the bootstrap window (§4) is open |
| Removable? | no — deleting it broke all admin access | yes, once `bootstrap_platform_admin` has run — new deployments should still set it once, for that first run |
| Still read anywhere else? | `Settings.admin_ids`/`is_admin()` — unchanged API, now consulted from exactly one place (`PlatformAuthorizationService.is_operator`) instead of ~10 handler files | |

`ADMIN_ID` was **not deleted** (§4 of the brief explicitly forbids simply deleting it without
migrating existing behavior) — it was narrowed to a single, self-closing bootstrap path.

## 13. Security model

- **Every platform callback re-resolves its target server-side.** `PlatformCB.arg` (a tenant id or
  a Telegram bot id) is parsed and looked up fresh on every callback — never trusted because "the
  button was only shown to an operator." A forged/stale/nonexistent id fails a repository lookup
  and produces a clean "not found" alert, never a crash or a silent no-op that looks like success.
- **Platform authorization and target-tenant lookup are two separate steps**, never conflated: (1)
  is this actor a platform operator (no tenant involved at all), then (2) does the target tenant
  exist (ordinary repository lookup). A platform operator's privilege is *broader* than a tenant
  staff member's, never *less explicit* about what it's acting on.
  - Tenant `OWNER`/`ADMIN`/`MANAGER`/`RECEPTIONIST`/`BARBER` cannot reach `/platform` at all —
    structurally, their bot is never the platform bot, so `is_platform_bot` is never `True` for
    them regardless of their tenant role or `is_super_admin` status.
  - A platform operator managing Tenant A is not automatically that tenant's `OWNER`/staff member
    — `PlatformOperator` and `StaffMember` are unrelated rows; assigning an owner is a separate,
    explicit `ensure_owner` call.
  - A platform operator can manage Tenant A and Tenant B independently and without cross-
    contamination — every service call takes an explicit `tenant_id`.

## 14. Audit log

`AuditLogEntry.tenant_id` became **nullable** (previously `NOT NULL` via `TenantScopedMixin`) —
confirmed safe by grep: this table has **zero existing readers** anywhere in the codebase before
Phase 8 (write-only), so relaxing the constraint cannot break any query. Platform-level events
(no tenant context) leave `tenant_id = NULL`; tenant-scoped events continue to populate it.

| Event | Action string | tenant_id |
|---|---|---|
| Tenant created | `tenant.created` | set |
| Tenant activated | `tenant.activated` (existing, Phase 5) | set |
| Tenant suspended | `tenant.suspended` | set |
| Owner assigned | `staff.created` (existing, Phase 4/5, `details.role="tenant_owner"` — this **is** OWNER_ASSIGNED, reusing the existing action rather than duplicating it) | set |
| Bot attached | `bot.attached` | set |
| Bot deactivated | `bot.deactivated` | set |
| Bot (re)activated | `bot.activated` | set |
| Platform operator created | `platform_operator.created` | `NULL` |
| Platform operator deactivated | `platform_operator.deactivated` | `NULL` |

No bot token, password, or other secret is ever written into `details` or any audit field.
`app/register_bot.py` (the CLI) does **not** write an audit entry — a bare CLI invocation has no
meaningful Telegram "actor" to attribute; `bootstrap_platform_admin.py` does, self-attributed,
since that actor is well-defined.

## 15. Migration `0012_add_platform_operators.py`

Creates `platform_operators` (id, `telegram_user_id` unique, native enum `role`, `is_active`,
timestamps — no `tenant_id` column) and `ALTER TABLE audit_log_entries ALTER COLUMN tenant_id DROP
NOT NULL`. Migrations `0001`-`0011` are untouched; no backfill (mirrors Phase 7's
`telegram_bot_identities` — there is nothing to guess).

The `platform_role` enum is created implicitly via `op.create_table` (not an explicit
`.create(checkfirst=True)` call) — the same lesson migration `0010` already learned: doing both
would raise `DuplicateObjectError`.

**Downgrade is lossy by necessity, and this is intentional, not a bug worked around**: rows written
against the platform-only audit events (`tenant_id IS NULL`) cannot be represented in the pre-0012
`NOT NULL` schema. `downgrade()` deletes exactly those rows (`DELETE FROM audit_log_entries WHERE
tenant_id IS NULL`) before restoring the constraint — verified on a disposable scratch database:
fresh `0001→0012`, then `0012→0011→0012` (downgrade, re-upgrade), both clean.

## 16. Known limitations (honest, not swept under the rug)

- **No live UI for creating new `PlatformOperator`s or listing existing ones.** The brief's
  minimal-UI instruction (§14 of the spec) covers tenants and bots; operator management stays a
  CLI/DB-level concern (`bootstrap_platform_admin.py`, direct DB inspection) for this phase.
  Deactivating a *bot* is live; deactivating a *platform operator* is not (yet) — the service
  method (`PlatformAuthorizationService.deactivate_operator`) exists and is tested, but no
  `/platform` menu item calls it.
- **No dynamic runtime bot registration**, same as Phase 7 — a newly attached bot (via CLI or
  live UI) needs a process restart to actually start polling.
- **The pre-existing `notify_admins`/global-`ADMIN_ID`-recipient mismatch in
  `app/services/notifications.py` is unchanged.** A tenant-scoped `NotificationService` still
  alerts the *global* `ADMIN_ID` list rather than that tenant's own staff — flagged during this
  phase's audit, **not fixed**, since fixing recipient resolution is a notifications-system change
  outside this phase's explicit scope (no scheduler/notification redesign).
- **A single platform role.** `PlatformRole` has exactly one member (`PLATFORM_ADMIN`) — there is
  no read-only "platform viewer" tier. Adding one later is additive (new enum member + narrower
  permission checks), not a breaking change to this design.

## 17. Authorization matrix

| Action | Owner | Admin | Manager | Receptionist | Barber | Platform Admin |
|---|---|---|---|---|---|---|
| View own tenant | ✅ | ✅ | ✅ (own branches) | ✅ (own branches) | ✅ (own data) | ✅ |
| View other tenants | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| Create tenant | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| Suspend tenant | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| Activate tenant | ❌ (via own onboarding flow while `MANAGE_TENANT`) | ❌ (same) | ❌ | ❌ | ❌ | ✅ |
| Register/attach bot | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ (or CLI operator) |
| Deactivate bot | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| Assign tenant owner | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| Manage own staff | ✅ | ✅ (`MANAGE_STAFF`) | ❌ | ❌ | ❌ | n/a (not tenant staff) |
| Manage own branches | ✅ | ✅ (`MANAGE_BRANCHES`) | ❌ | ❌ | ❌ | n/a |
| Manage own services | ✅ | ✅ (`MANAGE_SERVICES`) | ❌ | ❌ | ❌ | n/a |
| Manage own subscription | ✅ (`MANAGE_SUBSCRIPTION`) | ✅ | ❌ | ❌ | ❌ | ✅ (inspect only, §Billing — no new billing capability) |
| Manage platform operators | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ (CLI/service-level only, §16) |

Note: `TENANT_OWNER`/`TENANT_ADMIN` hold the tenant `Permission.MANAGE_TENANT`, which lets them
progress **their own** tenant through onboarding/activation via the existing onboarding flow
(`app/bot/handlers/onboarding.py`) — this is unrelated to, and does not grant, the platform's
`activate_tenant`/`suspend_tenant` operations, which require a platform identity regardless of any
tenant role.

## 18. Failure cases

| Scenario | Result |
|---|---|
| Tenant bot receives `/platform` | `is_platform_bot` is `False` for any non-configured bot → `RequirePlatformOperator` fails → falls through to the ordinary fallback handler, never the platform menu |
| Platform bot, non-operator sends `/platform` | `RequirePlatformOperator` fails (not authorized) → same fallback, no platform menu, no information disclosed |
| Platform bot, operator, forged/nonexistent tenant id in callback | Server-side lookup returns `None` → "not found" alert, no mutation, no crash |
| Attach a bot already attached to a *different* tenant | `BotAlreadyAssignedError` → CLI exits 1 / live UI shows an error; the existing identity is untouched |
| Attach a bot already attached to the *same* tenant | No-op, `created=False`, no duplicate row, no duplicate audit entry |
| Suspend an already-`SUSPENDED` tenant | No-op, returns the tenant unchanged, no duplicate audit entry |
| Suspend an `ONBOARDING` tenant | `TenantLifecycleError` — not a meaningful transition |
| Activate a tenant that isn't ready | `OnboardingReadiness(is_ready=False, missing=[...])` returned, tenant status unchanged, no partial activation |
| Two operators bootstrap the same `ADMIN_ID` twice (`bootstrap_platform_admin` re-run) | Idempotent — existing row detected, skipped, no duplicate/`IntegrityError` |

## 19. Explicitly not done in this phase

Stripe/payments, a public web frontend, Kubernetes, Redis, OAuth/SSO, a full CRM, rewriting
booking/RBAC/billing/scheduler/onboarding internals (only reused through existing entry points),
touching migrations `0001`-`0011`, backfilling `PlatformOperator`/bot identities for existing data,
an audit-log viewer UI, accepting bot tokens through the live Telegram UI, fixing the pre-existing
`notify_admins` recipient mismatch (§16), Phase 9.
