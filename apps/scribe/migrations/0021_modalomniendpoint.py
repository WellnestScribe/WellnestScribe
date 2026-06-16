from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("scribe", "0020_notefeedback"),
    ]

    operations = [
        migrations.CreateModel(
            name="ModalOmniEndpoint",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("label", models.CharField(blank=True, max_length=100)),
                ("base_url", models.URLField(max_length=300)),
                ("api_key", models.CharField(max_length=200)),
                ("status", models.CharField(
                    choices=[("active", "Active"), ("exhausted", "Exhausted"), ("disabled", "Disabled")],
                    default="active",
                    max_length=20,
                )),
                ("priority", models.PositiveIntegerField(default=0, help_text="Lower = used first")),
                ("call_count", models.PositiveIntegerField(default=0)),
                ("audio_seconds_used", models.FloatField(default=0.0)),
                ("last_used_at", models.DateTimeField(blank=True, null=True)),
                ("exhausted_at", models.DateTimeField(blank=True, null=True)),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "Modal Omni endpoint",
                "ordering": ["priority", "created_at"],
            },
        ),
    ]
