from django.conf import settings

from . import checker


def licensing(request):
    state = getattr(request, "license", None) or checker.current_state()
    return {
        "license": state,
        "deployment_mode": settings.DEPLOYMENT_MODE,
        "is_platform_root": settings.DEPLOYMENT_MODE == "platform" and not getattr(request, "tenant", None),
    }
