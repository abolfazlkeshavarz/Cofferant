from django.core.management.base import BaseCommand

from licensing import tenancy
from licensing.models import License


class Command(BaseCommand):
    help = "Apply pending migrations to every hosted customer's database (run after each deploy)."

    def handle(self, *args, **opts):
        slugs = [s for s in License.objects.filter(mode=License.HOSTED).values_list("slug", flat=True) if s]
        for slug in slugs:
            if not tenancy.tenant_db_exists(slug):
                self.stdout.write(self.style.WARNING(f"skip {slug}: database file missing"))
                continue
            tenancy.migrate_tenant(slug)
            self.stdout.write(f"migrated {slug}")
        self.stdout.write(self.style.SUCCESS(f"{len(slugs)} tenant(s) checked."))
