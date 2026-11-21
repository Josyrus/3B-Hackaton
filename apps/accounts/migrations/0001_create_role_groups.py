"""Crea los grupos que representan los roles del sistema."""
from django.db import migrations

ROLE_GROUPS = ("analista", "coordinador", "admin_tecnico")


def create_groups(apps, schema_editor):
    group_model = apps.get_model("auth", "Group")
    for name in ROLE_GROUPS:
        group_model.objects.get_or_create(name=name)


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(create_groups, migrations.RunPython.noop),
    ]
