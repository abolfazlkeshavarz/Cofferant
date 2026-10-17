from django import forms

from .models import PLAN_CHOICES, License
from .tenancy import valid_slug

INPUT = {"class": "input"}


class LicenseCreateForm(forms.ModelForm):
    class Meta:
        model = License
        fields = ["business_name", "contact_name", "phone", "email", "mode", "slug", "domain",
                  "plan", "price_paid", "notes"]
        widgets = {
            "business_name": forms.TextInput(attrs=INPUT),
            "contact_name": forms.TextInput(attrs=INPUT),
            "phone": forms.TextInput(attrs={**INPUT, "dir": "ltr"}),
            "email": forms.EmailInput(attrs={**INPUT, "dir": "ltr"}),
            "mode": forms.Select(attrs=INPUT),
            "slug": forms.TextInput(attrs={**INPUT, "dir": "ltr", "placeholder": "mycafe"}),
            "domain": forms.TextInput(attrs={**INPUT, "dir": "ltr", "placeholder": "menu.mycafe.com"}),
            "plan": forms.Select(attrs=INPUT),
            "price_paid": forms.NumberInput(attrs={**INPUT, "min": 0}),
            "notes": forms.Textarea(attrs={**INPUT, "rows": 3}),
        }

    def clean(self):
        data = super().clean()
        mode, slug = data.get("mode"), (data.get("slug") or "").strip().lower()
        if mode == License.HOSTED:
            if not slug:
                self.add_error("slug", "برای پنل روی دامنه ما، زیردامنه لازم است.")
            elif not valid_slug(slug):
                self.add_error("slug", "زیردامنه نامعتبر یا رزرو شده است (۳ تا ۳۰ حرف انگلیسی/عدد/خط تیره).")
            data["slug"] = slug
        else:
            data["slug"] = None
        return data


class RenewForm(forms.Form):
    plan = forms.ChoiceField(label="مدت اشتراک", choices=PLAN_CHOICES, widget=forms.Select(attrs=INPUT))
    price = forms.IntegerField(label="مبلغ دریافتی (تومان)", min_value=0, initial=0, widget=forms.NumberInput(attrs=INPUT))


class CancelForm(forms.Form):
    reason = forms.CharField(label="دلیل (اختیاری)", required=False, max_length=200, widget=forms.TextInput(attrs=INPUT))
