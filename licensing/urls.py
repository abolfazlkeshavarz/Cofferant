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
    path("licenses/<int:pk>/reset-owner/", views.license_reset_owner, name="reset_owner"),
]
