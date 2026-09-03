"""Seed the RechargeProduct table with plans matching the WordPress site.

Run once after migration:
    python manage.py seed_recharge_products
"""

from django.core.management.base import BaseCommand
from apps.recharge.models import RechargeProduct


PRODUCTS = [
    {
        "name": "Zoiko Starter 5GB",
        "slug": "zoiko-starter-5gb",
        "module": "recharge",
        "price_pence": 999,
        "short_description": "5GB data, unlimited calls & texts",
        "rate_plan": "",  # uses default from TRANSATEL settings
        "attributes": {"data_gb": 5, "validity_days": 30},
        "sort_order": 1,
    },
    {
        "name": "Zoiko Essential 15GB",
        "slug": "zoiko-essential-15gb",
        "module": "recharge",
        "price_pence": 1499,
        "short_description": "15GB data, unlimited calls & texts",
        "rate_plan": "",
        "attributes": {"data_gb": 15, "validity_days": 30},
        "sort_order": 2,
    },
    {
        "name": "Zoiko Plus 30GB",
        "slug": "zoiko-plus-30gb",
        "module": "recharge",
        "price_pence": 1834,
        "short_description": "30GB data, unlimited calls & texts",
        "rate_plan": "",
        "attributes": {"data_gb": 30, "validity_days": 30},
        "sort_order": 3,
    },
    {
        "name": "Zoiko Premium 50GB",
        "slug": "zoiko-premium-50gb",
        "module": "recharge",
        "price_pence": 2134,
        "short_description": "50GB data, unlimited calls & texts",
        "rate_plan": "",
        "attributes": {"data_gb": 50, "validity_days": 30},
        "sort_order": 4,
    },
    {
        "name": "Zoiko Elite 100GB",
        "slug": "zoiko-elite-100gb",
        "module": "recharge",
        "price_pence": 2834,
        "short_description": "100GB data, unlimited calls & texts",
        "rate_plan": "",
        "attributes": {"data_gb": 100, "validity_days": 30},
        "sort_order": 5,
    },
]


class Command(BaseCommand):
    help = "Seed RechargeProduct table with default plans"

    def handle(self, *args, **options):
        created = 0
        updated = 0

        for p in PRODUCTS:
            obj, was_created = RechargeProduct.objects.update_or_create(
                slug=p["slug"],
                defaults=p,
            )
            if was_created:
                created += 1
            else:
                updated += 1

        self.stdout.write(self.style.SUCCESS(
            f"Done: {created} created, {updated} updated."
        ))
