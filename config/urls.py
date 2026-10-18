from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.generic import RedirectView
from django.views.static import serve

from licensing import views as licensing_views

admin.site.site_header = "مدیریت کافیرانت"
admin.site.site_title = "کافیرانت"

urlpatterns = [
    path('favicon.ico', RedirectView.as_view(url='/static/images/fevicon.png', permanent=True)),
    path('healthz', licensing_views.healthz),
    path('api/license/verify/', licensing_views.verify_api),
    path('license/unavailable/', licensing_views.unavailable, name='license_unavailable'),
    path('license/recheck/', licensing_views.recheck, name='license_recheck'),
    path('developer/', include('licensing.urls')),
    path('admin/', admin.site.urls),
    path('', include('home.urls')),
    path("management/", include("management.urls")),
    path("vendor/", include(("vendor.urls", "vendor"), namespace="vendor")),
    path('users/', include('users.urls')),
    # Uploaded media (menu photos). For high traffic serve MEDIA_ROOT from nginx instead.
    re_path(r"^media/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT}),
]
