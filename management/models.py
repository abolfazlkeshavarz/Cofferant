from django.db import models
import secrets


# -----------------------------
# Item (Product)
# -----------------------------
class Item(models.Model):
    CHOICES = (
        ('hot coffee', 'قهوه گرم'),
        ('cold coffee', 'قهوه سرد'),
        ('hot drink', 'نوشیدنی گرم'),
        ('cold drink', 'نوشیدنی سرد'),
        ('cakes', 'کیک و دسر'),
    )

    name = models.CharField(max_length=100)
    drink_type = models.CharField(max_length=100, choices=CHOICES)
    specs = models.TextField(max_length=150)
    price_cents = models.PositiveIntegerField(default=0) 
    customizable = models.BooleanField(
        default=False,
        help_text="Allow customer to add custom notes/details (e.g., 70/30, extra sugar)"
    )
    image = models.ImageField(upload_to='images')
    
    is_available = models.BooleanField(
        default=True,
        help_text="Uncheck this if the item is temporarily unavailable (ناموجود)"
    )

    def __str__(self):
        return self.name
# -----------------------------
# Table (QR-enabled)
# -----------------------------
def make_qr_slug():
    return secrets.token_urlsafe(6)

class Table(models.Model):
    number = models.CharField(max_length=50)   # e.g., "T1", "A2"
    qr_slug = models.CharField(max_length=100, unique=True, default=make_qr_slug)
    notes = models.CharField(max_length=200, blank=True)

    def __str__(self):
        return f"Table {self.number}"


# -----------------------------
# Order (one per customer visit)
# -----------------------------
class Order(models.Model):
    STATUS_CHOICES = [
        ("new", "New"),
        ("preparing", "Preparing"),
        ("ready", "Ready"),
        ("delivered", "Delivered"),
        ("cancelled", "Cancelled"),
    ]

    created_at = models.DateTimeField(auto_now_add=True)
    table = models.ForeignKey(
        Table,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders"
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="new")
    total_cents = models.PositiveIntegerField(default=0)  # Updated after order creation

    customer_name = models.CharField(max_length=150, blank=True)
    customer_phone = models.CharField(max_length=50, blank=True)
    notes = models.TextField(blank=True)

    paid = models.BooleanField(default=False)

    def __str__(self):
        return f"Order #{self.id} - {self.get_status_display()}"

    @property
    def total_items(self):
        return sum(item.quantity for item in self.items.all())

    @property
    def total_price(self):
        return sum(item.line_total() for item in self.items.all())


# -----------------------------
# OrderItem (product inside an order)
# -----------------------------
class OrderItem(models.Model):
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="items"
    )
    product = models.ForeignKey(
        "management.Item",
        on_delete=models.SET_NULL,
        null=True
    )
    quantity = models.PositiveIntegerField(default=1)

    # Snapshot of price at time of order
    unit_price_cents = models.PositiveIntegerField(default=0)

    # Special customer note (e.g. 70/30 espresso)
    note = models.CharField(max_length=200, blank=True)

    def line_total(self):
        return self.unit_price_cents * self.quantity

    def __str__(self):
        if self.product:
            return f"{self.quantity} x {self.product.name}"
        return f"{self.quantity} x Deleted Item"
