"""Recharge API.

Flow, with every guard the WordPress version had plus the ones it lacked:

  1. GET  /api/recharge/plans/          list plans from OUR database
  2. POST /api/recharge/sim-check/      ask Transatel for live SIM status
  3. POST /api/recharge/checkout/       charge, then activate
  4. POST /api/recharge/stripe-webhook/ authoritative payment confirmation

Two rules that must never be relaxed:

  * The amount comes from RechargePlan.price. There is no `amount` parameter
    on any endpoint and there must never be one.
  * Activation happens only after Stripe confirms the charge succeeded.
"""

import logging
import uuid

import stripe
from django.conf import settings
from django.db import transaction as db_transaction
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import RechargePlan, RechargeTransaction
from .serializers import RechargePlanSerializer, RechargeTransactionSerializer
from .transatel import TransatelClient, TransatelError, extract_status, valid_serial

logger = logging.getLogger(__name__)

stripe.api_key = getattr(settings, "STRIPE_SECRET_KEY", "")

# The WordPress module refused recharge unless status was 'Suspended'.
# Same rule, kept configurable.
RECHARGEABLE_STATUSES = {
    s.lower() for s in getattr(settings, "RECHARGE_ALLOWED_SIM_STATUSES", ["suspended"])
}


def new_reference():
    return f"rch-{uuid.uuid4().hex[:20]}"


# ─── 1. Plans ──────────────────────────────────────────────────────────────

class RechargePlanListAPI(generics.ListAPIView):
    serializer_class = RechargePlanSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        qs = RechargePlan.objects.filter(is_active=True)
        kind = self.request.query_params.get("kind")
        if kind:
            qs = qs.filter(kind=kind)
        return qs


# ─── 2. SIM check ──────────────────────────────────────────────────────────

class SimCheckAPI(APIView):
    """POST {"sim_serial": "8944..."} → live status from Transatel.

    Replaces the `wp_transatel_sim_details` table lookup. Reading status live
    means a SIM reactivated elsewhere is reflected immediately, instead of the
    stale local copy the WordPress version relied on.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        sim_serial = (request.data.get("sim_serial") or "").strip()

        if not valid_serial(sim_serial):
            return Response(
                {"detail": "SIM serial must be 13–20 digits."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            payload = TransatelClient().get_subscriber(sim_serial)
        except TransatelError as exc:
            # Transatel returns 400 for an unknown SIM, not 404. Surface its
            # own message rather than inventing one.
            return Response(
                {"detail": str(exc), "sim_serial": sim_serial},
                status=exc.status if 400 <= exc.status < 500 else 502,
            )

        sim_status = extract_status(payload)
        rechargeable = sim_status.lower() in RECHARGEABLE_STATUSES

        return Response({
            "sim_serial": sim_serial,
            "status": sim_status,
            "rechargeable": rechargeable,
            "message": (
                "Ready to recharge."
                if rechargeable
                else f"Recharge is only available for suspended SIMs. Current status: {sim_status}"
            ),
        })


# ─── 3. Checkout ───────────────────────────────────────────────────────────

class RechargeCheckoutAPI(APIView):
    """POST /api/recharge/checkout/

    Body:
        plan_id            int, required
        sim_serial         str, required
        payment_method_id  str, required (created by Stripe.js in the browser)

    No `amount`. Ever.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        plan_id = request.data.get("plan_id")
        sim_serial = (request.data.get("sim_serial") or "").strip()
        payment_method_id = (request.data.get("payment_method_id") or "").strip()

        if not plan_id or not sim_serial or not payment_method_id:
            return Response(
                {"detail": "plan_id, sim_serial and payment_method_id are all required."},
                status=400,
            )

        if not valid_serial(sim_serial):
            return Response({"detail": "SIM serial must be 13–20 digits."}, status=400)

        try:
            plan = RechargePlan.objects.get(pk=plan_id, is_active=True)
        except (RechargePlan.DoesNotExist, ValueError, TypeError):
            return Response({"detail": "Unknown or inactive plan."}, status=400)

        client = TransatelClient()

        # ── Guard: SIM must be suspended ──────────────────────────────────
        # Re-checked here rather than trusting the earlier sim-check call.
        # A client-side check is a convenience, never a control.
        try:
            subscriber = client.get_subscriber(sim_serial)
        except TransatelError as exc:
            return Response({"detail": str(exc)}, status=exc.status if 400 <= exc.status < 500 else 502)

        sim_status = extract_status(subscriber)
        if sim_status.lower() not in RECHARGEABLE_STATUSES:
            return Response(
                {"detail": f"Recharge is only available for suspended SIMs. Current status: {sim_status}"},
                status=409,
            )

        msisdn = ""
        if isinstance(subscriber, dict):
            msisdn = str(
                subscriber.get("msisdnVoice")
                or subscriber.get("msisdn")
                or ""
            )

        # ── Log BEFORE any external call ──────────────────────────────────
        txn = RechargeTransaction.objects.create(
            user=request.user,
            plan=plan,
            reference=new_reference(),
            sim_serial=sim_serial,
            msisdn=msisdn,
            sim_status_before=sim_status,
            amount=plan.price,             # from the DB, not the request
            currency=plan.currency,
            rate_plan=plan.transatel_rate_plan,
            status=RechargeTransaction.Status.SIM_CHECKED,
        )

        # ── Charge ────────────────────────────────────────────────────────
        try:
            intent = stripe.PaymentIntent.create(
                amount=plan.amount_minor,           # pence, from the DB
                currency=plan.currency.lower(),
                payment_method=payment_method_id,
                confirm=True,
                # Card-only, no redirect flows — this is a server-side confirm.
                automatic_payment_methods={"enabled": True, "allow_redirects": "never"},
                metadata={
                    "reference": txn.reference,
                    "user_id": str(request.user.pk),
                    "plan_id": str(plan.pk),
                    "sim_serial_last4": sim_serial[-4:],
                },
                # Stripe-side idempotency: a retry of this exact call returns
                # the original PaymentIntent instead of charging twice.
                idempotency_key=txn.reference,
            )
        except stripe.error.CardError as exc:
            txn.mark_failed(exc.user_message or "Card was declined.")
            return Response({"detail": exc.user_message or "Card was declined.",
                             "reference": txn.reference}, status=402)
        except stripe.error.StripeError as exc:
            txn.mark_failed(f"Stripe error: {exc}")
            logger.exception("Recharge %s: Stripe error", txn.reference)
            return Response({"detail": "Payment could not be processed.",
                             "reference": txn.reference}, status=502)

        txn.stripe_payment_intent_id = intent.id
        txn.stripe_response = {"id": intent.id, "status": intent.status}

        # ── 3DS / SCA ─────────────────────────────────────────────────────
        # The WordPress version called payment_complete() on any non-error,
        # which under UK/EU SCA marks orders paid that were never captured.
        # Report the real state and let the webhook confirm.
        if intent.status == "requires_action":
            txn.status = RechargeTransaction.Status.REQUIRES_ACTION
            txn.save()
            return Response({
                "reference": txn.reference,
                "status": txn.status,
                "requires_action": True,
                "client_secret": intent.client_secret,
            })

        if intent.status != "succeeded":
            txn.mark_failed(f"PaymentIntent ended in state '{intent.status}'.")
            return Response({"detail": "Payment was not completed.",
                             "reference": txn.reference}, status=402)

        txn.mark_paid(intent.id, {"id": intent.id, "status": intent.status})

        # ── Activate ──────────────────────────────────────────────────────
        activated = _activate(txn)

        return Response({
            "reference": txn.reference,
            "status": txn.status,
            "requires_action": False,
            "activated": activated,
            "amount": str(txn.amount),
            "currency": txn.currency,
            "message": (
                "Recharge complete. Your SIM has been reactivated."
                if activated
                else "Payment received. Activation is being completed — our team has been notified."
            ),
        })


def _activate(txn):
    """Call Transatel reactivate for a paid transaction. Idempotent.

    Returns True on success. On failure the transaction is left in
    ACTIVATION_FAILED — money taken, SIM not active. Those rows must be worked
    manually; they are filtered in the admin for exactly that reason.
    """
    if txn.status == RechargeTransaction.Status.ACTIVATED:
        return True
    if txn.status not in {RechargeTransaction.Status.PAID,
                          RechargeTransaction.Status.ACTIVATION_FAILED}:
        return False

    try:
        result = TransatelClient().reactivate(txn.sim_serial, txn.rate_plan)
    except TransatelError as exc:
        # A 504 means the call may actually have succeeded. Record it as
        # needing attention rather than retrying blindly and double-activating.
        txn.transatel_response = {"error": str(exc), "status": exc.status,
                                  "payload": exc.payload}
        txn.mark_failed(f"Activation failed: {exc}",
                        status=RechargeTransaction.Status.ACTIVATION_FAILED)
        logger.error("Recharge %s: activation failed: %s", txn.reference, exc)
        return False

    txn_id = ""
    if isinstance(result, dict):
        txn_id = str(result.get("transactionId") or result.get("transaction_id") or "")

    txn.mark_activated(txn_id, result if isinstance(result, dict) else {"raw": str(result)})
    logger.info("Recharge %s: SIM activated (transatel txn %s)", txn.reference, txn_id or "n/a")
    return True


# ─── 4. Stripe webhook ─────────────────────────────────────────────────────

@csrf_exempt
@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def stripe_webhook(request):
    """Authoritative payment confirmation.

    This is what makes 3DS/SCA safe. The browser saying "it worked" is not
    evidence; a signature-verified webhook is.
    """
    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")
    secret = getattr(settings, "STRIPE_WEBHOOK_SECRET", "")

    if not secret:
        logger.error("STRIPE_WEBHOOK_SECRET is not configured.")
        return Response(status=500)

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, secret)
    except ValueError:
        return Response({"detail": "Invalid payload."}, status=400)
    except stripe.error.SignatureVerificationError:
        # Never process an unverified webhook. Anyone can POST to this URL.
        logger.warning("Stripe webhook signature verification failed.")
        return Response({"detail": "Invalid signature."}, status=400)

    if event["type"] not in {"payment_intent.succeeded", "payment_intent.payment_failed"}:
        return Response(status=200)

    intent = event["data"]["object"]
    reference = (intent.get("metadata") or {}).get("reference")

    with db_transaction.atomic():
        txn = (
            RechargeTransaction.objects
            .select_for_update()
            .filter(reference=reference)
            .first()
        ) if reference else None

        if not txn:
            txn = (
                RechargeTransaction.objects
                .select_for_update()
                .filter(stripe_payment_intent_id=intent["id"])
                .first()
            )

        if not txn:
            # Not ours, or a test event. 200 so Stripe stops retrying.
            return Response(status=200)

        if event["type"] == "payment_intent.payment_failed":
            if txn.status not in {RechargeTransaction.Status.ACTIVATED,
                                  RechargeTransaction.Status.PAID}:
                txn.mark_failed("Stripe reported the payment failed.")
            return Response(status=200)

        # succeeded — idempotent: already activated means nothing to do.
        if txn.status == RechargeTransaction.Status.ACTIVATED:
            return Response(status=200)

        if txn.status != RechargeTransaction.Status.PAID:
            txn.mark_paid(intent["id"], {"id": intent["id"], "status": intent["status"]})

    # Activate outside the row lock so a slow Transatel call does not hold it.
    _activate(txn)
    return Response(status=200)


# ─── 5. History ────────────────────────────────────────────────────────────

class MyRechargeTransactionsAPI(generics.ListAPIView):
    """The signed-in user's own history, for their profile page."""

    serializer_class = RechargeTransactionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        # Ownership filter lives in the queryset, so a guessed reference
        # belonging to another customer returns 404, not their data.
        return RechargeTransaction.objects.filter(
            user=self.request.user
        ).select_related("plan")


class RechargeTransactionDetailAPI(generics.RetrieveAPIView):
    serializer_class = RechargeTransactionSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = "reference"

    def get_queryset(self):
        return RechargeTransaction.objects.filter(
            user=self.request.user
        ).select_related("plan")
