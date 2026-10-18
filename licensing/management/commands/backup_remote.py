from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from licensing import backup


class Command(BaseCommand):
    help = "Test the off-server backup connection (--test) or send the newest local backup there (--push)."

    def add_arguments(self, parser):
        parser.add_argument("--test", action="store_true")
        parser.add_argument("--push", action="store_true")

    def handle(self, *args, **opts):
        if not settings.BACKUP_REMOTE:
            raise CommandError("BACKUP_REMOTE is not set (user@host:/absolute/path)")
        status = backup.push_remote(test=opts["test"] or not opts["push"])
        if not status["ok"]:
            raise CommandError(f"Off-server backup failed: {status['detail']}")
        self.stdout.write(self.style.SUCCESS(f"OK: {status['detail']} -> {status['target']}"))
