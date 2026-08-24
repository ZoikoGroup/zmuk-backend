from rest_framework import serializers

from .models import RechargePlan, RechargeTransaction


class RechargePlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = RechargePlan
        fields = [
            "id", "name", "slug", "kind", "description",
            "price", "currency", "data_allowance", "validity_days",
        ]
        read_only_fields = fields
        # NOTE: transatel_rate_plan is deliberately NOT exposed. It is an
        # internal provisioning value; the browser has no reason to see it and
        # no reason to be able to influence it.


class RechargeTransactionSerializer(serializers.ModelSerializer):
    plan_name = serializers.CharField(source="plan.name", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    sim_serial = serializers.CharField(source="masked_serial", read_only=True)

    class Meta:
        model = RechargeTransaction
        fields = [
            "reference", "plan_name", "sim_serial", "msisdn",
            "amount", "currency",
            "status", "status_display", "failure_reason",
            "created_at", "paid_at", "activated_at",
        ]
        read_only_fields = fields
        # stripe_response / transatel_response / rate_plan omitted — provider
        # internals, not for customer display.
