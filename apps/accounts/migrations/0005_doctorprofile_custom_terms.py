from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0004_doctorprofile_suggestive_assist"),
    ]

    operations = [
        migrations.AddField(
            model_name="doctorprofile",
            name="custom_terms",
            field=models.TextField(
                blank=True,
                help_text=(
                    "Regional or personal abbreviations, one per line. "
                    "e.g. 'HTN = hypertension', 'SLE = systemic lupus erythematosus'. "
                    "Added to every note-generation prompt."
                ),
            ),
        ),
    ]
