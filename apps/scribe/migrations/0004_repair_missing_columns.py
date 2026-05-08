from django.db import migrations


def repair_all_scribe_columns(apps, schema_editor):
    model_names = ("ScribeSession", "SOAPNote", "SessionEvent", "NoteShare")

    with schema_editor.connection.cursor() as cursor:
        existing_tables = set(
            schema_editor.connection.introspection.table_names(cursor)
        )

    for model_name in model_names:
        model = apps.get_model("scribe", model_name)
        table_name = model._meta.db_table

        if table_name not in existing_tables:
            schema_editor.create_model(model)
            continue

        with schema_editor.connection.cursor() as cursor:
            existing_columns = {
                col.name
                for col in schema_editor.connection.introspection.get_table_description(
                    cursor, table_name
                )
            }

        for field in model._meta.local_fields:
            if field.primary_key:
                continue
            if field.column not in existing_columns:
                schema_editor.add_field(model, field)


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("scribe", "0003_repair_mysql_schema"),
    ]

    operations = [
        migrations.RunPython(repair_all_scribe_columns, migrations.RunPython.noop),
    ]
