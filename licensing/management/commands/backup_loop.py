import logging
import signal
import time

from django.conf import settings
from django.core.management.base import BaseCommand

from licensing import backup

log = logging.getLogger("cofferant")


class Command(BaseCommand):
    help = "Run backups forever, every BACKUP_INTERVAL_HOURS (default 12). Used by the 'backup' container."

    def add_arguments(self, parser):
        parser.add_argument("--first-delay", type=int, default=90, help="seconds before the first backup when none is due yet")

    def handle(self, *args, **opts):
        interval = max(1, float(settings.BACKUP_INTERVAL_HOURS)) * 3600
        stop = {"now": False}
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, lambda *_: stop.update(now=True))

        existing = backup.list_backups()
        if existing:
            # a restart must not trigger an extra backup, nor delay a due one
            age = time.time() - (backup.backup_dir() / existing[0]["name"]).stat().st_mtime
            due = time.time() + max(0, interval - age)
        else:
            due = time.time() + opts["first_delay"]
        self.stdout.write(f"Backups every {interval / 3600:g}h into {settings.BACKUP_DIR}; next in {max(0, due - time.time()):.0f}s")

        while not stop["now"]:
            if time.time() >= due:
                try:
                    path, count = backup.create_backup()
                    self.stdout.write(f"backup ok: {path.name} ({count} databases)")
                except Exception:  # keep the loop alive; the next round retries
                    log.exception("backup failed")
                    self.stderr.write("backup FAILED (see log); retrying in 15 minutes")
                    due = time.time() + 900
                    continue
                due = time.time() + interval
            time.sleep(5)
        self.stdout.write("backup loop stopped")
