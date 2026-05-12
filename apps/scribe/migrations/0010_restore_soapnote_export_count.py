"""Restore SOAPNote.export_count.

The 0009 migration incorrectly dropped this column. It IS a current field on
the `SOAPNote` model (`export_count = models.PositiveIntegerField(default=0)`),
so Django's queries reference it and fail with:

    OperationalError: (1054, "Unknown column 'scribe_soapnote.export_count' in 'field list'")

This migration adds it back idempotently on any vendor.
"""

from django.db import migrations, models


def add_column_if_missing(apps, schema_editor):
    connection = schema_editor.connection
    cur = connection.cursor()
    if connection.vendor == "mysql":
        cur.execute(
            "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'scribe_soapnote'"
        )
        cols = {row[0] for row in cur.fetchall()}
        if "export_count" not in cols:
            cur.execute(
                "ALTER TABLE scribe_soapnote ADD COLUMN export_count "
                "INT UNSIGNED NOT NULL DEFAULT 0"
            )
    elif connection.vendor == "sqlite":
        cur.execute("PRAGMA table_info(scribe_soapnote)")
        cols = {row[1] for row in cur.fetchall()}
        if "export_count" not in cols:
            cur.execute(
                "ALTER TABLE scribe_soapnote ADD COLUMN export_count "
                "INTEGER NOT NULL DEFAULT 0"
            )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("scribe", "0009_drop_orphan_soapnote_columns"),
    ]

    operations = [
        migrations.RunPython(add_column_if_missing, noop_reverse),
    ]
