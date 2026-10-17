from django import template

register = template.Library()

_FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


@register.filter
def fa(value):
    """Convert Latin digits to Persian digits."""
    return str(value).translate(_FA)


@register.filter
def money(value):
    """1250000 -> ۱٬۲۵۰٬۰۰۰"""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return value
    return f"{n:,}".replace(",", "٬").translate(_FA)
