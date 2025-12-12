# management/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path("t/<str:qr_slug>/", views.public_menu, name="public_menu"),
    path("api/orders/create/", views.create_order, name="create_order"),
]
