from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("pages", "0008_accountprofile_authenticated_orcid"),
    ]

    operations = [
        migrations.AddField(
            model_name="accountprofile",
            name="orcid_disconnected_at",
            field=models.DateTimeField(
                blank=True,
                default=None,
                editable=False,
                null=True,
            ),
        ),
    ]
