from django.db import migrations, models


def ensure_encounter_voided_reason_column(apps, schema_editor):
    Encounter = apps.get_model("emr", "Encounter")
    table_name = Encounter._meta.db_table

    with schema_editor.connection.cursor() as cursor:
        existing_tables = set(
            schema_editor.connection.introspection.table_names(cursor)
        )
        if table_name not in existing_tables:
            return

        existing_columns = {
            col.name
            for col in schema_editor.connection.introspection.get_table_description(
                cursor, table_name
            )
        }

    if "voided_reason" in existing_columns:
        return

    field = models.TextField(blank=True, default="")
    field.set_attributes_from_name("voided_reason")
    schema_editor.add_field(Encounter, field)


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("emr", "0004_appointment_color_and_more"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(
                    ensure_encounter_voided_reason_column,
                    migrations.RunPython.noop,
                ),
            ],
            state_operations=[
                migrations.AddField(
                    model_name="encounter",
                    name="voided_reason",
                    field=models.TextField(blank=True, default=""),
                ),
            ],
        ),
    ]
