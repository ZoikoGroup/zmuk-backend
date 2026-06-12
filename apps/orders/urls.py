from django.urls import path
from .views import (
    BqOrderCreateAPIView,
    BqUserGroupedOrdersAPIView,
)

urlpatterns = [
    path("bqorders/", BqOrderCreateAPIView.as_view(), name="bqorders_create"),
    path("bqorders/by-user/", BqUserGroupedOrdersAPIView.as_view(), name="bqorders_by_user"),
]
