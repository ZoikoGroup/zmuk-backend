from django.db import models


class SimActivation(models.Model):
    username = models.CharField(max_length=100)
    email = models.EmailField()

    otp = models.CharField(max_length=8)
    sim_serial = models.CharField(max_length=25)

    title = models.CharField(max_length=20)

    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)

    dob = models.DateField()

    zoiko_package = models.CharField(max_length=100)

    country = models.CharField(max_length=100)
    postcode = models.CharField(max_length=30)
    city = models.CharField(max_length=100)

    address = models.TextField()

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.first_name} {self.last_name}"