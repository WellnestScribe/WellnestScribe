from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("scribe", "0014_scribesession_consent_acknowledged_at"),
    ]

    operations = [
        migrations.AlterField(
            model_name="scribesession",
            name="length_mode",
            field=models.CharField(
                choices=[
                    ("concise", "Concise"),
                    ("normal", "Standard"),
                    ("long_form", "Long form"),
                ],
                default="normal",
                max_length=20,
            ),
        ),
    ]
