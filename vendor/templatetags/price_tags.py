# vendor/templatetags/price_tags.py
from django import template

register = template.Library()

@register.filter
def money(value):
    try:
        n = int(value)
    except:
        return value

    return f"{n:,}"
