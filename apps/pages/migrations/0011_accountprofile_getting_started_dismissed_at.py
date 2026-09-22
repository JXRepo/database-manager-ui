from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("pages", "0010_jsondata_identifier_fingerprint"),
    ]

    operations = [
        migrations.AddField(
            model_name="accountprofile",
            name="getting_started_dismissed_at",
            field=models.DateTimeField(blank=True, editable=False, null=True),
        ),
    ]
