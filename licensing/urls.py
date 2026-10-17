from django.urls import path

from . import views

app_name = "developer"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("licenses/", views.license_list, name="list"),
    path("licenses/new/", views.license_create, name="create"),
    path("licenses/<int:pk>/", views.license_detail, name="detail"),
    path("licenses/<int:pk>/renew/", views.license_renew, name="renew"),
    path("licenses/<int:pk>/cancel/", views.license_cancel, name="cancel"),
    path("licenses/<int:pk>/reactivate/", views.license_reactivate, name="reactivate"),
    path("licenses/<int:pk>/password/", views.license_set_password, name="set_password"),
    path("licenses/<int:pk>/reset-owner/", views.license_set_password, name="reset_owner"),
    path("licenses/<int:pk>/domain/", views.license_set_domain, name="set_domain"),
    path("licenses/<int:pk>/trash/", views.license_trash, name="trash"),
    path("licenses/<int:pk>/restore/", views.license_restore, name="restore"),
    path("licenses/<int:pk>/purge/", views.license_purge, name="purge"),
    path("prices/", views.prices, name="prices"),
    path("backups/", views.backups, name="backups"),
    path("backups/run/", views.backup_now, name="backup_now"),
    path("backups/<str:name>/", views.backup_download, name="backup_download"),
]
