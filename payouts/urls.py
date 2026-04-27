from django.urls import path
from . import views

urlpatterns = [
    path('merchants/', views.merchant_list, name='merchant-list'),
    path('merchants/<uuid:merchant_id>/', views.merchant_dashboard, name='merchant-dashboard'),
    path('merchants/<uuid:merchant_id>/payouts/', views.create_payout, name='create-payout'),
    path('merchants/<uuid:merchant_id>/payouts/<uuid:payout_id>/', views.payout_status, name='payout-status'),
]