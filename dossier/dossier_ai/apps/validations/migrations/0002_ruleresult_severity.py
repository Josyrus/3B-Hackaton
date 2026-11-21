from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('validations', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='ruleresult',
            name='severity',
            field=models.CharField(default='relevante', max_length=12),
        ),
    ]
