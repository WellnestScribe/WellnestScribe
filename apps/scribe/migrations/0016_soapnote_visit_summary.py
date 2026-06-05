from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("scribe", "0015_alter_scribesession_length_mode"),
    ]

    operations = [
        migrations.AddField(
            model_name="soapnote",
            name="visit_summary",
            field=models.TextField(blank=True),
        ),
    ]
