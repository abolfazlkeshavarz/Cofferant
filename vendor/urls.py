from django.urls import path
from . import views

app_name = "vendor"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),

    # Items
    path("items/", views.ItemListView.as_view(), name="items"),
    path("items/add/", views.ItemCreateView.as_view(), name="item_add"),
    path("items/<int:pk>/edit/", views.ItemUpdateView.as_view(), name="item_edit"),

    # Tables
    path("tables/", views.TableListView.as_view(), name="tables"),
    path("tables/add/", views.TableCreateView.as_view(), name="table_add"),

    # Orders
    path("orders/", views.orders_list, name="orders"),
    path("orders/<int:pk>/", views.order_detail, name="order_detail"),
    path("orders/<int:pk>/complete/", views.complete_order, name="order_complete"),
]
