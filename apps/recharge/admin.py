from django.contrib import admin, messages
from django.utils.html import format_html

from .models import RechargePlan, RechargeTransaction


@admin.register(RechargePlan)
class RechargePlanAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "price_display", "transatel_rate_plan",
                    "data_allowance", "is_active", "sort_order")
    list_editable = ("is_active", "sort_order")
    list_filter = ("kind", "is_active", "currency")
    search_fields = ("name", "slug", "transatel_rate_plan")
    prepopulated_fields = {"slug": ("name",)}
    ordering = ("sort_order", "price")

    fieldsets = (
        ("Plan", {"fields": ("name", "slug", "kind", "description", "is_active", "sort_order")}),
        ("Price", {
            "description": "This is the amount the customer is charged. It is "
                           "never taken from the browser.",
            "fields": ("price", "currency"),
        }),
        ("Transatel", {
            "description": "ratePlan sent to the reactivate endpoint. Must match "
                           "a rate plan that exists in Transatel exactly, or "
                           "activation fails after the customer has paid.",
            "fields": ("transatel_rate_plan",),
        }),
        ("Display", {"fields": ("data_allowance", "validity_days")}),
    )

    @admin.display(description="Price", ordering="price")
    def price_display(self, obj):
        return f"{obj.currency} {obj.price}"


class NeedsAttentionFilter(admin.SimpleListFilter):
    """Money taken but SIM not activated. Work these first."""

    title = "needs attention"
    parameter_name = "attention"

    def lookups(self, request, model_admin):
        return (("yes", "Paid but not activated"),)

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.filter(
                status__in=[
                    RechargeTransaction.Status.ACTIVATION_FAILED,
                    RechargeTransaction.Status.PAID,
                ]
            )
        return queryset


@admin.register(RechargeTransaction)
class RechargeTransactionAdmin(admin.ModelAdmin):
    """Read-only. An audit log staff can edit is not an audit log."""

    list_display = ("reference", "user", "state_badge", "plan",
                    "amount_display", "masked", "created_at")
    list_filter = (NeedsAttentionFilter, "status", "currency", "created_at", "plan")
    search_fields = ("reference", "sim_serial", "msisdn",
                     "user__email", "user__username",
                     "stripe_payment_intent_id", "transatel_transaction_id")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    list_select_related = ("user", "plan")
    actions = ("retry_activation",)

    readonly_fields = (
        "reference", "user", "plan", "sim_serial", "msisdn", "sim_status_before",
        "amount", "currency", "rate_plan",
        "stripe_payment_intent_id", "transatel_transaction_id",
        "status", "failure_reason", "stripe_response", "transatel_response",
        "created_at", "updated_at", "paid_at", "activated_at",
    )

    fieldsets = (
        ("Transaction", {"fields": ("reference", "user", "plan", "status", "failure_reason")}),
        ("SIM", {"fields": ("sim_serial", "msisdn", "sim_status_before", "rate_plan")}),
        ("Amount", {"fields": ("amount", "currency")}),
        ("Provider references", {"fields": ("stripe_payment_intent_id", "transatel_transaction_id")}),
        ("Raw responses", {
            "classes": ("collapse",),
            "description": "Reconciliation only. Do not surface to customers.",
            "fields": ("stripe_response", "transatel_response"),
        }),
        ("Timestamps", {"fields": ("created_at", "updated_at", "paid_at", "activated_at")}),
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        # Deleting a payment record destroys the audit trail.
        return False

    @admin.display(description="Status", ordering="status")
    def state_badge(self, obj):
        colours = {
            "activated": "#059669",
            "paid": "#d97706",
            "activation_failed": "#dc2626",
            "requires_action": "#d97706",
            "payment_pending": "#2563eb",
            "sim_checked": "#6b7280",
            "initiated": "#6b7280",
            "failed": "#dc2626",
            "refunded": "#6b7280",
        }
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;'
            'border-radius:10px;font-size:11px;white-space:nowrap;">{}</span>',
            colours.get(obj.status, "#6b7280"), obj.get_status_display(),
        )

    @admin.display(description="Amount", ordering="amount")
    def amount_display(self, obj):
        return f"{obj.currency} {obj.amount}"

    @admin.display(description="SIM")
    def masked(self, obj):
        return obj.masked_serial or "—"

    @admin.action(description="Retry Transatel activation (paid transactions only)")
    def retry_activation(self, request, queryset):
        from .views import _activate

        done = failed = skipped = 0
        for txn in queryset:
            if txn.status not in {RechargeTransaction.Status.PAID,
                                  RechargeTransaction.Status.ACTIVATION_FAILED}:
                skipped += 1
                continue
            if _activate(txn):
                done += 1
            else:
                failed += 1

        if done:
            self.message_user(request, f"{done} activated.", messages.SUCCESS)
        if failed:
            self.message_user(request, f"{failed} still failing — check the reason field.", messages.ERROR)
        if skipped:
            self.message_user(request, f"{skipped} skipped (not in a paid state).", messages.WARNING)
