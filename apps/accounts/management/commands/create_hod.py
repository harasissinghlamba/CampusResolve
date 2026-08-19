from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError

from apps.accounts.models import Department, Role


class Command(BaseCommand):
    """
    Provision an HOD account administratively - same reasoning as
    create_director: HOD accounts must never be creatable through public
    registration.
    """

    help = "Create a Head of Department account (administrative provisioning only)."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)
        parser.add_argument("--full-name", required=True)
        parser.add_argument("--password", required=True)
        parser.add_argument(
            "--department", required=True, choices=[d.value for d in Department],
            help="One of: " + ", ".join(d.value for d in Department),
        )

    def handle(self, *args, **options):
        User = get_user_model()
        email = options["email"].strip().lower()
        if User.objects.filter(email=email).exists():
            raise CommandError(f"A user with email {email} already exists.")
        try:
            user = User.objects.create_user(
                username=email,
                email=email,
                full_name=options["full_name"],
                password=options["password"],
                role=Role.HOD,
                department=options["department"],
                is_staff=False,
            )
        except IntegrityError as exc:
            raise CommandError(str(exc))
        self.stdout.write(self.style.SUCCESS(
            f"HOD account created: {user.email} ({user.department})"
        ))
