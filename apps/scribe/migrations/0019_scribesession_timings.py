from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("scribe", "0018_scribesession_raw_transcript"),
    ]

    operations = [
        migrations.AddField(
            model_name="scribesession",
            name="timings",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
