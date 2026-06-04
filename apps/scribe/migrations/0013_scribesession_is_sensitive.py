from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("scribe", "0012_drugalias_druginteractioncheck")]

    operations = [
        migrations.AddField(
            model_name="scribesession",
            name="is_sensitive",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Mark encounters containing HIV status, mental health, "
                    "reproductive health, or substance-use data. Enables "
                    "enhanced audit logging and blocks share-link generation."
                ),
            ),
        ),
    ]
