from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("pages", "0007_jsondata_size_bytes_and_rate_limit_bucket"),
    ]

    operations = [
        migrations.AddField(
            model_name="accountprofile",
            name="authenticated_orcid",
            field=models.CharField(
                blank=True,
                editable=False,
                max_length=19,
                null=True,
                unique=True,
            ),
        ),
        migrations.AddField(
            model_name="accountprofile",
            name="orcid_authenticated_at",
            field=models.DateTimeField(blank=True, editable=False, null=True),
        ),
    ]
