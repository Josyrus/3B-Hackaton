"""Specification: condiciones de búsqueda componibles que se traducen a Q de Django."""
from __future__ import annotations

from datetime import date

from django.db.models import Q


class Spec:
    def __init__(self, q: Q) -> None:
        self.q = q

    def __and__(self, other: "Spec") -> "Spec":
        return Spec(self.q & other.q)

    def __or__(self, other: "Spec") -> "Spec":
        return Spec(self.q | other.q)


def status_is(v: str) -> Spec: return Spec(Q(status=v))
def recommendation_is(v: str) -> Spec: return Spec(Q(recommendation=v))
def created_from(d: date) -> Spec: return Spec(Q(created_at__date__gte=d))
def created_to(d: date) -> Spec: return Spec(Q(created_at__date__lte=d))
def all_dossiers() -> Spec: return Spec(Q())


def from_params(params) -> Spec:
    spec = all_dossiers()
    if v := params.get("status"):
        spec &= status_is(v)
    if v := params.get("recommendation"):
        spec &= recommendation_is(v)
    for key, fn in (("from", created_from), ("to", created_to)):
        if v := params.get(key):
            try:
                spec &= fn(date.fromisoformat(v))
            except ValueError:
                continue
    return spec
