from django.conf import settings
from django.shortcuts import render

from licensing import services
from licensing.models import PLANS


def index(request):
    # On the developer's own domain the front page is the sales page; on a venue's domain it is the venue page.
    if settings.DEPLOYMENT_MODE == "platform" and not getattr(request, "tenant", None):
        plans, prices = [], services.get_prices()
        for code, label, days in PLANS:
            price = prices.get(code, 0)
            months = (days or 0) / 30
            plans.append({
                "code": code, "label": label, "price": price,
                "per_month": int(price / months) if months else None,
                "best": code == "1y",
            })
        return render(request, "home/platform.html", {"plans": plans, "sales_contact": settings.SALES_CONTACT})
    return render(request, "home/index.html")


def about(request):
    return render(request, "home/about.html")


def contact(request):
    return render(request, "home/contact.html")
