from functools import wraps

from django.core.exceptions import PermissionDenied


def role_required(check: str):
    """Decorador: exige autenticación y que la propiedad `check` del usuario sea verdadera."""
    def deco(view):
        @wraps(view)
        def wrapper(request, *a, **kw):
            if not request.user.is_authenticated:
                from django.contrib.auth.views import redirect_to_login
                return redirect_to_login(request.get_full_path())
            if not getattr(request.user, check):
                raise PermissionDenied
            return view(request, *a, **kw)
        return wrapper
    return deco
