from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from management.models import Category, Item

from .forms import CustomUserCreationForm, LoginForm
from .models import CustomUser


def _home_for(user, request=None):
    """Where to send someone after signing in. The developer lands on the developer panel."""
    if (request is not None and user.is_superuser and settings.DEPLOYMENT_MODE == "platform"
            and not getattr(request, "tenant", None)):
        return "developer:dashboard"
    return "vendor:dashboard" if user.is_staff else "profile"


def register(request):
    """First-run setup: only available while no staff account exists.

    The first account becomes the owner (staff + superuser). Afterwards new staff
    are created from the Django admin, so strangers can't self-register into the panel.
    """
    if CustomUser.objects.filter(is_staff=True).exists():
        messages.info(request, "ثبت‌نام عمومی غیرفعال است. برای ساخت حساب جدید با مدیر تماس بگیرید.")
        return redirect("login")

    if request.method == "POST":
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.is_staff = True
            user.is_superuser = True
            user.save()
            login(request, user)
            messages.success(request, "حساب مدیر ساخته شد. به کافیرانت خوش آمدید!")
            return redirect("vendor:dashboard")
    else:
        form = CustomUserCreationForm()
    return render(request, "users/register.html", {"form": form})


def sign_in(request):
    if request.user.is_authenticated:
        return redirect(_home_for(request.user, request))

    form = LoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = authenticate(
            request,
            username=form.cleaned_data["username"],
            password=form.cleaned_data["password"],
        )
        if user:
            login(request, user)
            nxt = request.POST.get("next") or request.GET.get("next")
            if nxt and url_has_allowed_host_and_scheme(nxt, {request.get_host()}, request.is_secure()):
                return redirect(nxt)
            return redirect(_home_for(user, request))
        form.add_error(None, "نام کاربری یا رمز عبور اشتباه است.")
    can_setup = not CustomUser.objects.filter(is_staff=True).exists()
    return render(request, "users/login.html", {"form": form, "can_setup": can_setup,
                                                  "next": request.GET.get("next", "")})


@login_required
def profile(request):
    return render(request, "users/profile.html")


@require_POST
def sign_out(request):
    logout(request)
    return redirect("home")


def products_list(request):
    """Public read-only menu (no ordering) grouped by the vendor's categories."""
    products = list(Item.objects.filter(is_available=True))
    types = []
    for cat in Category.objects.filter(is_active=True):
        group = [p for p in products if p.category_id == cat.id]
        if group:
            types.append({"code": str(cat.id), "label": cat.label, "products": group, "count": len(group)})
    rest = [p for p in products if p.category_id is None]
    if rest:
        types.append({"code": "0", "label": "سایر", "products": rest, "count": len(rest)})
    return render(request, "users/products_list.html", {"types": types})
