"""Migrate PHI fields to application-level encrypted field types.

ScribeSession: title, chief_complaint, patient_name, patient_identifier,
               transcript, raw_transcript  → EncryptedCharField / EncryptedTextField

SOAPNote: visit_summary, subjective, objective, assessment, plan,
          narrative, full_note, edited_note  → EncryptedTextField

Schema changes:
  • CharField columns become TEXT (EncryptedCharField stores as TEXT to hold
    the ciphertext overhead; ~100 extra bytes per row).
  • TextField columns remain TEXT — field-class change only, no SQL ALTER needed.

Existing plaintext data stays readable after this migration because the field's
from_db_value() falls back gracefully when decryption fails (InvalidToken).
Run  manage.py encrypt_existing_phi  after configuring FIELD_ENCRYPTION_KEY to
encrypt all existing rows in-place.
"""

from django.db import migrations
import scribe.fields


class Migration(migrations.Migration):

    dependencies = [
        ("scribe", "0021_modalomniendpoint"),
    ]

    operations = [
        # ── ScribeSession ──────────────────────────────────────────────────
        migrations.AlterField(
            model_name="scribesession",
            name="title",
            field=scribe.fields.EncryptedCharField(blank=True, max_length=160),
        ),
        migrations.AlterField(
            model_name="scribesession",
            name="chief_complaint",
            field=scribe.fields.EncryptedCharField(blank=True, max_length=200),
        ),
        migrations.AlterField(
            model_name="scribesession",
            name="patient_name",
            field=scribe.fields.EncryptedCharField(blank=True, max_length=120),
        ),
        migrations.AlterField(
            model_name="scribesession",
            name="patient_identifier",
            field=scribe.fields.EncryptedCharField(blank=True, max_length=120),
        ),
        migrations.AlterField(
            model_name="scribesession",
            name="transcript",
            field=scribe.fields.EncryptedTextField(blank=True),
        ),
        migrations.AlterField(
            model_name="scribesession",
            name="raw_transcript",
            field=scribe.fields.EncryptedTextField(blank=True),
        ),
        # ── SOAPNote ───────────────────────────────────────────────────────
        migrations.AlterField(
            model_name="soapnote",
            name="visit_summary",
            field=scribe.fields.EncryptedTextField(blank=True),
        ),
        migrations.AlterField(
            model_name="soapnote",
            name="subjective",
            field=scribe.fields.EncryptedTextField(blank=True),
        ),
        migrations.AlterField(
            model_name="soapnote",
            name="objective",
            field=scribe.fields.EncryptedTextField(blank=True),
        ),
        migrations.AlterField(
            model_name="soapnote",
            name="assessment",
            field=scribe.fields.EncryptedTextField(blank=True),
        ),
        migrations.AlterField(
            model_name="soapnote",
            name="plan",
            field=scribe.fields.EncryptedTextField(blank=True),
        ),
        migrations.AlterField(
            model_name="soapnote",
            name="narrative",
            field=scribe.fields.EncryptedTextField(blank=True),
        ),
        migrations.AlterField(
            model_name="soapnote",
            name="full_note",
            field=scribe.fields.EncryptedTextField(blank=True),
        ),
        migrations.AlterField(
            model_name="soapnote",
            name="edited_note",
            field=scribe.fields.EncryptedTextField(blank=True),
        ),
    ]
