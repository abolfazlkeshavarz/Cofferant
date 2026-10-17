"""Database-per-tenant plumbing for the hosted (platform) deployment mode.

Every hosted customer owns a SQLite file under TENANT_DB_DIR. A request is bound to
a tenant by TenantMiddleware (via the sub-domain); the router then sends all
non-licensing models to that tenant's database, so data can never leak across customers.
"""
import contextlib
import contextvars
import re
import threading

from django.conf import settings
from django.core.management import call_command
from django.db import connections

SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,28}[a-z0-9])$")
RESERVED = {"www", "admin", "api", "app", "mail", "static", "media", "developer", "dev", "panel", "root", "cdn"}

current_tenant = contextvars.ContextVar("current_tenant", default=None)
_lock = threading.Lock()


def alias_for(slug):
    return f"t_{slug}" if slug else "default"


def current_alias():
    return alias_for(current_tenant.get())


def valid_slug(slug):
    return bool(slug) and bool(SLUG_RE.match(slug)) and slug not in RESERVED


def db_path(slug):
    return settings.TENANT_DB_DIR / f"{slug}.sqlite3"


def tenant_db_exists(slug):
    return valid_slug(slug) and db_path(slug).exists()


def register_tenant_db(slug):
    """Make Django aware of the tenant's database (idempotent, thread-safe)."""
    if not valid_slug(slug):
        raise ValueError(f"invalid tenant slug: {slug!r}")
    alias = alias_for(slug)
    if alias in connections.settings:
        return alias
    with _lock:
        if alias not in connections.settings:
            settings.TENANT_DB_DIR.mkdir(parents=True, exist_ok=True)
            cfg = dict(connections.settings["default"])
            cfg["NAME"] = str(db_path(slug))
            cfg["OPTIONS"] = dict(cfg.get("OPTIONS", {}))
            connections.settings[alias] = cfg
    return alias


@contextlib.contextmanager
def use_tenant(slug):
    """Run a block against a tenant's database (slug=None -> the main database)."""
    if slug:
        register_tenant_db(slug)
    token = current_tenant.set(slug)
    try:
        yield
    finally:
        current_tenant.reset(token)


def migrate_tenant(slug):
    alias = register_tenant_db(slug)
    call_command("migrate", database=alias, interactive=False, verbosity=0)
    return alias


def provision_tenant(slug, business_name, owner_username, owner_password, owner_email=""):
    """Create + migrate a tenant database and its first (owner) account."""
    migrate_tenant(slug)
    with use_tenant(slug):
        from django.contrib.auth import get_user_model
        from management.models import Venue

        User = get_user_model()
        user, created = User.objects.get_or_create(
            username=owner_username,
            defaults={"is_staff": True, "is_superuser": False, "email": owner_email},
        )
        user.is_staff = True
        user.set_password(owner_password)
        user.save()
        venue = Venue.load()
        venue.name = business_name
        venue.save()
    return created


def close_tenant_connection(slug):
    alias = alias_for(slug)
    if alias in connections.settings:
        try:
            connections[alias].close()
        except Exception:  # pragma: no cover
            pass


def drop_tenant(slug):
    """Permanently remove a hosted customer's database file and uploaded photos."""
    import shutil
    from pathlib import Path

    if not valid_slug(slug):
        raise ValueError(f"invalid tenant slug: {slug!r}")
    alias = alias_for(slug)
    if alias in connections.settings:
        try:
            connections[alias].close()
        except Exception:  # pragma: no cover
            pass
        try:
            del connections[alias]
        except Exception:  # pragma: no cover
            pass
        connections.settings.pop(alias, None)
    base = db_path(slug)
    for suffix in ("", "-wal", "-shm", "-journal"):
        Path(str(base) + suffix).unlink(missing_ok=True)
    shutil.rmtree(Path(settings.MEDIA_ROOT) / slug, ignore_errors=True)
