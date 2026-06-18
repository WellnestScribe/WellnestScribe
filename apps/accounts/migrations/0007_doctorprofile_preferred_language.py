from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0006_doctorprofile_custom_drugs"),
    ]

    operations = [
        migrations.AddField(
            model_name="doctorprofile",
            name="preferred_language",
            field=models.CharField(
                choices=[
                    ("jam_Latn", "Jamaican Creole (Patois)"),
                    ("eng_Latn", "English"),
                    ("spa_Latn", "Spanish"),
                    ("fra_Latn", "French"),
                    ("hat_Latn", "Haitian Creole"),
                    ("por_Latn", "Portuguese"),
                ],
                default="jam_Latn",
                help_text="Language spoken during consultations — used by the ASR model.",
                max_length=20,
            ),
        ),
    ]
