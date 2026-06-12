from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .serializers import BqOrderSerializer
from .models import BqOrder
from collections import defaultdict


class BqOrderCreateAPIView(APIView):
    def post(self, request):
        serializer = BqOrderSerializer(
            data={"raw_data": request.data}
        )

        if serializer.is_valid():
            serializer.save()
            return Response(
                {"success": True, "message": "Order saved successfully"},
                status=status.HTTP_201_CREATED
            )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class BqUserGroupedOrdersAPIView(APIView):
    """
    POST BODY:
    {
        "logged_user": "user@example.com"
    }
    """

    def post(self, request):
        logged_user = request.data.get("logged_user")

        if not logged_user:
            return Response({
                "status": False,
                "message": "logged_user is required"
            }, status=status.HTTP_400_BAD_REQUEST)

        orders = BqOrder.objects.all().order_by("-id")

        grouped_data = defaultdict(lambda: defaultdict(list))

        for order in orders:
            data = order.raw_data  # already dict

            billing = data.get("billingAddress", {})
            order_email = billing.get("email", "")

            if order_email != logged_user:
                continue

            cart = data.get("cart", [])
            totals = data.get("totals", {})

            grouped_data[order_email][str(order.id)].append({
                "order_db_id": order.id,
                "bequick_order_id": data.get("bequick_order_id"),
                "subscriber_id": data.get("subscriber_id"),
                "total": totals.get("total"),
                "subtotal": totals.get("subtotal"),
                "shipping": totals.get("shipping"),
                "discount": totals.get("discount"),
                "payment_method": data.get("paymentMethod"),
                "cart": cart,
                "created_at": order.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            })

        return Response({
            "status": True,
            "logged_user": logged_user,
            "groups": grouped_data
        })
