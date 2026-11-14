from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("pages", "0018_collection_relationship")]

    operations = [
        migrations.CreateModel(
            name="SavedStudyAnalysis",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=120)),
                ("notes", models.TextField(blank=True, max_length=5000)),
                ("state", models.JSONField(default=dict)),
                ("source_digests", models.JSONField(default=dict, editable=False)),
                ("revision", models.PositiveIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("collection", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                                related_name="saved_analyses", to="pages.researchcollection")),
            ],
            options={"ordering": ("-updated_at", "-pk")},
        ),
    ]
