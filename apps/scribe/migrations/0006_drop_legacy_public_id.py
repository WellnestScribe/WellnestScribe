from django.db import migrations


def drop_legacy_public_id(apps, schema_editor):
    model = apps.get_model("scribe", "ScribeSession")
    table_name = model._meta.db_table

    with schema_editor.connection.cursor() as cursor:
        existing_columns = {
            col.name
            for col in schema_editor.connection.introspection.get_table_description(
                cursor, table_name
            )
        }

    if "public_id" in existing_columns:
        quoted_table = schema_editor.quote_name(table_name)
        quoted_column = schema_editor.quote_name("public_id")
        schema_editor.execute(
            f"ALTER TABLE {quoted_table} DROP COLUMN {quoted_column}"
        )


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("scribe", "0005_align_nullable_fields"),
    ]

    operations = [
        migrations.RunPython(drop_legacy_public_id, migrations.RunPython.noop),
    ]
