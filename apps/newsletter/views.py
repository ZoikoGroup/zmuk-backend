from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.core.mail import send_mail
from django.conf import settings
from django.db import IntegrityError
from .models import Subscriber
from .serializers import SubscriberSerializer


class SubscribeView(APIView):

    def post(self, request):
        email = request.data.get("email")

        if not email:
            return Response({
                "status": False,
                "message": "Email is required."
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            subscriber, created = Subscriber.objects.get_or_create(
                email=email
            )

            # If subscriber exists but inactive → reactivate
            if not created and not subscriber.is_active:
                subscriber.is_active = True
                subscriber.save()
                message = "Subscription reactivated successfully."
            elif not created:
                return Response({
                    "status": False,
                    "message": "This email is already subscribed."
                }, status=status.HTTP_400_BAD_REQUEST)
            else:
                message = "Successfully subscribed!"

            # Send confirmation email
            try:
                send_mail(
                    subject="Subscription Confirmation",
                    message="Thank you for subscribing to GoLite!",
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[subscriber.email],
                    fail_silently=True,
                )
            except Exception:
                pass

            return Response({
                "status": True,
                "message": message,
                "data": {
                    "email": subscriber.email,
                    "subscribed_at": subscriber.subscribed_at
                }
            }, status=status.HTTP_201_CREATED)

        except IntegrityError:
            return Response({
                "status": False,
                "message": "Subscription failed due to duplicate email."
            }, status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            return Response({
                "status": False,
                "message": "Something went wrong.",
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
