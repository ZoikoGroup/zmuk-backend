from django.urls import path

from . import views

app_name = "recharge"

urlpatterns = [
    path("plans/", views.RechargePlanListAPI.as_view(), name="plans"),
    path("sim-check/", views.SimCheckAPI.as_view(), name="sim-check"),
    path("checkout/", views.RechargeCheckoutAPI.as_view(), name="checkout"),
    path("stripe-webhook/", views.stripe_webhook, name="stripe-webhook"),
    path("transactions/", views.MyRechargeTransactionsAPI.as_view(), name="transactions"),
    path("transactions/<str:reference>/", views.RechargeTransactionDetailAPI.as_view(), name="transaction-detail"),
]
