"""Drop orphan columns on scribe_scribesession that exist in MySQL but have
no matching Django model field. These columns were introduced by earlier
schema iterations during the SQLite -> MySQL migration; their NOT NULL
without DEFAULT constraint causes:

    (1364, "Field 'encounter_alias' doesn't have a default value")

on every INSERT.

Strategy: try to DROP each column; if it doesn't exist (e.g. on a fresh
SQLite dev DB), swallow the error silently. The reverse migration is a
no-op — we never want to re-add dead columns.
"""

from django.db import migrations


ORPHAN_COLUMNS = [
    "encounter_alias",
    "audio_mime_type",
    "transcript_language",
    "narrative_note",
    "note_model",
    "output_mode",
    "specialty",
    "transcription_model",
    "transcription_provider",
    "used_real_ai",
    "export_count",
]


def drop_orphans(apps, schema_editor):
    connection = schema_editor.connection
    if connection.vendor != "mysql":
        return  # SQLite / Postgres: these orphans never existed
    cur = connection.cursor()
    cur.execute(
        "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'scribe_scribesession'"
    )
    existing = {row[0] for row in cur.fetchall()}
    for col in ORPHAN_COLUMNS:
        if col in existing:
            try:
                cur.execute(f"ALTER TABLE scribe_scribesession DROP COLUMN `{col}`")
            except Exception:
                # column may have a FK or index that blocks drop; soften to NULL+default instead
                try:
                    cur.execute(
                        f"ALTER TABLE scribe_scribesession MODIFY `{col}` "
                        f"VARCHAR(255) NULL DEFAULT ''"
                    )
                except Exception:
                    pass


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("scribe", "0007_scribesession_active_conditions_and_more"),
    ]

    operations = [
        migrations.RunPython(drop_orphans, noop_reverse),
    ]
