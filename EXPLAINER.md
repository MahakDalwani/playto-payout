# Playto Payout Engine — EXPLAINER.md

## The Ledger

**Balance calculation query:**

```python
def get_balance(merchant):
    result = LedgerEntry.objects.filter(merchant=merchant).aggregate(
        total_credits=Sum('amount_paise', filter=Q(entry_type=LedgerEntry.CREDIT)),
        total_debits=Sum('amount_paise', filter=Q(entry_type=LedgerEntry.DEBIT))
    )
    total_credits = result['total_credits'] or 0
    total_debits = result['total_debits'] or 0
    return total_credits - total_debits
```

**Why this model:**
I store every transaction as an immutable LedgerEntry row — either a credit or a debit — instead of storing a running balance on the Merchant model. The balance is always derived by summing credits minus debits at the database level using a single aggregation query.

This means there is no mutable balance field that two concurrent transactions can corrupt. The balance is always correct by definition — it is a mathematical result of the ledger, not a cached number that can drift.

All amounts are stored as BigIntegerField in paise (integer). No FloatField, no DecimalField. This prevents floating point errors like 100.1 + 200.2 = 300.30000000000003.

---

## The Lock

**Exact code that prevents overdrawing:**

```python
with transaction.atomic():
    # Row-level lock on merchant row
    merchant_locked = Merchant.objects.select_for_update().get(id=merchant_id)

    # Balance calculated INSIDE the lock
    available_balance = get_balance(merchant_locked)
    held_balance = get_held_balance(merchant_locked)
    actual_available = available_balance - held_balance

    if actual_available < amount_paise:
        return Response({'error': 'Insufficient balance'}, status=400)

    # Create payout and debit entry atomically
    payout = PayoutRequest.objects.create(...)
    LedgerEntry.objects.create(
        entry_type=LedgerEntry.DEBIT,
        amount_paise=amount_paise,
        ...
    )
```

**Database primitive:** PostgreSQL `SELECT FOR UPDATE`.

When two concurrent requests arrive simultaneously for a merchant with 100 rupees trying to withdraw 60 rupees each, both enter `transaction.atomic()`. One acquires the row lock first and proceeds. The second blocks at `select_for_update()` until the first transaction commits. By then, the debit entry has been written and the balance check inside the second transaction correctly sees only 40 rupees available — so it rejects cleanly with "Insufficient balance".

This is database-level locking, not Python-level locking. Python threading locks would not protect against multiple Celery workers or multiple gunicorn processes running simultaneously.

---

## The Idempotency

**How the system recognizes a seen key:**

Every payout request requires an `Idempotency-Key` header. When a request arrives, the system checks the `IdempotencyKey` table:

```python
existing = IdempotencyKey.objects.filter(
    merchant=merchant,
    key=idempotency_key
).first()

if existing:
    if existing.is_expired():
        existing.delete()
    else:
        return Response(existing.response_body, status=existing.response_status)
```

The key, full response body, and HTTP status code are stored after every request — including failed ones (like insufficient balance). This means the second call always returns the exact same response as the first.

**What happens if the first request is in-flight when the second arrives:**

Both requests pass the initial key lookup (key not found yet). Both enter `transaction.atomic()` with `select_for_update()`. One acquires the lock first, creates the payout, and saves the idempotency key before committing. The second transaction, when it finally runs, will find the key in the table and return the cached response. The database unique constraint on `(merchant, key)` is a safety net — if somehow both transactions get past the lookup simultaneously, the second insert will raise an IntegrityError, which is caught and handled.

Keys are scoped per merchant and expire after 24 hours via the `is_expired()` check.

---

## The State Machine

**Legal transitions:**
- `pending → processing → completed`
- `pending → processing → failed`

**Illegal transitions are blocked here:**

```python
# In models.py
VALID_TRANSITIONS = {
    PENDING: [PROCESSING],
    PROCESSING: [COMPLETED, FAILED],
    COMPLETED: [],
    FAILED: [],
}

def can_transition_to(self, new_status):
    return new_status in self.VALID_TRANSITIONS.get(self.status, [])
```

In `tasks.py`, every state change checks this before proceeding:

```python
if not payout.can_transition_to(PayoutRequest.COMPLETED):
    return
```

`COMPLETED: []` and `FAILED: []` mean no transitions are allowed out of terminal states. A failed-to-completed transition returns an empty list for FAILED, so `can_transition_to(COMPLETED)` returns False and is rejected.

**Fund return is atomic with state transition:**

```python
with transaction.atomic():
    payout_locked = PayoutRequest.objects.select_for_update().get(id=payout_id)
    payout_locked.status = PayoutRequest.FAILED
    payout_locked.save()

    LedgerEntry.objects.create(
        entry_type=LedgerEntry.CREDIT,
        amount_paise=payout_locked.amount_paise,
        description=f'Refund for failed payout {payout_id}',
        ...
    )
```

Both the status change and the credit entry happen in one atomic block. Either both happen or neither does.

---

## The AI Audit

**What AI gave me (wrong):**

When I asked AI to write the balance check for concurrent payouts, it initially gave me this:

```python
# AI's version - WRONG
available_balance = get_balance(merchant)
held_balance = get_held_balance(merchant)
actual_available = available_balance - held_balance

if actual_available < amount_paise:
    return Response({'error': 'Insufficient balance'}, status=400)

payout = PayoutRequest.objects.create(...)
```

**What I caught:**

The balance check and the payout creation are two separate database operations with no lock between them. Two concurrent requests both read `actual_available = 4000 paise`, both pass the check, and both create payouts — resulting in a 8000 paise withdrawal from a 4000 paise balance. This is a classic check-then-act race condition.

**What I replaced it with:**

```python
with transaction.atomic():
    merchant_locked = Merchant.objects.select_for_update().get(id=merchant_id)
    available_balance = get_balance(merchant_locked)
    held_balance = get_held_balance(merchant_locked)
    actual_available = available_balance - held_balance

    if actual_available < amount_paise:
        return Response({'error': 'Insufficient balance'}, status=400)

    payout = PayoutRequest.objects.create(...)
    LedgerEntry.objects.create(entry_type=LedgerEntry.DEBIT, ...)
```

The fix wraps everything in `transaction.atomic()` and acquires a `SELECT FOR UPDATE` lock on the merchant row before reading the balance. Now the balance check and payout creation are a single atomic unit. The second concurrent request blocks at the lock, reads the updated balance after the first commits, and correctly rejects with insufficient funds.

---

## Architecture