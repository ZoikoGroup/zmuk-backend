from django.urls import path

from .views import SimActivationView


urlpatterns = [
    path(
        "activate/",
        SimActivationView.as_view(),
        name="activate-sim"
    ),
]