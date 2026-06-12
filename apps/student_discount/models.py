from django.db import models

class StudentDiscountApplication(models.Model):

    DOCUMENT_CHOICES = [
        ("Valid Student ID (Front & Back)", "Valid Student ID (Front & Back)"),
        ("Enrollment Verification Letter", "Enrollment Verification Letter"),
        ("Transcript", "Transcript"),
    ]

    full_name = models.CharField(max_length=255)
    dob = models.DateField()
    student_email = models.EmailField()
    document_type = models.CharField(max_length=255, choices=DOCUMENT_CHOICES)
    document_file = models.FileField(upload_to="student_documents/")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.full_name
