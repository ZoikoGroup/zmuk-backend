from django.db import models


class BqOrder(models.Model):
    raw_data = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Bq Order #{self.id}"
