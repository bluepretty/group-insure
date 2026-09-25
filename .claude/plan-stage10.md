# Stage 10 — Closed Lapsed Policies

- [ ] Service: `close_policy` (services/policies.py) — `lapsed` → `closed` with grace guard
- [ ] API: `POST /api/policies/{policy_id}/close` — underwriter-gated, JSON
- [ ] Wire the **Close** button into `policy_list.html` (shows when the policy is `lapsed`)
- [ ] Extend smoke test (auto-lapse via overdue invoice → close → terminal; broker 403)
- [ ] Run smoke test & fix issues (1 passed)
- [ ] Commit

## Context

Stage 9 (`claude/plan-stage9.md`) wired the billing→policy bridge: an unpaid
invoice past its `due_date` lapses an active policy, and a full payment
reinstates it. The policy state machine (`services/policies.py:_ALLOWED`) already
modelled the other half of that loop — `lapsed → active | closed` — but nothing
ever triggered the `lapsed → closed` edge. So a policy that lapses (or is
reinstated and lapses again) can orbit `lapsed` forever: it is neither `active`
(no coverage, no billing effect) nor `closed` (gone). There is no way to retire
it.

This stage is the lapse task Stage 9 pointed to:

> The lapsed→closed transition (already in the machine) is intentionally left for
> the next lapse-related task — no scope creep.

It is the small, matching sibling to Stage 9: it closes the loop so that an
unresolved lapse terminates the policy rather than pinning it in limbo.

### Why a grace period

A policy lapses when an invoice goes unpaid. Lapping immediately, reinstating on
payment, is what Stage 9 built. But an underwriter should have a bounded window to
notice the lapse and either collect payment or talk to the policyholder *before*
the policy is written off as closed. Closing a policy the day after it lapses
would be too eager — and it would fight reinstatement, which is the natural
payment effect. So `close_policy` requires the policy to have been lapsed for at
least a `grace_days` window (default 30 days): a recently-lapsed policy cannot
yet be closed, an old one can. This keeps the underwriter's manual choice in the
loop while still guaranteeing the policy eventually leaves `lapsed`.

## Behavior

1. **A lapsed policy can be closed once it has been lapsed ≥ `grace_days`** (the
   window is a parameter, default 30). Before the window elapses the underwriter
   may still reinstate (the policy pays); after it, closing becomes the option.
2. **`lapsed → closed` is terminal** — the existing `_ALLOWED` map already marks
   `closed` as having no out-edges; this stage only makes the transition
   reachable and gated by the grace window.
3. **Auto-closure is deferred** — there is no background sweep to close policies
   once the grace window elapses; the underwriter closes it, as they would close
   any other administrative action. (A future stage can sweep.) This keeps Stage 10
   a thin, action-at-a-time slice consistent with the rest of the app.
4. **The grace window is measured from a policy's own `status_changed_at`** (a
   new nullable column — see below), not from `start_date`. The API never receives
   a lapse date from the client; `close_policy` compares `status_changed_at` to
   `today` to decide how long the policy has been lapsed. `updated_at` already
   exists on the model but is bumped on *every* write, so it is the wrong source
   here — `status_changed_at` is the single, status-specific timestamp.

## Design

### Service
`services/policies.py`, add:

```python
# near the top, with the other constants
GRACE_DAYS = 30  # a policy must be lapsed this long before it can be closed


def _lapsed_for(db, policy: Policy) -> int | None:
    """Days the policy has been in its current 'lapsed' status, if lapsed.

    Returns the whole-day gap from `status_changed_at` to `today`, or None if the
    policy is not currently lapsed. Uses `status_changed_at` (set by
    `change_policy_status` on every transition) as the single source of truth for
    "when did this status begin".
    """
    if policy.status != "lapsed" or policy.status_changed_at is None:
        return None
    changed = policy.status_changed_at
    tz = changed.tzinfo or dt.timezone.utc
    changed_date = changed.replace(tzinfo=None) if changed.tzinfo else changed
    days = (dt.date.today() - changed_date).days
    return max(0, days)


def close_policy(db, *, policy_id: int, today: dt.date | None = None) -> Policy:
    """Close a lapsed policy that has outlived the grace period.

    Only the `lapsed -> closed` transition is here, gated by `GRACE_DAYS`.
    Raises ValueError if the policy is unknown, not lapsed, or still inside the
    grace window; raises 400 elsewhere via the API. Logs `policy_closed`.
    """
    if today is None:
        today = dt.date.today()
    policy = db.get(Policy, policy_id)
    if policy is None:
        raise ValueError(f"Unknown policy_id: {policy_id}")
    if policy.status != "lapsed":
        raise ValueError(f"Only a lapsed policy can be closed (is '{policy.status}')")
    lapsed_days = _lapsed_for(db, policy)
    if lapsed_days is None or lapsed_days < GRACE_DAYS:
        raise ValueError(
            f"Policy {policy_id} has only been lapsed {lapsed_days} day(s); "
            f"wait until it has been lapsed {GRACE_DAYS} days before closing"
        )
    return change_policy_status(db, policy_id=policy_id, to_status="closed")
```

`_lapsed_for` is the testable seam (returns the day count for a fixture lapse
date); `close_policy` is the thin guard + `change_policy_status` call, matching
the `laps_if_overdue` shape Stage 9 left.

### `Policy.status_changed_at`
Add to `models/policy.py` a `status_changed_at: Mapped[dt.datetime | None]`
column and set it in `change_policy_status` right after it reads `policy.status`,
*before* mutating:

```python
policy.status_changed_at = dt.datetime.now(dt.timezone.utc)
policy.status = to_status
```

Set it to `None`-on-create (nullable) — a draft policy's `status_changed_at`
stays null until its first real transition; that is fine, `close_policy` only
touches lapsed policies (which necessarily transitioned from active, so the
column is populated). `create_policy` and `change_policy_status` are the only
writers.

Wait — `create_policy` sets `status="draft"` and does NOT set `status_changed_at`,
leaving it null. `policy` status transitions from draft → active → lapsed set it.
`_lapsed_for` only ever reads it for a lapsed policy, so a null value can only
occur for a policy that is lapsed without ever having its column set — impossible
for policies that reach `lapsed` through the machine. Kept nullable to avoid a
migration on an existing DB; the value is populated on first `change_policy_status`.

### API
`api/policies.py`, add under `/api/policies`:

```python
@router.post("/{policy_id}/close")
def policy_close(
    policy_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_role("manage_policies")),
) -> JSONResponse:
    from app.services.policies import close_policy
    try:
        policy = close_policy(db, policy_id=policy_id)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    return JSONResponse(content={"policy_id": policy_id, "status": policy.status})
```

Mirrors `policy_status` (400 on `ValueError`, JSON body). `close_policy` is
imported lazily so the module import stays cheap and the smoke import path
matches the other policy endpoints.

### UI
`templates/partials/policy_list.html`: in the `can_manage` block, add a **Close**
button that shows only when the policy is `lapsed` (Stage 9 already shows the
Reinstate button there). Position it after the Reinstate button, styled
`btn-outline-secondary` with a hover warning. It posts to the new close endpoint
and reloads on success:

```html
{% if can_manage and policy.status == 'lapsed' %}
... existing Reinstate button ...
<a
  href="#"
  class="btn btn-sm btn-outline-secondary"
  hx-post="/api/policies/{{ policy.id }}/close"
  hx-target="#content"
  hx-swap="innerHTML"
  hx-on::after-request="if (requestEvent.xhr.status === 200) { location.reload(); }"
  title="Close the policy once it has been lapsed for the grace period"
>Close</a>
{% endif %}
```

Only the `can_manage` branch gets the button — consistent with the existing
Reinstate button and the `manage_policies` gate on the endpoint. Minimal markup;
the button simply disappears (the policy is closed/terminal) once the transition
runs.

### RBAC
**Underwriter only (`manage_policies`)** — a policy closure is an
underwriter action, consistent with `manage_policies` and the existing
lapse-check / status endpoints. A broker is excluded (already is, by the gate).
No new permission; this is a policy-management action, not a finance-close one.

### Reports
No change to `services/reports.py`. `build_report` already reads `Policy.status`
and buckets `closed` into `policies`/`open_policies` correctly: a closed policy is
excluded from `open_policies` (live = active + lapsed) and counted in `policies`.
The new transition only changes a policy's status; the report's bucket rules are
already right.

## Testing
`api/test_smoke.py`, a new Stage 10 block appended after Stage 9 (the fixture ends
with `policy_id` active and everything paid — clean room for a lapse→close).
Two parts: a real API-driven part and a service part that injects `today`.

**(a) API-driven** — a fresh, separate policy, auto-lapse via an overdue invoice,
then assert the grace guard (400 on a too-recent close) and the broker gate (403).
No time-travel needed; a policy closed through the API is, by construction, still
inside the window.

```python
# --- Stage 10: closed lapsed policies -----------------------------------

# A second, dedicated policy for the lapse→close transition.
r = client.post(
    "/api/policies/create",
    data={"policy_number": "POL-010", "product_id": str(product_id),
          "party_id": str(party_id)},
    headers={"Authorization": f"Bearer {token}"},
)
assert r.status_code == 200, r.text
policies = client.get("/api/policies", headers={"Authorization": f"Bearer {token}"}).json()
policy10_id = next(p["id"] for p in policies if p["policy_number"] == "POL-010")

# Make it active.
r = client.post(f"/api/policies/{policy10_id}/status",
    data={"to_status": "active"},
    headers={"Authorization": f"Bearer {token}"}),
assert r.status_code == 200, r.text

# Issue an overdue invoice → auto-lapse (mirrors Stage 9).
r = client.post("/api/billing/invoices",
    data={"policy_id": str(policy10_id), "due_date": "2024-01-01"},
    headers={"Authorization": f"Bearer {token}"}),
assert r.status_code == 200, r.text

r = client.get(f"/api/policies/{policy10_id}/lapse-check",
    headers={"Authorization": f"Bearer {token}"}),
assert r.json()["status"] == "lapsed", r.json()

# Closing too early (just lapsed, inside the 30-day grace window) is refused.
r = client.post(f"/api/policies/{policy10_id}/close",
    headers={"Authorization": f"Bearer {token}"}),
assert r.status_code == 400, r.text

# The broker cannot close a policy.
r = client.post(f"/api/policies/{policy10_id}/close",
    headers={"Authorization": f"Bearer {broker_token}"}),
assert r.status_code == 403, r.text
```

**(b) Service-driven, with `today` injected** — exercises the qualify → close →
terminal logic directly (the same DI `close_policy` already exposes, matching
`laps_if_overdue`), so no real time has to pass:

```python
import datetime as _dt
from app.services.policies import GRACE_DAYS, close_policy
from app.core.database import SessionLocal as _SessionLocal

_db = _SessionLocal()
try:
    # Still inside the window: lapsed only 5 days, window is 30.
    try:
        close_policy(_db, policy_id=policy10_id, today=_dt.date.today())
        assert False, "refuse a policy inside the grace window"
    except ValueError:
        pass

    # Past the window: far-future today pushes the lapse count past 30 days.
    future = _dt.date.today() + _dt.timedelta(days=GRACE_DAYS + 5)
    closed = close_policy(_db, policy_id=policy10_id, today=future)
    assert closed.status == "closed", closed.status

    # Terminal: a second close raises.
    try:
        close_policy(_db, policy_id=policy10_id, today=future)
        assert False, "a closed policy must be terminal"
    except ValueError:
        pass
finally:
    _db.close()
```

Keep `setup_test_db` idempotent — this block is additive and the fixture still
ends with `policy_id` active.

## Scope notes
- No background sweep, no grace-timer service, no `void_policy` — those belong to
  a later lapse-related follow-up. Stage 10 is a single gated transition.
- `GRACE_DAYS` lives at module top so it is easy to find and change; it is not a
  runtime-config value in v1.
- `status_changed_at` is the only new column and is nullable, so it adds nothing
  to the create path for existing drafts and needs no migration.
