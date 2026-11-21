from django.contrib.auth.models import AbstractUser
from django.db import models


class Role(models.TextChoices):
    ANALYST = "legal_analyst", "Analista legal"
    SUPERVISOR = "legal_supervisor", "Supervisor legal"
    TECH_ADMIN = "tech_admin", "Administrador técnico"


class User(AbstractUser):
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.ANALYST)

    @property
    def can_correct(self) -> bool:
        return self.role in (Role.SUPERVISOR, Role.TECH_ADMIN) or self.is_superuser

    @property
    def is_tech_admin(self) -> bool:
        return self.role == Role.TECH_ADMIN or self.is_superuser
