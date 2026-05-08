from django.db import migrations


def repair_scribe_schema(apps, schema_editor):
    models_to_repair = [
        apps.get_model("scribe", "ScribeSession"),
        apps.get_model("scribe", "SOAPNote"),
        apps.get_model("scribe", "SessionEvent"),
        apps.get_model("scribe", "NoteShare"),
    ]

    with schema_editor.connection.cursor() as cursor:
        existing_tables = set(
            schema_editor.connection.introspection.table_names(cursor)
        )

    for model in models_to_repair:
        table_name = model._meta.db_table
        if table_name not in existing_tables:
            schema_editor.create_model(model)
            continue

        existing_columns = {
            col.name
            for col in schema_editor.connection.introspection.get_table_description(
                schema_editor.connection.cursor(), table_name
            )
        }

        if model._meta.model_name == "scribesession":
            for field_name in ("chief_complaint",):
                field = model._meta.get_field(field_name)
                if field.column not in existing_columns:
                    schema_editor.add_field(model, field)


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("scribe", "0002_noteshare"),
    ]

    operations = [
        migrations.RunPython(repair_scribe_schema, migrations.RunPython.noop),
    ]
