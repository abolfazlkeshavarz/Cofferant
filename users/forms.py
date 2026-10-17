from django import forms
from django.contrib.auth.forms import UserCreationForm

from .models import CustomUser


class CustomUserCreationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = CustomUser
        fields = ("username", "email", "phone_number")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        labels = {"username": "نام کاربری", "email": "ایمیل", "phone_number": "تلفن",
                  "password1": "رمز عبور", "password2": "تکرار رمز عبور"}
        for name, field in self.fields.items():
            field.label = labels.get(name, field.label)
            field.widget.attrs.setdefault("class", "input")
            field.help_text = ""
        self.fields["username"].widget.attrs["dir"] = "ltr"
        self.fields["email"].widget.attrs["dir"] = "ltr"


class LoginForm(forms.Form):
    username = forms.CharField(
        label="نام کاربری",
        widget=forms.TextInput(attrs={"class": "input", "dir": "ltr", "autocomplete": "username", "autofocus": True}),
    )
    password = forms.CharField(
        label="رمز عبور",
        widget=forms.PasswordInput(attrs={"class": "input", "dir": "ltr", "autocomplete": "current-password"}),
    )
