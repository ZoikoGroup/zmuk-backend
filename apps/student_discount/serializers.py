from rest_framework import serializers
from .models import StudentDiscountApplication

class StudentDiscountSerializer(serializers.ModelSerializer):
    class Meta:
        model = StudentDiscountApplication
        fields = "__all__"
