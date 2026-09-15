# Bot Identity Architecture — Phase 7

## 1. Before / After

**Before** (Phase 1-6.5): one process resolved one arendator once, at startup, and used it for
every update for the process's entire lifetime.

```
process start
    │
    ▼
resolve_default_tenant_id()   (app/database/tenants.py — oldest tenant row, or create one)
    │
    ▼
dispatcher["tenant_id"] = tenant_id     (aiogram workflow data — same value forever)
    │
    ▼
every update, every handler
```

This was a deliberate, documented transitional shortcut (`docs/TENANT_ONBOARDING_DESIGN.md` §14) —
correct for "one process serves exactly one shop," structurally incapable of serving two.

**After** (Phase 7): the tenant is resolved fresh, per update, from *which Telegram bot* received
it — not from anything the process decided once at boot.

```
incoming Telegram update
    │
    ▼
actual Bot instance for this update      (aiogram-native: data["bot"], always correct even
    │                                      with multiple bots polling in one process)
    ▼
TelegramBotIdentity lookup (by Bot.id)   (app/services/bot_identity.py::BotIdentityResolver)
    │
    ▼
tenant_id                                 (per-update, via BotIdentityMiddleware)
    │
    ▼
dispatcher/application context → handlers/services/repositories   (unchanged — every service
                                                                     already took tenant_id as
                                                                     an explicit parameter)
```

One process can now poll any number of `Bot` instances; each bot belongs to exactly one tenant;
a tenant may own more than one bot.

## 2. Model — `TelegramBotIdentity`

`app/database/models/bot_identity.py`, table `telegram_bot_identities`:

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `tenant_id` | UUID, FK → `tenants.id`, `ON DELETE CASCADE` | tenant-owned (`TenantScopedMixin`) |
| `telegram_bot_id` | `BigInteger` | Telegram's numeric bot id — **not** the token, **not** the username |
| `username` | `String(64)`, nullable | display/logging only — see §3 |
| `is_active` | `Boolean`, default `true` | a plain on/off flag, matching `Barber.is_active`/`Service.is_active`'s existing convention (not a multi-state enum — there's no third state to model) |
| `created_at`/`updated_at` | timestamps | |

**The one invariant this table exists to enforce**: `UniqueConstraint(telegram_bot_id)` — global,
not `(tenant_id, telegram_bot_id)`. A bot can belong to at most one tenant; a tenant can own many
bots. No raw bot token column exists anywhere in this schema (§8).

## 3. Why the Telegram bot ID, never a Telegram user ID

A Telegram *user* ID (`message.from_user.id`, a callback's `from_user.id`, an FSM-stored id) is
**never** used to resolve a tenant — a customer, staff member, or the platform admin's Telegram
account means nothing about which shop they're talking to; only *which bot they sent the message
to* does. This is why `TelegramBotIdentity` keys off `telegram_bot_id`, obtained from
`Bot.id`/`getMe()`, never from `username` (Telegram usernames can be changed by their owner at any
time; the numeric id cannot) and never from any user-supplied data.

## 4. Runtime resolution — `BotIdentityMiddleware`

`app/bot/middlewares/bot_identity.py`, inserted into the existing outer-middleware chain (built in
`app/main.py::build_dispatcher`) at exactly one new point:

```
ThrottlingMiddleware → PrivateChatOnlyMiddleware → DatabaseMiddleware
    → BotIdentityMiddleware (NEW)   →   UserContextMiddleware → StaffContextMiddleware
```

It must run after `DatabaseMiddleware` (needs `data["session"]`) and before
`UserContextMiddleware` (which already reads `data["tenant_id"]` — unchanged since Phase 1). No
other middleware moved.

It reads `bot: Bot = data["bot"]` — aiogram itself guarantees this is the exact `Bot` instance that
received the current update, even when several bots are being polled concurrently by the same
`Dispatcher` (verified directly against aiogram 3.31's source: `Dispatcher.feed_update` builds each
update's middleware data as `{"dispatcher": self, **self.workflow_data, **kwargs, "bot": bot}` —
the per-call `bot` always wins over anything set once at dispatcher-build time). `Bot.id` is parsed
client-side from the token (`Bot(token="123456789:...").id == 123456789`, no network call) — this
is safe to use on the per-update hot path specifically because every `Bot` object was already
confirmed live via one `await bot.get_me()` call at process startup (`app/main.py::_validate_bots`)
before it's ever handed to the dispatcher; nothing here "trusts a token" blindly.

Three outcomes:

- **Unknown `bot.id`** (no `TelegramBotIdentity` row): logged at `WARNING`, the update is dropped
  (`return None` — the same "stop the middleware chain, no handler runs" pattern
  `PrivateChatOnlyMiddleware` already uses for group chats). No reply is sent — we don't know what
  shop to speak for, so silence is the only safe default.
- **Known but `is_active=False`**: same treatment, a distinguishable log line.
- **Known and active**: `data["tenant_id"] = identity.tenant_id`, and the update proceeds exactly
  as it always has.

There is no default-tenant fallback anywhere in this path, and no process-wide mutable tenant
state survives this phase — `resolve_default_tenant_id()` still exists (harmless, still tested)
but nothing in the runtime request path calls it anymore.

## 5. Security invariants

- **Nothing user-supplied can select a tenant.** `callback_data` factories
  (`app/bot/keyboards/callbacks.py`) and FSM state classes never carried a `tenant_id` field even
  before this phase (confirmed by grep) — there was nothing to remove. The *only* input to tenant
  resolution is `bot.id`, which the user cannot influence (it's a property of which bot they
  messaged, fixed the moment `@BotFather` issues a token).
- **Every existing tenant-ownership check downstream is unchanged and still authoritative.**
  `TelegramBotIdentity` decides *which* tenant an update belongs to; it does not replace or weaken
  any Phase 1-4 IDOR/ownership check (`BranchRepository`/`AppointmentRepository`/etc. still filter
  by `tenant_id` on every query) or Phase 2 RBAC check. A forged `appointment_id`/`barber_id`/etc.
  in a callback is still rejected by the same tenant-scoped repository lookups as before — bot
  identity resolution happens *before* any handler runs, RBAC/ownership checks happen *inside* the
  handler exactly as before.
- **Staff and RBAC compose correctly across bots.** `StaffContextMiddleware` resolves
  `StaffRepository(session, tenant_id).get_by_telegram_id(...)` using the `tenant_id` that
  `BotIdentityMiddleware` just set — a Telegram account that is `TENANT_OWNER` in Tenant A and has
  no staff row in Tenant B sees the admin button through Tenant A's bot and does not through Tenant
  B's bot, tested directly in `tests/test_integration_bot_identity.py`.
- **`ADMIN_ID` is not a tenant identity and does not grant cross-tenant access.**
  `Settings.admin_ids` is unchanged, process-wide config — but since tenant is now resolved
  per-bot, a platform admin's elevated rights apply only within whichever tenant the bot they're
  currently talking to resolves to. There is no code path where being in `ADMIN_ID` reveals or
  mutates a *different* tenant than the one the current bot belongs to.
- **`Customer`/`User` stays tenant-scoped, per the existing `(tenant_id, telegram_id)` unique
  constraint** (Phase 1, migration `0004`) — the same Telegram account messaging two different
  bots (two different tenants) correctly creates two independent `User` rows, never one shared
  customer record. Verified directly in `tests/test_integration_bot_identity.py`.

## 6. Provisioning — `app/register_bot.py`

```
python -m app.register_bot --tenant-id <uuid>
```

The only controlled way a `telegram_bot_identities` row is ever created. The bot token is read
from the `BOT_TOKEN` environment variable (via `Settings`, exactly as the main process reads it) —
**never** accepted as a CLI argument and **never** printed or logged (§8).

Flow: `Bot(token=...)` → `await bot.get_me()` (the one live, authoritative Telegram API call this
whole phase makes — confirms the token is valid and returns Telegram's own `id`/`username`, not a
value this project computed) → verify `--tenant-id` resolves to a real `Tenant`
(`TenantRepository.get`) → look up any existing identity for that `bot.id`:

- **No existing row** → create it, `is_active=True`.
- **Existing row, same tenant** → no-op ("idempotent" — running the command again is safe).
- **Existing row, a *different* tenant** → **refused**, with a clear error. Reassigning a bot to a
  different tenant is exactly the kind of destructive action a mistyped `--tenant-id` should never
  be able to trigger; doing that on purpose is a manual, explicit database operation, not something
  this script automates.

## 7. Existing-tenant migration strategy

Migration `0011_add_telegram_bot_identities.py` creates the table **empty** — no backfill, no
guessed mapping for tenants that existed before Phase 7. This is deliberate: this project cannot
know which bot token an operator has actually been using for a given tenant, and guessing wrong
would silently misroute a real shop's traffic.

**Consequence that matters for deployment**: after Phase 7's code ships, the existing bot
(whatever `BOT_TOKEN` a deployment already has configured) will not respond to anything —
`BotIdentityMiddleware` will see an unrecognized `bot.id` on every single update and drop it
silently — **until `python -m app.register_bot --tenant-id <the existing tenant's id>` is run
once**, exactly mirroring how Phase 6.5 required migrating the database before the new application
build could start. Find the existing tenant's id with:

```sql
SELECT id, name, slug FROM tenants ORDER BY created_at LIMIT 1;
```

(the same "oldest tenant" query `resolve_default_tenant_id`/`TenantRepository.get_default()` used
to run automatically — now a one-time manual lookup instead of an automatic runtime fallback).

## 8. Bot token security

No bot token is ever stored in this database, in any column, in any table. `TelegramBotIdentity`
stores only `telegram_bot_id` (a public-ish numeric identifier, not a secret) and `username`
(also public). Tokens live exactly where they already did — `BOT_TOKEN`/`BOT_TOKENS` in the
process environment / `.env` — and this phase adds no new place a token could leak to: not logs
(`BotIdentityMiddleware`/`_validate_bots` log `bot.id`, never the token), not `callback_data`, not
FSM state, not exceptions, not test output (`tests/test_integration_bot_identity.py` never
constructs a real token — its fake tokens are `<numeric-id>:AAHdq...` test fixtures that never
touch a real Telegram server), not this documentation, not `README.md`/`.env.example` (which show
the token *shape*, as they already did before this phase, never a real value). No external secret
manager was introduced — `BOT_TOKEN`/`BOT_TOKENS` staying in environment configuration is the
extension point a future secret-manager integration would replace, without needing any change to
`TelegramBotIdentity` or the resolver.

## 9. Lifecycle interaction (`TenantStatus`, bot `is_active`)

Two independent on/off axes, deliberately not merged into one:

- **`TelegramBotIdentity.is_active`** — is this *bot* currently allowed to serve any traffic at
  all. Set to `false` to take one bot offline (e.g., a compromised token before it's rotated)
  without touching the tenant or its other bots.
- **`Tenant.status`** (`ONBOARDING`/`ACTIVE`/`SUSPENDED`, Phase 5, unchanged) — is this *tenant*
  ready to serve normal customer traffic. `BotIdentityMiddleware` stops at supplying a correct,
  active `tenant_id`; it does not re-implement or duplicate the existing lifecycle branching in
  `app/bot/handlers/common.py::cmd_start` (`if tenant.status != TenantStatus.ACTIVE:
  await _handle_inactive_tenant(...)`), which continues to run exactly as it did before this phase
  once a correct `tenant_id` reaches it — verified in
  `tests/test_integration_bot_identity.py::test_suspended_tenant_blocks_normal_menu`.

An inactive bot identity is a hard stop before any handler runs (§4); a suspended tenant is a soft,
existing, product-level state a bot identity can be perfectly active and still route into.

## 10. Multi-bot process architecture

One `Dispatcher`, N `Bot` instances — this is aiogram 3's own native multi-bot support
(`dispatcher.start_polling(*bots)`, `dispatcher.feed_update(bot, update)`, both verified directly
against the installed aiogram 3.31), not a custom multi-process or multi-loop scheme. Each
configured token (`BOT_TOKEN` plus the optional comma-separated `BOT_TOKENS`, §11) becomes one
`Bot` object; `app/main.py::_validate_bots` confirms each independently via `get_me()` — a token
that fails validation is logged and excluded from polling/scheduling, it does not take down the
other tenants' bots (the whole process only refuses to start if *zero* bots validate, matching
today's single-bot fatal-on-bad-token behavior for the "nothing to serve" case).

## 11. Configuration

`BOT_TOKEN` remains required, unchanged — a single-bot deployment needs zero configuration
changes for this phase. An optional `BOT_TOKENS` (comma-separated *additional* tokens, parsed the
same way `ADMIN_ID`'s comma-separated list already is) exists for a genuine multi-bot deployment;
`Settings.bot_tokens_all` returns the deduplicated union. No service discovery, no dynamic config
source, no external configuration store was introduced.

## 12. Scheduler routing

`app/scheduler/jobs.py` (`send_due_reminders`, `complete_past_appointments`,
`schedule_return_reminders`) is **unchanged** — every job function already took an explicit
`tenant_id` (and `send_due_reminders` an explicit `bot`) as a parameter, exactly as if it had
always been written for a multi-tenant world. Only `app/scheduler/setup.py::build_scheduler`
changed: instead of registering one job-trio for one hardcoded `(bot, tenant_id)` pair, it now
takes `bots_by_tenant: dict[tenant_id, Bot]` and registers the same three jobs **once per tenant**,
each with a unique APScheduler job id (`f"send_due_reminders:{tenant_id}"`, etc.) and that tenant's
own bot/tenant_id in its kwargs. `bots_by_tenant` is built once at startup
(`app/main.py::_resolve_bots_by_tenant`) by resolving each validated bot's identity: a tenant with
more than one active bot uses its **earliest-registered** identity for scheduler-originated
reminders (documented simplification, §13) — this never affects *reply*-shaped interactions, which
always go out through whichever bot the customer actually messaged, only which bot fires a
scheduled reminder that wasn't triggered by an incoming message.

## 13. Known limitations (honest, not swept under the rug)

- **A tenant with multiple active bots gets scheduler-originated reminders through only one of
  them** (the earliest-registered) — chosen as the simplest deterministic rule rather than
  building "which bot did this customer/appointment originate from" tracking, which would require
  a new column on `User`/`Appointment` and is a larger change than this phase's brief asked for.
  Reply-shaped messages (booking confirmations, cancellations, admin actions) are unaffected — they
  always use the bot the customer/staff member actually messaged.
- **No dynamic runtime bot registration.** `app/register_bot.py` writing a new row does not make a
  *running* process start polling that bot or scheduling its reminders — both are computed once at
  process startup (`_validate_bots`/`_resolve_bots_by_tenant`/`build_scheduler`). A newly
  provisioned bot needs a process restart to actually come online. Adding hot-reload is explicitly
  out of scope for this phase.
- **No per-bot admin scoping beyond today's single `Settings.admin_ids` list** — the platform
  operator allowlist is still one process-wide list, not something configured per bot/tenant; §5
  explains why this remains safe (it never crosses the tenant boundary a bot resolves to), but a
  true multi-operator SaaS would eventually want this to be per-tenant data, not environment
  config.
- **`Bot.id`'s advisory-lock key space** (`app/utils/locks.py::advisory_lock_key`, Phase 6) is
  unrelated and untouched — bot identity resolution does not use or contend with it.
