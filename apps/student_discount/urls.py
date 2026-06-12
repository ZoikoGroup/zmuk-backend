from django.urls import path
from .views import StudentDiscountCreateAPIView

urlpatterns = [
    path("student-discount-form", StudentDiscountCreateAPIView.as_view()),
]
