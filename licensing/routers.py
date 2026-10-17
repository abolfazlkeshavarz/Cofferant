from .tenancy import current_alias


class TenantRouter:
    """licensing.* always lives in the main database; everything else follows the tenant."""

    def _db(self, model):
        return "default" if model._meta.app_label == "licensing" else current_alias()

    def db_for_read(self, model, **hints):
        return self._db(model)

    def db_for_write(self, model, **hints):
        return self._db(model)

    def allow_relation(self, obj1, obj2, **hints):
        return True

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if app_label == "licensing":
            return db == "default"
        return True
