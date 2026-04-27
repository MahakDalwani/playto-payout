from django.core.management.base import BaseCommand
from django.db import transaction
from payouts.models import Merchant, BankAccount, LedgerEntry


class Command(BaseCommand):
    help = 'Seed the database with test merchants and data'

    def handle(self, *args, **kwargs):
        self.stdout.write('Seeding database...')

        with transaction.atomic():
            # Create Merchant 1
            merchant1, _ = Merchant.objects.get_or_create(
                email='rahul@agency.com',
                defaults={'name': 'Rahul Sharma'}
            )
            BankAccount.objects.get_or_create(
                merchant=merchant1,
                account_number='1234567890',
                defaults={
                    'ifsc_code': 'HDFC0001234',
                    'account_holder_name': 'Rahul Sharma',
                    'is_primary': True
                }
            )
            # Add credits for merchant1
            LedgerEntry.objects.get_or_create(
                merchant=merchant1,
                description='Payment from Client A',
                defaults={
                    'entry_type': LedgerEntry.CREDIT,
                    'amount_paise': 500000  # 5000 INR
                }
            )
            LedgerEntry.objects.get_or_create(
                merchant=merchant1,
                description='Payment from Client B',
                defaults={
                    'entry_type': LedgerEntry.CREDIT,
                    'amount_paise': 300000  # 3000 INR
                }
            )

            # Create Merchant 2
            merchant2, _ = Merchant.objects.get_or_create(
                email='priya@freelancer.com',
                defaults={'name': 'Priya Singh'}
            )
            BankAccount.objects.get_or_create(
                merchant=merchant2,
                account_number='9876543210',
                defaults={
                    'ifsc_code': 'ICIC0009876',
                    'account_holder_name': 'Priya Singh',
                    'is_primary': True
                }
            )
            LedgerEntry.objects.get_or_create(
                merchant=merchant2,
                description='Payment from Client X',
                defaults={
                    'entry_type': LedgerEntry.CREDIT,
                    'amount_paise': 750000  # 7500 INR
                }
            )
            LedgerEntry.objects.get_or_create(
                merchant=merchant2,
                description='Payment from Client Y',
                defaults={
                    'entry_type': LedgerEntry.CREDIT,
                    'amount_paise': 250000  # 2500 INR
                }
            )

            # Create Merchant 3
            merchant3, _ = Merchant.objects.get_or_create(
                email='amit@studio.com',
                defaults={'name': 'Amit Patel'}
            )
            BankAccount.objects.get_or_create(
                merchant=merchant3,
                account_number='1122334455',
                defaults={
                    'ifsc_code': 'SBIN0011223',
                    'account_holder_name': 'Amit Patel',
                    'is_primary': True
                }
            )
            LedgerEntry.objects.get_or_create(
                merchant=merchant3,
                description='Payment from Client P',
                defaults={
                    'entry_type': LedgerEntry.CREDIT,
                    'amount_paise': 1000000  # 10000 INR
                }
            )

        self.stdout.write(self.style.SUCCESS('Database seeded successfully!'))
        self.stdout.write('Merchants created:')
        self.stdout.write(f'  1. {merchant1.name} - Balance: ₹{8000}')
        self.stdout.write(f'  2. {merchant2.name} - Balance: ₹{10000}')
        self.stdout.write(f'  3. {merchant3.name} - Balance: ₹{10000}')