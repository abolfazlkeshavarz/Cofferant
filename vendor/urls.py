from django.urls import path
from . import views

app_name = "vendor"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),

    # Live board
    path("board/", views.board, name="board"),
    path("api/board/", views.board_feed, name="board_feed"),
    path("requests/<int:pk>/resolve/", views.resolve_request, name="request_resolve"),

    # Items
    path("items/", views.ItemListView.as_view(), name="items"),
    path("items/add/", views.ItemCreateView.as_view(), name="item_add"),
    path("items/<int:pk>/edit/", views.ItemUpdateView.as_view(), name="item_edit"),
    path("items/<int:pk>/delete/", views.ItemDeleteView.as_view(), name="item_delete"),
    path("items/<int:pk>/toggle/", views.item_toggle, name="item_toggle"),

    # Categories
    path("categories/", views.CategoryListView.as_view(), name="categories"),
    path("categories/add/", views.CategoryCreateView.as_view(), name="category_add"),
    path("categories/defaults/", views.category_defaults, name="category_defaults"),
    path("categories/<int:pk>/edit/", views.CategoryUpdateView.as_view(), name="category_edit"),
    path("categories/<int:pk>/delete/", views.CategoryDeleteView.as_view(), name="category_delete"),

    # Tables
    path("tables/", views.TableListView.as_view(), name="tables"),
    path("tables/add/", views.TableCreateView.as_view(), name="table_add"),
    path("tables/print/", views.tables_print, name="tables_print"),
    path("tables/<int:pk>/edit/", views.TableUpdateView.as_view(), name="table_edit"),
    path("tables/<int:pk>/delete/", views.TableDeleteView.as_view(), name="table_delete"),
    path("tables/<int:pk>/qr.svg", views.table_qr, name="table_qr"),

    # Orders
    path("orders/", views.orders_list, name="orders"),
    path("orders/export.csv", views.orders_export, name="orders_export"),
    path("orders/<int:pk>/", views.order_detail, name="order_detail"),
    path("orders/<int:pk>/status/", views.order_set_status, name="order_status"),
    path("orders/<int:pk>/paid/", views.order_set_paid, name="order_paid"),
    path("orders/<int:pk>/complete/", views.complete_order, name="order_complete"),

    # Coupons
    path("coupons/", views.CouponListView.as_view(), name="coupons"),
    path("coupons/add/", views.CouponCreateView.as_view(), name="coupon_add"),
    path("coupons/<int:pk>/edit/", views.CouponUpdateView.as_view(), name="coupon_edit"),
    path("coupons/<int:pk>/delete/", views.CouponDeleteView.as_view(), name="coupon_delete"),

    path("settings/", views.venue_settings, name="settings"),
    path("settings/password/", views.change_password, name="change_password"),
]
