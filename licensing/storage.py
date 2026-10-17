from django.core.files.storage import FileSystemStorage

from .tenancy import current_tenant


class TenantMediaStorage(FileSystemStorage):
    """Uploads of hosted customers live in MEDIA_ROOT/<slug>/… so customers stay separated."""

    @staticmethod
    def _prefix():
        slug = current_tenant.get()
        return f"{slug}/" if slug else ""

    def path(self, name):
        return super().path(self._prefix() + name)

    def url(self, name):
        return super().url(self._prefix() + name)
