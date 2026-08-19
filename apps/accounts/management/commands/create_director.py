from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError

from apps.accounts.models import Role


class Command(BaseCommand):
    """
    Provision a Director account administratively.

    Director accounts must never be creatable through public registration
    (see CLAUDE.md: "Director accounts are provisioned administratively").
    This command is the sanctioned way to create one.
    """

    help = "Create a Director account (administrative provisioning only)."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)
        parser.add_argument("--full-name", required=True)
        parser.add_argument("--password", required=True)

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
                role=Role.DIRECTOR,
                is_staff=False,
            )
        except IntegrityError as exc:
            raise CommandError(str(exc))
        self.stdout.write(self.style.SUCCESS(f"Director account created: {user.email}"))
