from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("pages", "0014_jsondata_identifier_lookup"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ResearchCollection",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=200)),
                ("description", models.TextField(blank=True, max_length=2000)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("members", models.ManyToManyField(blank=True, related_name="research_collections", to="pages.jsondata")),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="research_collections", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("-updated_at", "-pk")},
        ),
    ]
