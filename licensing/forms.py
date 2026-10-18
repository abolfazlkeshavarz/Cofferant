import re

from django import forms

from .models import PLAN_CHOICES, License
from .tenancy import valid_slug

INPUT = {"class": "input"}


HOST_RE = re.compile(r"^(?=.{4,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


def clean_domain_value(raw, instance=None):
    """Normalise and validate a customer's own domain (blank is fine)."""
    from django.conf import settings

    value = (raw or "").strip().lower().rstrip(".")
    value = re.sub(r"^https?://", "", value).split("/")[0]
    if not value:
        return ""
    if not HOST_RE.match(value):
        raise forms.ValidationError("آدرس دامنه نامعتبر است (مثل menu.mycafe.com).")
    root = settings.PLATFORM_DOMAIN
    if value == root or value.endswith("." + root):
        raise forms.ValidationError("این دامنه متعلق به خود پلتفرم است؛ دامنه جداگانه مشتری را وارد کنید.")
    for alias in settings.PLATFORM_ALIAS_DOMAINS:
        if value == alias or value.endswith("." + alias):
            raise forms.ValidationError(
                f"«{alias}» هنوز به‌عنوان دامنه قدیمی پلتفرم فعال است (PLATFORM_ALIAS_DOMAINS در فایل .env). "
                f"اگر دیگر لازم نیست، روی سرور بزنید: make change-domain DOMAIN={root} DROP_OLD=1")
    qs = License.objects.filter(domain__iexact=value)
    if instance is not None and instance.pk:
        qs = qs.exclude(pk=instance.pk)
    other = qs.first()
    if other is not None:
        where = " (در سطل زباله است؛ از آنجا حذف نهایی یا دامنه‌اش را خالی کنید)" if other.in_trash else ""
        raise forms.ValidationError(f"این دامنه قبلاً برای «{other.business_name}» ثبت شده است{where}.")
    return value


class LicenseCreateForm(forms.ModelForm):
    class Meta:
        model = License
        fields = ["business_name", "contact_name", "phone", "email", "mode", "slug", "domain",
                  "owner_username", "plan", "price_paid", "notes"]
        widgets = {
            "business_name": forms.TextInput(attrs=INPUT),
            "contact_name": forms.TextInput(attrs=INPUT),
            "phone": forms.TextInput(attrs={**INPUT, "dir": "ltr"}),
            "email": forms.EmailInput(attrs={**INPUT, "dir": "ltr"}),
            "mode": forms.Select(attrs=INPUT),
            "slug": forms.TextInput(attrs={**INPUT, "dir": "ltr", "placeholder": "mycafe"}),
            "domain": forms.TextInput(attrs={**INPUT, "dir": "ltr", "placeholder": "menu.mycafe.com"}),
            "owner_username": forms.TextInput(attrs={**INPUT, "dir": "ltr"}),
            "plan": forms.Select(attrs=INPUT),
            "price_paid": forms.NumberInput(attrs={**INPUT, "min": 0}),
            "notes": forms.Textarea(attrs={**INPUT, "rows": 3}),
        }

    owner_password = forms.CharField(
        label="رمز ورود مدیر مجموعه", required=False, min_length=8, max_length=64,
        widget=forms.TextInput(attrs={**INPUT, "dir": "ltr", "autocomplete": "off", "placeholder": "خالی = ساخت خودکار"}),
        help_text="حداقل ۸ نویسه. اگر خالی بگذارید، یک رمز تصادفی ساخته می‌شود.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["owner_username"].required = False  # blank = "owner"
        self.fields["domain"].required = False

    def clean_domain(self):
        return clean_domain_value(self.cleaned_data.get("domain"), self.instance)

    def clean_owner_username(self):
        name = (self.cleaned_data.get("owner_username") or "owner").strip()
        if not re.match(r"^[\w.@+-]{3,150}$", name):
            raise forms.ValidationError("نام کاربری باید ۳ تا ۱۵۰ نویسه و بدون فاصله باشد.")
        return name

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


class OwnerPasswordForm(forms.Form):
    password = forms.CharField(
        label="رمز جدید", min_length=8, max_length=64,
        widget=forms.TextInput(attrs={**INPUT, "dir": "ltr", "autocomplete": "off"}),
    )


class PurgeForm(forms.Form):
    confirm = forms.CharField(label="نام کسب‌وکار را برای تایید بنویسید", max_length=120,
                              widget=forms.TextInput(attrs=INPUT))


class PricesForm(forms.Form):
    def __init__(self, *args, **kwargs):
        initial = kwargs.pop("prices", {})
        super().__init__(*args, **kwargs)
        for code, label in PLAN_CHOICES:
            self.fields[code] = forms.IntegerField(
                label=label, min_value=0, max_value=10**10, initial=initial.get(code, 0),
                widget=forms.NumberInput(attrs={**INPUT, "inputmode": "numeric"}),
            )


class DomainForm(forms.Form):
    domain = forms.CharField(
        label="دامنه اختصاصی مشتری", required=False, max_length=253,
        widget=forms.TextInput(attrs={**INPUT, "dir": "ltr", "placeholder": "menu.mycafe.com"}),
    )

    def __init__(self, *args, instance=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance = instance

    def clean_domain(self):
        return clean_domain_value(self.cleaned_data.get("domain"), self.instance)
