from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("pages", "0015_researchcollection"),
    ]

    operations = [
        migrations.AddField(
            model_name="jsondata",
            name="collection_summary",
            field=models.JSONField(blank=True, editable=False, null=True),
        ),
    ]
