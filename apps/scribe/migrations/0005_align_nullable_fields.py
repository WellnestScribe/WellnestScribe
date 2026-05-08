from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("scribe", "0004_repair_missing_columns"),
    ]

    operations = [
        migrations.AlterField(
            model_name="scribesession",
            name="audio_file",
            field=models.FileField(
                blank=True, null=True, upload_to="scribe_audio/%Y/%m/%d/"
            ),
        ),
        migrations.AlterField(
            model_name="scribesession",
            name="duration_seconds",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="scribesession",
            name="finalized_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
