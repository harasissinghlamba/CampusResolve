from django.core.management.base import BaseCommand
from django.utils.text import slugify

from apps.complaints.models import ComplaintCategory

CATEGORIES = [
    "Academic", "Examination", "Fees", "Infrastructure", "Hostel",
    "Library", "Transport", "Canteen", "Faculty/Staff",
    "Harassment/Safety", "IT/Portal", "Other",
]


class Command(BaseCommand):
    help = "Idempotently seed the default complaint categories."

    def handle(self, *args, **options):
        created_count = 0
        for name in CATEGORIES:
            _, created = ComplaintCategory.objects.get_or_create(
                name=name, defaults={"slug": slugify(name), "is_active": True}
            )
            created_count += int(created)
        self.stdout.write(self.style.SUCCESS(
            f"Seeded categories: {created_count} created, {len(CATEGORIES) - created_count} already existed."
        ))
