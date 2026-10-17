from django import forms

from management.models import Coupon, Item, Table, Venue

INPUT = {"class": "input"}


class VendorItemForm(forms.ModelForm):
    class Meta:
        model = Item
        fields = ["name", "drink_type", "specs", "price_cents", "prep_minutes", "customizable",
                  "is_popular", "image", "is_available"]
        labels = {
            "name": "نام محصول",
            "drink_type": "دسته‌بندی",
            "specs": "توضیحات",
            "price_cents": "قیمت (تومان)",
            "prep_minutes": "زمان آماده‌سازی (دقیقه)",
            "customizable": "مشتری بتواند توضیح اضافه کند (مثلاً ۷۰/۳۰)",
            "is_popular": "نمایش در «محبوب‌ترین‌ها»",
            "image": "تصویر",
            "is_available": "موجود است",
        }
        widgets = {
            "name": forms.TextInput(attrs={**INPUT, "placeholder": "مثال: اسپرسو"}),
            "drink_type": forms.Select(attrs=INPUT),
            "specs": forms.Textarea(attrs={**INPUT, "rows": 3, "maxlength": 150}),
            "price_cents": forms.NumberInput(attrs={**INPUT, "min": 0, "inputmode": "numeric"}),
            "prep_minutes": forms.NumberInput(attrs={**INPUT, "min": 1, "max": 120}),
            "image": forms.FileInput(attrs={"accept": "image/*"}),
        }

    def clean_image(self):
        img = self.cleaned_data.get("image")
        if img and hasattr(img, "size") and img.size > 5 * 1024 * 1024:
            raise forms.ValidationError("حجم تصویر باید کمتر از ۵ مگابایت باشد.")
        return img


class VendorTableForm(forms.ModelForm):
    class Meta:
        model = Table
        fields = ["number", "notes"]
        labels = {"number": "شماره / نام میز", "notes": "یادداشت (اختیاری)"}
        widgets = {
            "number": forms.TextInput(attrs={**INPUT, "placeholder": "مثال: ۱ یا A2"}),
            "notes": forms.TextInput(attrs=INPUT),
        }

    def clean_number(self):
        number = self.cleaned_data["number"].strip()
        qs = Table.objects.filter(number__iexact=number)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("میزی با این شماره از قبل وجود دارد.")
        return number


class VenueForm(forms.ModelForm):
    class Meta:
        model = Venue
        fields = ["name", "tagline", "accent_color", "secondary_color", "logo", "phone", "address", "instagram",
                  "wifi_name", "wifi_password", "notice", "accepting_orders",
                  "tax_percent", "service_percent", "tips_enabled",
                  "online_payment_enabled", "zarinpal_merchant_id", "zarinpal_sandbox"]
        widgets = {
            "name": forms.TextInput(attrs=INPUT),
            "tagline": forms.TextInput(attrs=INPUT),
            "accent_color": forms.TextInput(attrs={"type": "color", "class": "input input-color"}),
            "secondary_color": forms.TextInput(attrs={"type": "color", "class": "input input-color"}),
            "tax_percent": forms.NumberInput(attrs={**INPUT, "min": 0, "max": 30}),
            "service_percent": forms.NumberInput(attrs={**INPUT, "min": 0, "max": 30}),
            "zarinpal_merchant_id": forms.TextInput(attrs={**INPUT, "dir": "ltr", "placeholder": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"}),
            "logo": forms.FileInput(attrs={"accept": "image/*"}),
            "phone": forms.TextInput(attrs={**INPUT, "dir": "ltr"}),
            "address": forms.TextInput(attrs=INPUT),
            "instagram": forms.TextInput(attrs={**INPUT, "dir": "ltr", "placeholder": "@yourcafe"}),
            "wifi_name": forms.TextInput(attrs={**INPUT, "dir": "ltr"}),
            "wifi_password": forms.TextInput(attrs={**INPUT, "dir": "ltr"}),
            "notice": forms.TextInput(attrs={**INPUT, "placeholder": "مثال: امروز تا ساعت ۲۲ باز هستیم"}),
        }


    def clean(self):
        data = super().clean()
        if data.get("online_payment_enabled") and not (data.get("zarinpal_merchant_id") or "").strip():
            self.add_error("zarinpal_merchant_id", "برای پرداخت آنلاین مرچنت‌کد زرین‌پال را وارد کنید.")
        return data


class CouponForm(forms.ModelForm):
    class Meta:
        model = Coupon
        fields = ["code", "percent", "amount", "min_order", "max_uses", "expires_at", "is_active"]
        widgets = {
            "code": forms.TextInput(attrs={**INPUT, "dir": "ltr", "placeholder": "WELCOME10"}),
            "percent": forms.NumberInput(attrs={**INPUT, "min": 0, "max": 100}),
            "amount": forms.NumberInput(attrs={**INPUT, "min": 0}),
            "min_order": forms.NumberInput(attrs={**INPUT, "min": 0}),
            "max_uses": forms.NumberInput(attrs={**INPUT, "min": 1}),
            "expires_at": forms.DateTimeInput(attrs={**INPUT, "type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        }

    def clean(self):
        data = super().clean()
        pct, amt = data.get("percent") or 0, data.get("amount") or 0
        if bool(pct) == bool(amt):
            raise forms.ValidationError("فقط یکی از «درصد تخفیف» یا «مبلغ ثابت» را پر کنید.")
        return data
