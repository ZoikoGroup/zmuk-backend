from django.urls import path

from .views import (
    ValidatePhoneView,
    RechargeProductsView,
    RechargeModulesView,
    RechargeStatsView,
    RechargeOrdersView,
    RechargeOrderDetailView,
    CreateRechargeView,
    TransatelLogsView,
    stripe_webhook,
)
app_name = "recharge"
urlpatterns = [
    # Phone validation (Step 1)
    path("validate-phone/", ValidatePhoneView.as_view(), name="recharge_validate_phone"),

    # Product catalog (Step 2)
    path("products/", RechargeProductsView.as_view(), name="recharge_products"),

    # Order creation + payment (Steps 3-4)
    path("create/", CreateRechargeView.as_view(), name="recharge_create"),

    # Order lookup
    path("orders/", RechargeOrdersView.as_view(), name="recharge_orders"),
    path("orders/<str:order_ref>/", RechargeOrderDetailView.as_view(), name="recharge_order_detail"),

    # Stripe webhook (payment confirmation → reactivation)
    path("webhook/", stripe_webhook, name="recharge_webhook"),

    # Admin / dashboard
    path("modules/", RechargeModulesView.as_view(), name="recharge_modules"),
    path("stats/", RechargeStatsView.as_view(), name="recharge_stats"),
    path("transatel-logs/", TransatelLogsView.as_view(), name="recharge_transatel_logs"),
]
