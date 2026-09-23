import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("pages", "0011_accountprofile_getting_started_dismissed_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="accountprofile",
            name="display_name",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="accountprofile",
            name="department",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="accountprofile",
            name="position",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="accountprofile",
            name="website",
            field=models.URLField(
                blank=True,
                max_length=500,
                validators=[django.core.validators.URLValidator(schemes=["http", "https"])],
            ),
        ),
        migrations.AddField(
            model_name="accountprofile",
            name="research_keywords",
            field=models.CharField(blank=True, max_length=1000),
        ),
    ]
