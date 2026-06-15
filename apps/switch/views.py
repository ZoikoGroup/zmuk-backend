from rest_framework import generics, permissions, status
from rest_framework.response import Response

from .models import SwitchRequest
from .serializers import SwitchRequestSerializer


class SwitchRequestCreateView(generics.CreateAPIView):
    """Public endpoint that the 'Switch to Zoiko Mobile' form POSTs to."""

    queryset = SwitchRequest.objects.all()
    serializer_class = SwitchRequestSerializer
    permission_classes = [permissions.AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        # Hook for later: trigger a confirmation email / notify ops here.
        return Response(
            {
                "success": True,
                "message": "Your switch request has been received. "
                "We'll be in touch within 1 working day.",
                "data": serializer.data,
            },
            status=status.HTTP_201_CREATED,
        )


class SwitchRequestListView(generics.ListAPIView):
    """Staff-only list of submitted switch requests (e.g. for an ops dashboard)."""

    queryset = SwitchRequest.objects.all()
    serializer_class = SwitchRequestSerializer
    permission_classes = [permissions.IsAdminUser]


class SwitchRequestDetailView(generics.RetrieveAPIView):
    """Staff-only detail view of a single switch request."""

    queryset = SwitchRequest.objects.all()
    serializer_class = SwitchRequestSerializer
    permission_classes = [permissions.IsAdminUser]
