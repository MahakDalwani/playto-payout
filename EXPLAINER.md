# Playto Payout Engine — Technical Explainer

## What This System Does
A backend payout engine that allows merchants to request payouts from their available balance. It handles balance tracking via a ledger system, ensures no duplicate payouts via idempotency keys, and processes payouts asynchronously via Celery workers.

## Architecture
React Frontend → Django REST API → PostgreSQL
                                 → Celery Worker (background jobs)
                                 → Redis (job queue)

## Key Design Decisions

### 1. Ledger-Based Accounting
Instead of storing a single balance number on the Merchant model, every transaction is recorded as a LedgerEntry (credit or debit). The available balance is calculated by summing all entries. This gives a full audit trail and makes it impossible to lose transaction history.

### 2. Idempotency Keys
Every payout request requires a unique Idempotency-Key header. If the same key is sent twice, the second request returns the same response as the first without creating a duplicate payout. This protects against network retries and double-clicks.

### 3. Asynchronous Processing
Payout requests are created instantly (status: pending) and processed in the background via Celery. This means the API responds fast and the heavy work happens asynchronously.

### 4. Status State Machine
Payouts follow a strict transition: pending → processing → completed/failed. Invalid transitions are rejected, preventing data corruption.

## API Endpoints
- `GET /api/v1/merchants/` — List all merchants
- `GET /api/v1/merchants/{id}/` — Merchant dashboard with balance and history
- `POST /api/v1/merchants/{id}/payouts/` — Create payout request
- `GET /api/v1/merchants/{id}/payouts/{payout_id}/` — Check payout status

## Models
- **Merchant** — name, email
- **BankAccount** — linked to merchant, stores account details
- **LedgerEntry** — every credit/debit transaction
- **PayoutRequest** — payout with status tracking
- **IdempotencyKey** — stores key + response to prevent duplicates

## What I Would Improve With More Time
1. Add webhook notifications when payout status changes
2. Add rate limiting per merchant
3. Add retry logic with exponential backoff in Celery tasks
4. Add more comprehensive test coverage
5. Add pagination to ledger and payout history
6. Move sensitive config to environment variables