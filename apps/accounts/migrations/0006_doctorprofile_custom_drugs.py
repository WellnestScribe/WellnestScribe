from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0005_doctorprofile_custom_terms"),
    ]

    operations = [
        migrations.AddField(
            model_name="doctorprofile",
            name="custom_drugs",
            field=models.JSONField(
                default=list,
                blank=True,
                help_text="Doctor-specific medication names shown in the note editor picker.",
            ),
        ),
    ]
