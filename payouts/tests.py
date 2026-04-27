from django.test import TestCase
from django.urls import reverse
import threading
from .models import Merchant, BankAccount, PayoutRequest, LedgerEntry

class IdempotencyTest(TestCase):
    def setUp(self):
        self.merchant = Merchant.objects.create(
            name='Test Merchant',
            email='test@test.com',
        )
        self.bank = BankAccount.objects.create(
            merchant=self.merchant,
            account_holder_name='Test Merchant',
            account_number='1234567890',
            ifsc_code='HDFC0001234',
            is_primary=True,
        )
        LedgerEntry.objects.create(
            merchant=self.merchant,
            entry_type='credit',
            amount_paise=100000,
            description='Test credit',
        )

    def test_idempotency(self):
        url = reverse('create-payout', args=[self.merchant.id])
        payload = {
            'amount_paise': 1000,
            'bank_account_id': str(self.bank.id),
        }
        key = 'test-idempotency-key-123'

        r1 = self.client.post(url, payload, content_type='application/json',
                              HTTP_IDEMPOTENCY_KEY=key)
        r2 = self.client.post(url, payload, content_type='application/json',
                              HTTP_IDEMPOTENCY_KEY=key)

        # Only 1 payout should be created
        self.assertEqual(PayoutRequest.objects.count(), 1)

    def test_concurrency(self):
        url = reverse('create-payout', args=[self.merchant.id])
        payload = {
            'amount_paise': 1000,
            'bank_account_id': str(self.bank.id),
        }
        results = []

        def make_request(key):
            r = self.client.post(url, payload, content_type='application/json',
                                 HTTP_IDEMPOTENCY_KEY=key)
            results.append(r.status_code)

        t1 = threading.Thread(target=make_request, args=('key-001',))
        t2 = threading.Thread(target=make_request, args=('key-002',))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Both requests should have been handled
        self.assertEqual(len(results), 2)