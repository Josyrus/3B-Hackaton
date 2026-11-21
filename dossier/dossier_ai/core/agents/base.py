"""Base de agentes. Los agentes son funciones puras sobre el estado: devuelven una salida
estructurada; solo el supervisor la aplica al estado compartido."""
from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel

from ..contracts import DossierState
from ..rules import RuleSet


class Agent(ABC):
    name: str
    stage: str

    def __init__(self, ruleset: RuleSet) -> None:
        self.ruleset = ruleset

    @abstractmethod
    def run(self, state: DossierState) -> BaseModel: ...
