import uuid
from django.db import transaction
from django.db.models import Sum, Q
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import Merchant, BankAccount, LedgerEntry, PayoutRequest, IdempotencyKey
from .serializers import PayoutRequestSerializer, LedgerEntrySerializer, MerchantSerializer, BankAccountSerializer


def get_balance(merchant):
    """Calculate balance at DB level - never in Python"""
    result = LedgerEntry.objects.filter(merchant=merchant).aggregate(
        total_credits=Sum('amount_paise', filter=Q(entry_type=LedgerEntry.CREDIT)),
        total_debits=Sum('amount_paise', filter=Q(entry_type=LedgerEntry.DEBIT))
    )
    total_credits = result['total_credits'] or 0
    total_debits = result['total_debits'] or 0
    return total_credits - total_debits


def get_held_balance(merchant):
    """Amount held in pending/processing payouts"""
    result = PayoutRequest.objects.filter(
        merchant=merchant,
        status__in=[PayoutRequest.PENDING, PayoutRequest.PROCESSING]
    ).aggregate(total=Sum('amount_paise'))
    return result['total'] or 0


@api_view(['GET'])
def merchant_list(request):
    """Get all merchants"""
    merchants = Merchant.objects.all()
    serializer = MerchantSerializer(merchants, many=True)
    return Response(serializer.data)


@api_view(['GET'])
def merchant_dashboard(request, merchant_id):
    """Get merchant balance, ledger, payouts"""
    try:
        merchant = Merchant.objects.get(id=merchant_id)
    except Merchant.DoesNotExist:
        return Response({'error': 'Merchant not found'}, status=404)

    available_balance = get_balance(merchant)
    held_balance = get_held_balance(merchant)

    ledger_entries = LedgerEntry.objects.filter(
        merchant=merchant
    ).order_by('-created_at')[:20]

    payouts = PayoutRequest.objects.filter(
        merchant=merchant
    ).order_by('-created_at')[:20]

    bank_accounts = BankAccount.objects.filter(merchant=merchant)

    return Response({
        'merchant': MerchantSerializer(merchant).data,
        'available_balance_paise': available_balance,
        'held_balance_paise': held_balance,
        'total_balance_paise': available_balance + held_balance,
        'ledger_entries': LedgerEntrySerializer(ledger_entries, many=True).data,
        'payouts': PayoutRequestSerializer(payouts, many=True).data,
        'bank_accounts': BankAccountSerializer(bank_accounts, many=True).data,
    })


@api_view(['POST'])
def create_payout(request, merchant_id):
    """Create a payout request with idempotency and concurrency safety"""
    try:
        merchant = Merchant.objects.get(id=merchant_id)
    except Merchant.DoesNotExist:
        return Response({'error': 'Merchant not found'}, status=404)

    # Check idempotency key
    idempotency_key = request.headers.get('Idempotency-Key')
    if not idempotency_key:
        return Response({'error': 'Idempotency-Key header is required'}, status=400)

    # Check if we have seen this key before
    existing = IdempotencyKey.objects.filter(
        merchant=merchant,
        key=idempotency_key
    ).first()

    if existing:
        if existing.is_expired():
            existing.delete()
        else:
            # Return exact same response as before
            return Response(existing.response_body, status=existing.response_status)

    # Validate request body
    amount_paise = request.data.get('amount_paise')
    bank_account_id = request.data.get('bank_account_id')

    if not amount_paise or not bank_account_id:
        return Response({'error': 'amount_paise and bank_account_id are required'}, status=400)

    if amount_paise <= 0:
        return Response({'error': 'amount_paise must be positive'}, status=400)

    try:
        bank_account = BankAccount.objects.get(id=bank_account_id, merchant=merchant)
    except BankAccount.DoesNotExist:
        return Response({'error': 'Bank account not found'}, status=404)

    # CRITICAL: Atomic transaction with row-level lock
    try:
        with transaction.atomic():
            # Lock the merchant's ledger rows to prevent race conditions
            # SELECT FOR UPDATE - no other transaction can touch these rows
            merchant_locked = Merchant.objects.select_for_update().get(id=merchant_id)

            # Calculate available balance INSIDE the lock
            available_balance = get_balance(merchant_locked)
            held_balance = get_held_balance(merchant_locked)
            actual_available = available_balance - held_balance

            if actual_available < amount_paise:
                response_body = {
                    'error': 'Insufficient balance',
                    'available_paise': actual_available,
                    'requested_paise': amount_paise
                }
                response_status = 400

                # Save idempotency key even for failures
                IdempotencyKey.objects.create(
                    merchant=merchant,
                    key=idempotency_key,
                    response_body=response_body,
                    response_status=response_status
                )
                return Response(response_body, status=response_status)

            # Create the payout
            payout = PayoutRequest.objects.create(
                merchant=merchant,
                bank_account=bank_account,
                amount_paise=amount_paise,
                status=PayoutRequest.PENDING
            )

            # Create debit ledger entry to hold funds
            LedgerEntry.objects.create(
                merchant=merchant,
                entry_type=LedgerEntry.DEBIT,
                amount_paise=amount_paise,
                description=f'Payout request {payout.id}',
                payout=payout
            )

            response_body = PayoutRequestSerializer(payout).data
            response_body = dict(response_body)
            response_body['id'] = str(response_body['id'])
            response_body['bank_account'] = str(response_body['bank_account'])
            response_status = 201

            # Save idempotency key
            IdempotencyKey.objects.create(
                merchant=merchant,
                key=idempotency_key,
                response_body=response_body,
                response_status=response_status
            )

            # Trigger background worker
            from .tasks import process_payout
            process_payout.delay(str(payout.id))

            return Response(response_body, status=response_status)

    except Exception as e:
        return Response({'error': str(e)}, status=500)


@api_view(['GET'])
def payout_status(request, merchant_id, payout_id):
    """Get status of a specific payout"""
    try:
        payout = PayoutRequest.objects.get(id=payout_id, merchant__id=merchant_id)
    except PayoutRequest.DoesNotExist:
        return Response({'error': 'Payout not found'}, status=404)

    return Response(PayoutRequestSerializer(payout).data)