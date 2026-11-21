"""Vistas de presentación de accounts (sin lógica de negocio)."""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView

from .roles import get_user_roles


class HomeView(LoginRequiredMixin, TemplateView):
    """Página de inicio provisional; el dashboard llega en la Fase 6."""

    template_name = "home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["roles"] = sorted(role.value for role in get_user_roles(self.request.user))
        return context
