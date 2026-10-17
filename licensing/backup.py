"""Consistent backups of every database (main + each hosted customer) and all uploaded photos.

SQLite files are copied with SQLite's own online-backup API, so a snapshot is valid even while the
site is serving requests (copying the raw file mid-write could produce a corrupt copy).

Archive layout (restore = extract into the app folder):
    data/<main>.sqlite3
    data/tenants/<slug>.sqlite3
    media/...
"""
import logging
import re
import shutil
import sqlite3
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path

from django.conf import settings

log = logging.getLogger("cofferant")

NAME_RE = re.compile(r"^cofferant-\d{8}-\d{6}\.tar\.gz$")


def backup_dir():
    path = Path(settings.BACKUP_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _snapshot(src, dst):
    """Copy one SQLite database safely and verify the copy."""
    src_conn = sqlite3.connect(str(src), timeout=30)
    dst_conn = sqlite3.connect(str(dst))
    try:
        src_conn.backup(dst_conn)
        result = dst_conn.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise RuntimeError(f"integrity check failed for {src}: {result}")
    finally:
        dst_conn.close()
        src_conn.close()


def list_backups():
    out = []
    for p in sorted(backup_dir().glob("cofferant-*.tar.gz"), reverse=True):
        if NAME_RE.match(p.name):
            st = p.stat()
            out.append({"name": p.name, "size": st.st_size, "mtime": datetime.fromtimestamp(st.st_mtime)})
    return out


def prune(keep=None):
    keep = int(keep or settings.BACKUP_KEEP)
    for old in list_backups()[keep:]:
        (backup_dir() / old["name"]).unlink(missing_ok=True)
        log.info("backup pruned: %s", old["name"])


def create_backup():
    """Write a new timestamped archive; returns (path, number_of_databases)."""
    target_dir = backup_dir()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    final = target_dir / f"cofferant-{stamp}.tar.gz"
    partial = target_dir / f".{final.name}.partial"
    main_db = Path(str(settings.DATABASES["default"]["NAME"]))

    with tempfile.TemporaryDirectory(prefix="stage-", dir=target_dir) as stage_name:
        stage = Path(stage_name)
        (stage / "data" / "tenants").mkdir(parents=True)
        count = 0
        if main_db.exists():
            _snapshot(main_db, stage / "data" / main_db.name)
            count += 1
        tenant_dir = Path(settings.TENANT_DB_DIR)
        if tenant_dir.exists():
            for db in sorted(tenant_dir.glob("*.sqlite3")):
                _snapshot(db, stage / "data" / "tenants" / db.name)
                count += 1
        try:
            with tarfile.open(partial, "w:gz") as tar:
                tar.add(stage / "data", arcname="data")
                media = Path(settings.MEDIA_ROOT)
                if media.exists():
                    tar.add(media, arcname="media")
            partial.replace(final)
        finally:
            partial.unlink(missing_ok=True)
    prune()
    log.info("backup written: %s (%s databases, %.1f MB)", final.name, count, final.stat().st_size / 1e6)
    return final, count


def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
