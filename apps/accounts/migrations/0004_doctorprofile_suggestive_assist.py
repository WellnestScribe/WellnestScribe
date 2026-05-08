from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0003_repair_mysql_schema"),
    ]

    operations = [
        migrations.AddField(
            model_name="doctorprofile",
            name="suggestive_assist",
            field=models.BooleanField(default=False),
        ),
    ]
