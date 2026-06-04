from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("scribe", "0013_scribesession_is_sensitive"),
    ]

    operations = [
        migrations.AddField(
            model_name="scribesession",
            name="consent_acknowledged_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
                help_text="Timestamp when the doctor confirmed verbal patient consent before recording.",
            ),
        ),
    ]
