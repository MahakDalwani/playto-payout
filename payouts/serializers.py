from rest_framework import serializers
from .models import Merchant, BankAccount, LedgerEntry, PayoutRequest


class BankAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = BankAccount
        fields = ['id', 'account_number', 'ifsc_code', 'account_holder_name', 'is_primary']


class LedgerEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = LedgerEntry
        fields = ['id', 'entry_type', 'amount_paise', 'description', 'created_at']


class PayoutRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = PayoutRequest
        fields = ['id', 'amount_paise', 'status', 'attempts', 'created_at', 'updated_at', 'bank_account']


class MerchantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Merchant
        fields = ['id', 'name', 'email', 'created_at']