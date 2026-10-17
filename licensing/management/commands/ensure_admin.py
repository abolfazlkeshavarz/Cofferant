import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create/update the owner superuser from ADMIN_USERNAME / ADMIN_PASSWORD (idempotent; used by Docker)."

    def handle(self, *args, **opts):
        username = os.environ.get("ADMIN_USERNAME", "admin")
        password = os.environ.get("ADMIN_PASSWORD", "")
        if not password:
            self.stdout.write("ADMIN_PASSWORD not set; skipping.")
            return
        User = get_user_model()
        user, created = User.objects.get_or_create(username=username)
        user.is_staff = user.is_superuser = True
        user.set_password(password)
        user.save()
        self.stdout.write(self.style.SUCCESS(f"{'Created' if created else 'Updated'} admin '{username}'."))
