"""Align nullable session fields with the Django model.

`ScribeSession.duration_seconds` is `null=True, blank=True` in models.py
but the MySQL repair migration left the column as `INT NOT NULL`. INSERTs
from the text-only "Generate from text" path send NULL → MySQL rejects:

    (1048, "Column 'duration_seconds' cannot be null")

Also normalises other fields that should be nullable but aren't on the
current MySQL schema. Vendor-gated (MySQL only). SQLite no-ops.
"""

from django.db import migrations


# (column_name, NULLABLE column definition for MySQL)
COLUMN_FIXES = [
    ("duration_seconds", "INT UNSIGNED NULL"),
    ("error_message",    "LONGTEXT NULL"),
    ("transcript",       "LONGTEXT NULL"),
    ("title",            "VARCHAR(160) NULL DEFAULT ''"),
    ("chief_complaint",  "VARCHAR(200) NULL DEFAULT ''"),
    ("patient_name",     "VARCHAR(120) NULL DEFAULT ''"),
    ("patient_identifier","VARCHAR(120) NULL DEFAULT ''"),
    ("active_conditions","VARCHAR(200) NULL DEFAULT ''"),
]


def relax_nulls(apps, schema_editor):
    connection = schema_editor.connection
    if connection.vendor != "mysql":
        return
    cur = connection.cursor()
    cur.execute(
        "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'scribe_scribesession'"
    )
    existing = {row[0] for row in cur.fetchall()}
    for col, definition in COLUMN_FIXES:
        if col in existing:
            try:
                cur.execute(
                    f"ALTER TABLE scribe_scribesession MODIFY `{col}` {definition}"
                )
            except Exception:
                pass


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("scribe", "0010_restore_soapnote_export_count"),
    ]

    operations = [
        migrations.RunPython(relax_nulls, noop_reverse),
    ]
