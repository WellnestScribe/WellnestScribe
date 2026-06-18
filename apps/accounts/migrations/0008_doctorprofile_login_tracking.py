from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0007_doctorprofile_preferred_language"),
    ]

    operations = [
        migrations.AddField(
            model_name="doctorprofile",
            name="last_login_ip",
            field=models.GenericIPAddressField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="doctorprofile",
            name="last_login_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="doctorprofile",
            name="previous_login_ip",
            field=models.GenericIPAddressField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="doctorprofile",
            name="previous_login_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
