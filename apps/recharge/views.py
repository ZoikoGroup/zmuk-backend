import logging

from django.db.models import Sum
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework import status

from apps.sims.models import Sim

from .models import RechargeModule, RechargeOrder, RechargeProduct, TransatelLog
from .serializers import (
    RechargeModuleSerializer,
    RechargeOrderSerializer,
    RechargeProductSerializer,
    CreateRechargeSerializer,
    PhoneValidateSerializer,
    SimDetailSerializer,
    mask_identifier,
    phone_variants,
)
from . import services
from . import reactivation as reactivation_service

logger = logging.getLogger("apps.recharge")


# ── Phone Validation ─────────────────────────────────────────────────────

class ValidatePhoneView(APIView):
    """POST /api/recharge/validate-phone/

    Look up a phone number in the local SIM inventory. Returns masked SIM
    details if found, matching the WordPress recharge page behaviour.

    Request:  { "phone_number": "+447421118918" }
    Response: { "success": true, "message": "...", "sim": { ... } }
    """
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PhoneValidateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        phone = serializer.validated_data["phone_number"]

        # Search local SIM inventory by all MSISDN variants
        variants = phone_variants(phone, country_code="44")
        sim = Sim.objects.filter(msisdn__in=variants).first()

        if not sim:
            return Response(
                {"success": False, "message": "No SIM found for this phone number."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Determine if rechargeable (Suspended SIMs only, matching WordPress logic)
        sim_status = (sim.provisioning_status or "").strip()
        rechargeable = sim_status.lower() == "suspended"

        if rechargeable:
            message = "Phone number validated successfully!"
        else:
            message = (
                f"This SIM is {sim_status}; recharge is only available "
                f"for suspended SIMs."
            )

        sim_data = {
            "phone_number": sim.msisdn or phone,
            "sim_card_id_masked": mask_identifier(sim.serial_number or sim.iccid),
            "sim_iccid_masked": mask_identifier(sim.iccid) if sim.iccid else "",
            "sim_status": sim_status,
            "rechargeable": rechargeable,
        }

        # Log the validation
        TransatelLog.objects.create(
            action="validate_phone",
            msisdn_masked=mask_identifier(phone),
            sim_serial_masked=mask_identifier(sim.serial_number or sim.iccid),
            success=True,
            response_body={"status": sim_status, "rechargeable": rechargeable},
        )

        return Response({
            "success": True,
            "message": message,
            "sim": SimDetailSerializer(sim_data).data,
            # Frontend needs the raw serial to pass back when creating the order.
            # In production, use a signed token instead (see security note below).
            "sim_serial": sim.serial_number or sim.iccid,
            "sim_iccid": sim.iccid or "",
        })


# ── Recharge Products / Plans ────────────────────────────────────────────

class RechargeProductsView(APIView):
    """GET /api/recharge/products/?module=recharge

    Returns the active plans for a given module. This is what populates
    the "Select Recharge Plan" modal.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        module = request.query_params.get("module", "recharge")
        products = RechargeProduct.objects.filter(
            module=module, is_active=True
        )
        return Response({
            "success": True,
            "products": RechargeProductSerializer(products, many=True).data,
        })


# ── Modules ──────────────────────────────────────────────────────────────

class RechargeModulesView(APIView):
    """GET /api/recharge/modules/"""
    permission_classes = [AllowAny]

    def get(self, request):
        mods = RechargeModule.objects.all()
        return Response(RechargeModuleSerializer(mods, many=True).data)


# ── Stats ────────────────────────────────────────────────────────────────

class RechargeStatsView(APIView):
    """GET /api/recharge/stats/"""
    permission_classes = [AllowAny]

    def get(self, request):
        completed = RechargeOrder.objects.filter(status=RechargeOrder.STATUS_COMPLETED)
        today = timezone.now().date()
        today_qs = completed.filter(created_at__date=today)

        total_amount = completed.aggregate(s=Sum("amount_pence"))["s"] or 0
        today_amount = today_qs.aggregate(s=Sum("amount_pence"))["s"] or 0

        return Response({
            "total_recharges": completed.count(),
            "total_amount": f"£{total_amount / 100:.2f}",
            "today_recharges": today_qs.count(),
            "today_amount": f"£{today_amount / 100:.2f}",
        })


# ── Orders List ──────────────────────────────────────────────────────────

class RechargeOrdersView(APIView):
    """GET /api/recharge/orders/"""
    permission_classes = [AllowAny]

    def get(self, request):
        limit = int(request.query_params.get("limit", 20))
        orders = RechargeOrder.objects.all()[:limit]
        return Response(RechargeOrderSerializer(orders, many=True).data)


# ── Order Detail ─────────────────────────────────────────────────────────

class RechargeOrderDetailView(APIView):
    """GET /api/recharge/orders/<order_ref>/"""
    permission_classes = [AllowAny]

    def get(self, request, order_ref):
        order = RechargeOrder.objects.filter(order_ref=order_ref).first()
        if not order:
            return Response(
                {"success": False, "message": "Order not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        data = RechargeOrderSerializer(order).data

        # Include reactivation status
        attempt = order.reactivation_attempts.order_by("-updated_at").first()
        data["reactivation_status"] = attempt.status if attempt else None
        data["reactivation_transaction_id"] = attempt.provider_transaction_id if attempt else None

        return Response({"success": True, "order": data})


# ── Create Order ─────────────────────────────────────────────────────────

class CreateRechargeView(APIView):
    """POST /api/recharge/create/

    Creates order + Stripe Checkout Session. Returns {order_ref, checkout_url}.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = CreateRechargeSerializer(data=request.data, context={})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        amount_pence = data["_amount_pence"]
        product = data.get("_product")

        order = RechargeOrder.objects.create(
            module=data["module"],
            msisdn=data["msisdn"],
            sim_serial=data.get("sim_serial", "") or "",
            sim_iccid=data.get("sim_iccid", "") or "",
            customer_name=data.get("customer_name", "") or "",
            customer_email=data.get("customer_email", "") or "",
            product=product,
            amount_pence=amount_pence,
            currency="gbp",
            status=RechargeOrder.STATUS_PENDING,
        )

        try:
            session = services.create_checkout_session(
                order,
                success_url=data["success_url"],
                cancel_url=data["cancel_url"],
            )
        except services.StripeNotConfigured as exc:
            order.status = RechargeOrder.STATUS_FAILED
            order.save(update_fields=["status"])
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except Exception as exc:
            order.status = RechargeOrder.STATUS_FAILED
            order.save(update_fields=["status"])
            logger.exception("Stripe session creation failed for %s", order.order_ref)
            return Response(
                {"detail": f"Payment could not be started: {exc}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        order.stripe_session_id = session.get("id", "")
        order.save(update_fields=["stripe_session_id"])

        return Response(
            {"order_ref": order.order_ref, "checkout_url": session.get("url")},
            status=status.HTTP_201_CREATED,
        )


# ── Stripe Webhook ───────────────────────────────────────────────────────

@csrf_exempt
def stripe_webhook(request):
    """POST /api/recharge/webhook/

    Source of truth for 'paid'. After payment confirmation, triggers
    Transatel SIM reactivation.
    """
    if request.method != "POST":
        return HttpResponse(status=405)

    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")

    try:
        event = services.construct_webhook_event(payload, sig_header)
    except services.StripeNotConfigured as exc:
        return HttpResponse(str(exc), status=503)
    except ValueError:
        return HttpResponse("Invalid payload", status=400)
    except Exception:
        return HttpResponse("Invalid signature", status=400)

    etype = event["type"]
    logger.info("Stripe webhook received: %s", etype)

    if etype == "checkout.session.completed":
        session = event["data"]["object"]
        ref = (session.get("metadata") or {}).get("order_ref")
        order = RechargeOrder.objects.filter(order_ref=ref).first()

        if order and order.status == RechargeOrder.STATUS_PENDING:
            # Mark as processing (paid but reactivation pending)
            order.status = RechargeOrder.STATUS_PROCESSING
            order.stripe_payment_intent_id = session.get("payment_intent", "") or ""
            order.paid_at = timezone.now()
            order.save(update_fields=["status", "stripe_payment_intent_id", "paid_at", "updated_at"])

            logger.info("Payment confirmed for %s — triggering reactivation", order.order_ref)

            # ── TRIGGER TRANSATEL REACTIVATION ──
            if order.sim_serial:
                try:
                    attempt = reactivation_service.reactivate_for_order(order)
                    if attempt and attempt.status == "success":
                        logger.info("Reactivation succeeded for %s", order.order_ref)
                    else:
                        logger.warning(
                            "Reactivation not successful for %s (status=%s). Will retry.",
                            order.order_ref,
                            attempt.status if attempt else "no_attempt",
                        )
                except Exception:
                    logger.exception(
                        "Reactivation error for %s — queued for retry",
                        order.order_ref,
                    )
            else:
                logger.warning(
                    "Order %s has no sim_serial — skipping reactivation",
                    order.order_ref,
                )
                # Still mark completed for non-SIM recharges (e.g. top-ups)
                order.status = RechargeOrder.STATUS_COMPLETED
                order.completed_at = timezone.now()
                order.save(update_fields=["status", "completed_at", "updated_at"])

    elif etype in ("checkout.session.expired", "checkout.session.async_payment_failed"):
        session = event["data"]["object"]
        ref = (session.get("metadata") or {}).get("order_ref")
        order = RechargeOrder.objects.filter(order_ref=ref).first()
        if order and order.status == RechargeOrder.STATUS_PENDING:
            order.status = RechargeOrder.STATUS_FAILED
            order.save(update_fields=["status", "updated_at"])
            logger.info("Payment failed/expired for %s", order.order_ref)

    return JsonResponse({"received": True})


# ── Transatel Logs (admin endpoint) ──────────────────────────────────────

class TransatelLogsView(APIView):
    """GET /api/recharge/transatel-logs/  — recent Transatel API call logs."""
    permission_classes = [AllowAny]  # TODO: restrict to admin

    def get(self, request):
        limit = int(request.query_params.get("limit", 50))
        logs = TransatelLog.objects.all()[:limit]
        data = [
            {
                "id": log.id,
                "action": log.action,
                "sim_serial_masked": log.sim_serial_masked,
                "msisdn_masked": log.msisdn_masked,
                "request_method": log.request_method,
                "response_status": log.response_status,
                "success": log.success,
                "error_message": log.error_message,
                "duration_ms": log.duration_ms,
                "created_at": log.created_at.isoformat(),
                "order_ref": log.order.order_ref if log.order else None,
            }
            for log in logs
        ]
        return Response({"success": True, "logs": data})
