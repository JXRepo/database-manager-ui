from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("pages", "0009_accountprofile_orcid_disconnected_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="jsondata",
            name="identifier_fingerprint",
            field=models.CharField(
                max_length=64, blank=True, default="", db_index=True, editable=False,
            ),
        ),
    ]
