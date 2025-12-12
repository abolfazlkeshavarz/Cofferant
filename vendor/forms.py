from django import forms
from management.models import Item, Table

class VendorItemForm(forms.ModelForm):
    class Meta:
        model = Item
        fields = ["name", "drink_type", "specs", "price_cents", "customizable", "image", "is_available"]
        labels = {
            "name": "نام محصول",
            "drink_type": "نوع محصول",
            "specs": "توضیحات",
            "price_cents": "قیمت (به تومان)",
            "customizable": "قابل سفارشی‌سازی",
            "image": "تصویر",
            "is_available": "موجود است",
        }
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "مثال: اسپرسو"}),
            "drink_type": forms.Select(attrs={"class": "form-control"}),
            "specs": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "price_cents": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
            "customizable": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            # Use a custom class for styling
            "image": forms.ClearableFileInput(attrs={"class": "custom-image-input"}), 
            "is_available": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

class VendorTableForm(forms.ModelForm):
    class Meta:
        model = Table
        fields = ["number", "notes"]
        labels = {"number": "شماره میز", "notes": "یادداشت (اختیاری)"}
        widgets = {
            "number": forms.TextInput(attrs={"class": "form-control", "placeholder": "مثال: میز 1 یا A2"}),
            "notes": forms.TextInput(attrs={"class": "form-control"}),
        }
