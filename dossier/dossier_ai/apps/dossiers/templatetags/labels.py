from django import template

from apps.dossiers import labels as L

register = template.Library()


@register.filter
def label(value):
    """Etiqueta legible de un identificador técnico (regla, campo, tipo documental, resultado…)."""
    return L.label(value)


@register.filter
def humanize(value):
    """Reemplaza identificadores técnicos dentro de un texto libre."""
    return L.humanize(value)


@register.filter
def humanize_list(values):
    return [L.humanize(v) for v in values or []]


@register.filter
def agent_label(value):
    return L.AGENTS.get(str(value).lower(), value)
