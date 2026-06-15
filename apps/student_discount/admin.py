from django.contrib import admin
from .models import StudentDiscountApplication

@admin.register(StudentDiscountApplication)
class StudentDiscountAdmin(admin.ModelAdmin):
    list_display = ("full_name", "student_email", "document_type", "created_at")
    search_fields = ("full_name", "student_email")
    list_filter = ("document_type",)
