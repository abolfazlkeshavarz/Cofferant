# management/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path("t/<str:qr_slug>/", views.public_menu, name="public_menu"),
    path("api/orders/create/", views.create_order, name="create_order"),
    path("api/requests/create/", views.create_request, name="create_request"),
    path("api/quote/", views.quote, name="quote"),
    path("o/<str:token>/", views.order_track, name="order_track"),
    path("pay/<str:token>/", views.pay_start, name="pay_start"),
    path("pay/<str:token>/callback/", views.pay_callback, name="pay_callback"),
    path("api/o/<str:token>/", views.order_status, name="order_status"),
    path("api/o/<str:token>/rate/", views.order_rate, name="order_rate"),
]
