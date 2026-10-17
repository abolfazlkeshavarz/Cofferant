from functools import wraps

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.shortcuts import redirect


def staff_required(view):
    """Require an authenticated, active staff user (anonymous -> login, non-staff -> home)."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        user = request.user
        if not user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not (user.is_staff and user.is_active):
            messages.error(request, "شما به این بخش دسترسی ندارید.")
            return redirect("home")
        return view(request, *args, **kwargs)

    return wrapper
