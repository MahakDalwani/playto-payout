import random
import time
from celery import shared_task
from django.db import transaction
from django.utils import timezone
from .models import PayoutRequest, LedgerEntry


@shared_task(bind=True, max_retries=3)
def process_payout(self, payout_id):
    """Process a payout request with simulated bank settlement"""
    try:
        payout = PayoutRequest.objects.get(id=payout_id)
    except PayoutRequest.DoesNotExist:
        return

    # Check valid transition to processing
    if not payout.can_transition_to(PayoutRequest.PROCESSING):
        return

    # Move to processing
    payout.status = PayoutRequest.PROCESSING
    payout.attempts += 1
    payout.save()

    # Simulate bank response
    # 70% success, 20% fail, 10% hang
    outcome = random.random()

    if outcome < 0.70:
        # SUCCESS
        with transaction.atomic():
            payout_locked = PayoutRequest.objects.select_for_update().get(id=payout_id)

            if not payout_locked.can_transition_to(PayoutRequest.COMPLETED):
                return

            payout_locked.status = PayoutRequest.COMPLETED
            payout_locked.completed_at = timezone.now()
            payout_locked.save()

    elif outcome < 0.90:
        # FAILURE - return funds atomically
        with transaction.atomic():
            payout_locked = PayoutRequest.objects.select_for_update().get(id=payout_id)

            if not payout_locked.can_transition_to(PayoutRequest.FAILED):
                return

            payout_locked.status = PayoutRequest.FAILED
            payout_locked.save()

            # Return funds to merchant
            LedgerEntry.objects.create(
                merchant=payout_locked.merchant,
                entry_type=LedgerEntry.CREDIT,
                amount_paise=payout_locked.amount_paise,
                description=f'Refund for failed payout {payout_id}',
                payout=payout_locked
            )

    else:
        # HANG - retry with exponential backoff
        if payout.attempts >= 3:
            # Max retries reached - mark as failed and return funds
            with transaction.atomic():
                payout_locked = PayoutRequest.objects.select_for_update().get(id=payout_id)
                payout_locked.status = PayoutRequest.FAILED
                payout_locked.save()

                LedgerEntry.objects.create(
                    merchant=payout_locked.merchant,
                    entry_type=LedgerEntry.CREDIT,
                    amount_paise=payout_locked.amount_paise,
                    description=f'Refund for stuck payout {payout_id}',
                    payout=payout_locked
                )
        else:
            # Retry with exponential backoff
            raise self.retry(countdown=2 ** payout.attempts)