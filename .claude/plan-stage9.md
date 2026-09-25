# Stage 9 — Automated Policy Lapse

**Domain:** Billing → Policy lifecycle. An underwriter's invoice that goes unpaid past its `due_date` should cause the policy to lapse, and payment to reinstate it.
**Connects:** Stage 1 (policy state machine) × Stage 6 (billing).
**Spec owner:** Peter. This doc is a proposal; implement only after approval.

## Why

The policy state machine (`services/policies.py:19`) already models `active → lapsed → active`, but nothing ever triggers the transitions — the enum is dead code. Billing and policies live on opposite sides of the app with no bridge. This stage wires them: the money side now drives the coverage side, turning a long-standing unpaid invoice into a visible policy-lapse state and payment into reinstatement. It is the first cross-domain behavior and the natural endpoint of the billing domain.

The scope is deliberately small and self-contained: the two transitions above plus the "reinstatement is the natural payment effect" detail. It does not touch premiums, coverage, or the financial close (Stage 10). The lapsed→closed transition (already in the machine) is intentionally left for the next lapse-related task — no scope creep.

## Behavior

1. **Unpaid invoice past due → policy lapses.** For an `active` policy that has an outstanding (unpaid) invoice whose `due_date` has passed, transition `active → lapsed`.
2. **Full payment → reinstatement.** When a payment fully settles a policy's outstanding invoice (`paid_amount >= total_amount`), transition `lapsed → active`. If the policy was still `active`, payment is a no-op on status (an active policy paying an invoice does not lapse — it never was).
3. **New invoice while lapsed → active.** Issuing an invoice for a `lapsed` policy transitions it back to `active` (the policyholder has paid again and the underwriter is billing the new cycle).
4. A lapsed policy is simply not `active` in reports; `open_policies` (active + lapsed) still counts it as live, matching the existing bucket definition.

## Design

### New service function
`services/policies.py`:

```python
def laps_if_overdue(db, *, policy_id: int, today: dt.date | None = None) -> Policy | None:
    """Lap an active policy with an unpaid invoice past due. No-op if not due."""
```

- `today` defaults to `date.today()` (dependency injection for testability).
- Finds the outstanding invoice (`_outstanding_invoice`), checks `due_date` if present.
- If active AND overdue: `change_policy_status(policy_id, "lapsed")`, log `policy_lapse_invoice_overdue`.
- Returns the policy if changed, else `None`.
- Only the `active → lapsed` transition is enforced here; the policy machine already blocks other invalid transitions.
- `change_policy_status` is the single source of truth for transition validation and logging — this function only decides *whether* to call it, so `record_log` is reused and `policy_status_change` (the existing audit action) is the only action written.

### Reinstatement on payment
`services/payments.py` `record_payment`, full-payment path only (matching existing `_reconcile_invoice`), after `_reconcile`:

```python
if invoice.status == "paid" and invoice.policy_id is not None:
    laps_if_overdue(db, policy_id=invoice.policy_id)
```

- `record_payment`'s signature is keyword-only (`*`), so passing an unused `payment_invoice_id=None` to `record_payment` is harmless — the reinstatement is handled here, not via the arg. The existing `record_payment` call at `billing.py:181` is unchanged.
- Running on full-payment only: a partial payment leaves the invoice `partially_paid`, which correctly leaves the policy alone, and avoids the "pay 0.01 then pay the rest" double-transition edge.

### Reinstatement on issue
`services/invoices.py` `create_invoice`, before `db.add(invoice)`:

```python
if policy.status == "lapsed":
    change_policy_status(db, policy_id=policy_id, to_status="active")
    policy = db.get(Policy, policy_id)
```

- The existing `create_invoice` already reloads the policy after `refresh_policy_premium`, so `policy.status` is current here.
- `create_invoice`'s signature is keyword-only (`*`), so passing an unused `policy_reinstated=True` is harmless — the reinstatement is handled here, not via the arg. The existing `create_invoice` call at `billing.py:150` is unchanged.

### API
`api/policies.py`: add `GET /{policy_id}/lapse-check`, `manage_policies` (underwriter only):

```python
@router.get("/{policy_id}/lapse-check")
def policy_lapse_check(policy_id, db, _: None = Depends(require_role("manage_policies"))):
    policy = laps_if_overdue(db, policy_id=policy_id)
    if policy is None:
        return JSONResponse(content={"policy_id": policy_id, "status": "active", "lapsed": False})
    return JSONResponse(content={"policy_id": policy_id, "status": "lapsed", "lapsed": True})
```

Existing billing endpoints (`api/billing.py`) unchanged — they keep calling `record_payment`/`create_invoice`, now with the reinstatement side effect.

### UI
`templates/partials/policy_list.html`: when the current user has `manage_policies`, show the current status as an interactive control. If the policy is `active` and overdue, offer a "Lapse policy" button (`hx-get="/api/policies/{id}/lapse-check"`); if `lapsed`, offer "Reinstate" and show the outstanding invoice. The premium button stays. Minimal markup, consistent with the existing partial.

## RBAC / access control
- **Underwriters only** (`manage_policies`) — consistent with the policy status endpoint and policy management scope. A policy lapse is an underwriter action, not a financial-close action.
- Existing `broker` (no `manage_policies`) is excluded.
- Reinstatement and lapse-trigger are side effects of existing billing actions; `manage_billing` (underwriter-only) is already the gate, no new permission needed.

## Testing
`api/test_smoke.py`, Stage 9 section:

- Reuse the underwriter `token`.
- Issue a new invoice for the active policy (the fixture's prior invoice is paid, so this is allowed):

  ```python
  r = client.post("/api/billing/invoices", data={"policy_id": str(policy_id),
      "due_date": "2024-01-01"}, headers=...)
  ```

- Verify the policy lapses: `GET /api/policies` → policy `status == "lapsed"`.
- Lapse-check returns `lapsed: true`:

  ```python
  r = client.get(f"/api/policies/{policy_id}/lapse-check", headers=...)
  assert r.json()["lapsed"] is True
  ```

- Pay the outstanding invoice in full:

  ```python
  r = client.post(f"/api/billing/invoices/{inv['id']}/payments",
      data={"amount": "10.00"}, headers=...)
  ```

- Verify reinstatement: `GET /api/policies` → `status == "active"`.

Broker cannot lapse: `GET /api/policies/{id}/lapse-check` with `broker_token` → 403. (Smoke ends here; Stage 8's report/broker checks remain valid.)

## Scope notes
- Reinstatement is the payment effect. No `void_payment`/partial payment effects, no lapsed→closed, no premium interaction — those belong to the next lapse-related stage, not Stage 9.
- Reports already count lapsed policies under `open_policies`; nothing in `services/reports.py` changes.
