from django.core.management.base import BaseCommand

from licensing import backup


class Command(BaseCommand):
    help = "Create one backup archive now (all databases, every hosted customer and uploaded photos)."

    def handle(self, *args, **opts):
        path, count = backup.create_backup()
        self.stdout.write(self.style.SUCCESS(f"{path}  ({count} databases, {backup.human_size(path.stat().st_size)})"))
