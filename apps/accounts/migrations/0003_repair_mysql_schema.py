from django.db import migrations


def repair_accounts_schema(apps, schema_editor):
    DoctorProfile = apps.get_model("accounts", "DoctorProfile")
    table_name = DoctorProfile._meta.db_table

    with schema_editor.connection.cursor() as cursor:
        existing_tables = set(
            schema_editor.connection.introspection.table_names(cursor)
        )

    if table_name not in existing_tables:
        schema_editor.create_model(DoctorProfile)
        return

    existing_columns = {
        col.name
        for col in schema_editor.connection.introspection.get_table_description(
            schema_editor.connection.cursor(), table_name
        )
    }

    for field_name in ("role",):
        field = DoctorProfile._meta.get_field(field_name)
        if field.column not in existing_columns:
            schema_editor.add_field(DoctorProfile, field)


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("accounts", "0002_doctorprofile_role"),
    ]

    operations = [
        migrations.RunPython(repair_accounts_schema, migrations.RunPython.noop),
    ]
