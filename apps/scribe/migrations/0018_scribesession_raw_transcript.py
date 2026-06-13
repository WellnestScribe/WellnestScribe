from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("scribe", "0017_scribesession_patient_gender"),
    ]

    operations = [
        migrations.AddField(
            model_name="scribesession",
            name="raw_transcript",
            field=models.TextField(blank=True),
        ),
    ]
