from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('documents', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='documentpage',
            name='method',
            field=models.CharField(default='native', max_length=10),
        ),
        migrations.AddField(
            model_name='documentpage',
            name='ocr_confidence',
            field=models.FloatField(default=100.0),
        ),
        migrations.AddField(
            model_name='documentpage',
            name='is_blank',
            field=models.BooleanField(default=False),
        ),
    ]
