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


@register.filter
def count_by(items, spec):
    """Cuenta elementos cuyo atributo coincide: `rules|count_by:"outcome=cumple"`. Solo presentación (indicadores)."""
    attr, _, expected = str(spec).partition("=")
    return sum(1 for i in items if str(getattr(i, attr, "")) == expected)


@register.filter
def not_approved(dossiers):
    """Expedientes ya dictaminados que no fueron aprobados (para el bloque 'Requieren atención')."""
    return [d for d in dossiers if d.recommendation and d.recommendation != "cumple"]


@register.filter
def pct(value, total):
    try:
        return round(100 * float(value) / float(total)) if float(total) else 0
    except (TypeError, ValueError):
        return 0
