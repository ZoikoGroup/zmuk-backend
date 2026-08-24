"""Recharge models.

RechargePlan replaces the WooCommerce products. RechargeTransaction replaces
the WooCommerce order plus adds the audit log the old system never had.

Once these exist, WordPress is no longer in the path at all.
"""

from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


class RechargePlan(models.Model):
    """A recharge product. Replaces the WooCommerce product.

    IMPORTANT: `price` here is the single source of truth for what a customer
    is charged. It is never taken from the browser. This is the property the
    old WooCommerce flow got right and it must be preserved.
    """

    class Kind(models.TextChoices):
        RECHARGE = "recharge", "Recharge"
        TOPUP = "topup", "Top up"
        PENDING_BILL = "pending_bill", "Pending bill"

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True)
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.RECHARGE)
    description = models.TextField(blank=True)

    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
        help_text="Charged amount. Never accepted from the client.",
    )
    currency = models.CharField(max_length=3, default="GBP")

    # The value sent to Transatel's reactivate endpoint. The WordPress module
    # hardcoded 'MVNA Wholesale PAYM 7'; making it per-plan removes that.
    transatel_rate_plan = models.CharField(
        max_length=120,
        help_text='e.g. "MVNA Wholesale PAYM 7". Sent as ratePlan on reactivate.',
    )

    data_allowance = models.CharField(max_length=60, blank=True)
    validity_days = models.PositiveIntegerField(null=True, blank=True)

    is_active = models.BooleanField(default=True, db_index=True)
    sort_order = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "price"]
        verbose_name = "Recharge plan"

    def __str__(self):
        return f"{self.name} — {self.currency} {self.price}"

    @property
    def amount_minor(self):
        """Stripe wants the smallest currency unit (pence)."""
        return int((self.price * 100).to_integral_value())


class RechargeTransaction(models.Model):
    """Log of every recharge attempt, successful or not.

    Two fields carry the integrity guarantees:

      * `reference` — generated before any external call, so a crash mid-flight
        still leaves an audit record.
      * `stripe_payment_intent_id` — unique. Stripe retries webhooks on any
        non-2xx response; without this a retry would double-process.
    """

    class Status(models.TextChoices):
        INITIATED = "initiated", "Initiated"
        SIM_CHECKED = "sim_checked", "SIM checked"
        PAYMENT_PENDING = "payment_pending", "Payment pending"
        REQUIRES_ACTION = "requires_action", "Requires action (3DS)"
        PAID = "paid", "Paid — awaiting activation"
        ACTIVATED = "activated", "Activated"
        ACTIVATION_FAILED = "activation_failed", "Paid but activation failed"
        FAILED = "failed", "Failed"
        REFUNDED = "refunded", "Refunded"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,      # never orphan a financial record
        related_name="recharge_transactions",
    )
    plan = models.ForeignKey(
        RechargePlan,
        on_delete=models.PROTECT,      # keep history readable after a plan retires
        related_name="transactions",
    )

    reference = models.CharField(max_length=64, unique=True, db_index=True)

    sim_serial = models.CharField(max_length=32, db_index=True)
    msisdn = models.CharField(max_length=32, blank=True)
    sim_status_before = models.CharField(max_length=40, blank=True)

    # Snapshot at time of sale. If the plan price changes later, history stays
    # accurate about what was actually charged.
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default="GBP")
    rate_plan = models.CharField(max_length=120, blank=True)

    stripe_payment_intent_id = models.CharField(
        max_length=255, blank=True, null=True, unique=True, db_index=True
    )
    transatel_transaction_id = models.CharField(max_length=120, blank=True)

    status = models.CharField(
        max_length=24, choices=Status.choices,
        default=Status.INITIATED, db_index=True,
    )
    failure_reason = models.TextField(blank=True)

    # Raw provider responses, for reconciliation. Never shown to customers.
    stripe_response = models.JSONField(default=dict, blank=True)
    transatel_response = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    activated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Recharge transaction"
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["sim_serial", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.reference} · {self.get_status_display()}"

    # ── helpers ────────────────────────────────────────────────────────────

    @property
    def masked_serial(self):
        if not self.sim_serial or len(self.sim_serial) < 4:
            return ""
        return f"{'*' * (len(self.sim_serial) - 4)}{self.sim_serial[-4:]}"

    @property
    def needs_attention(self):
        """Money taken but the SIM was not activated. These must be worked
        manually — either retry activation or refund."""
        return self.status == self.Status.ACTIVATION_FAILED

    def mark_paid(self, payment_intent_id=None, raw=None):
        self.status = self.Status.PAID
        self.paid_at = timezone.now()
        if payment_intent_id:
            self.stripe_payment_intent_id = payment_intent_id
        if raw is not None:
            self.stripe_response = raw
        self.save()

    def mark_activated(self, transatel_txn_id="", raw=None):
        self.status = self.Status.ACTIVATED
        self.activated_at = timezone.now()
        if transatel_txn_id:
            self.transatel_transaction_id = transatel_txn_id
        if raw is not None:
            self.transatel_response = raw
        self.save()

    def mark_failed(self, reason="", status=None):
        self.status = status or self.Status.FAILED
        self.failure_reason = str(reason)[:2000]
        self.save()
