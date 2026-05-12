"""Drop orphan columns on scribe_soapnote that exist in MySQL but have no
matching Django model field. Mirrors the 0008 cleanup we did for
scribe_scribesession. Same failure shape:

    (1364, "Field 'model_used' doesn't have a default value")

Strategy: vendor-gated (MySQL only). For each orphan column we try DROP;
if that fails (FK / index), we soften to NULL + empty default so INSERTs
succeed. SQLite/Postgres dev DBs are no-ops.
"""

from django.db import migrations


ORPHAN_COLUMNS = [
    "model_used",
    # `export_count` IS on the model in some branches but isn't on the
    # current SOAPNote, so it shows as orphan in MySQL — drop it.
    "export_count",
    # `reviewed_at` is nullable already so it doesn't trip INSERTs, but
    # we drop it too to keep the schema consistent with the model
    # (model uses `review_completed` Boolean instead).
    "reviewed_at",
]


def drop_orphans(apps, schema_editor):
    connection = schema_editor.connection
    if connection.vendor != "mysql":
        return
    cur = connection.cursor()
    cur.execute(
        "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'scribe_soapnote'"
    )
    existing = {row[0] for row in cur.fetchall()}
    for col in ORPHAN_COLUMNS:
        if col in existing:
            try:
                cur.execute(f"ALTER TABLE scribe_soapnote DROP COLUMN `{col}`")
            except Exception:
                try:
                    cur.execute(
                        f"ALTER TABLE scribe_soapnote MODIFY `{col}` "
                        f"VARCHAR(255) NULL DEFAULT ''"
                    )
                except Exception:
                    pass


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("scribe", "0008_drop_orphan_session_columns"),
    ]

    operations = [
        migrations.RunPython(drop_orphans, noop_reverse),
    ]
