"""Views for the WellNest Scribe MVP.

Page views render templates; API views are JSON-in/JSON-out and are used by the
browser-side recorder and editor.
"""

from __future__ import annotations

import json
import logging

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST

from django.conf import settings as dj_settings

from accounts.models import DoctorProfile

from .models import NoteShare, ScribeSession, SessionEvent, SOAPNote
from .services.export import make_share_token, qr_data_url, whatsapp_url
from .services.pipeline import (
    run_interpret_patois,
    run_note_generation,
    run_polish_grammar,
    run_suggest_improvements,
    run_transcription,
)
from .services.triage import (
    TriageDependencyError,
    probe_environment,
    transcribe_mms,
    t5_rewrite,
)


def _triage_visible(user) -> bool:
    if dj_settings.SCRIBE_ENABLE_TRIAGE:
        return user.is_authenticated
    return user.is_authenticated and (user.is_staff or user.is_superuser)


logger = logging.getLogger(__name__)
audit_log = logging.getLogger("scribe.audit")


def _get_profile(user) -> DoctorProfile:
    profile, _ = DoctorProfile.objects.get_or_create(user=user)
    return profile


def _json_body(request):
    if not request.body:
        return {}
    try:
        return json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}


def _log(session: ScribeSession, event_type: str, detail: str = "") -> None:
    SessionEvent.objects.create(
        session=session, event_type=event_type, detail=detail[:2000]
    )
    audit_log.info(
        "session=%s doctor=%s event=%s detail=%s",
        session.pk,
        session.doctor_id,
        event_type,
        detail.replace("\n", " ")[:400],
    )


# ----- Page views -----

class RecordView(LoginRequiredMixin, View):
    template_name = "scribe/record.html"

    def get(self, request):
        profile = _get_profile(request.user)
        recent = (
            ScribeSession.objects.filter(doctor=request.user)
            .order_by("-created_at")[:6]
        )
        return render(
            request,
            self.template_name,
            {
                "profile": profile,
                "recent_sessions": recent,
                "specialty_choices": DoctorProfile.SPECIALTY_CHOICES,
                "format_choices": ScribeSession.NOTE_FORMAT_CHOICES,
                "length_choices": ScribeSession.LENGTH_MODE_CHOICES,
            },
        )


class HistoryView(LoginRequiredMixin, View):
    template_name = "scribe/history.html"

    def get(self, request):
        sessions = (
            ScribeSession.objects.filter(doctor=request.user)
            .select_related("note")
            .order_by("-created_at")
        )
        return render(request, self.template_name, {"sessions": sessions})


class ReviewView(LoginRequiredMixin, View):
    template_name = "scribe/review.html"

    def get(self, request, pk):
        session = get_object_or_404(
            ScribeSession.objects.select_related("note"),
            pk=pk,
            doctor=request.user,
        )
        return render(
            request,
            self.template_name,
            {
                "session": session,
                "note": getattr(session, "note", None),
                "profile": _get_profile(request.user),
            },
        )


class SessionDetailView(LoginRequiredMixin, View):
    def get(self, request, pk):
        return redirect("scribe:review", pk=pk)


class TriageView(LoginRequiredMixin, View):
    """Admin/staff sandbox for testing Patois ASR (MMS) + T5 rewrites locally."""

    template_name = "scribe/triage.html"

    def get(self, request):
        if not _triage_visible(request.user):
            return redirect("scribe:record")
        return render(
            request,
            self.template_name,
            {
                "env": probe_environment(),
                "default_system_prompt": (
                    "You are a Jamaican Patois-to-clinical-English interpreter. "
                    "Read the raw Patwa transcript phonetically, rewrite it as "
                    "neutral clinical English in third person, capture every "
                    "symptom and herbal remedy, tag herbs as [HERBAL SUPPLEMENT], "
                    "and flag unintelligible parts with [unclear: \"...\"]."
                ),
            },
        )


@login_required
@require_POST
@csrf_protect
def triage_run_api(request):
    """Run a chosen Triage backend on uploaded audio or text and return raw output."""
    if not _triage_visible(request.user):
        return JsonResponse({"ok": False, "error": "Not authorized."}, status=403)

    backend = request.POST.get("backend", "mms")
    device = request.POST.get("device", dj_settings.TRIAGE_DEFAULT_DEVICE)
    target_lang = request.POST.get("target_lang", "jam")

    audio = request.FILES.get("audio")
    text_input = request.POST.get("text_input", "").strip()

    saved_path = None
    if audio:
        from datetime import datetime
        stem = datetime.now().strftime("%Y%m%d-%H%M%S")
        ext = (audio.name.rsplit(".", 1)[-1] if "." in audio.name else "webm")[:5]
        saved_path = dj_settings.TRIAGE_AUDIO_DIR / f"{stem}-{request.user.pk}.{ext}"
        with open(saved_path, "wb") as fh:
            for chunk in audio.chunks():
                fh.write(chunk)

    import time
    started = time.perf_counter()
    try:
        if backend == "mms":
            if not saved_path:
                return JsonResponse({"ok": False, "error": "MMS requires audio."}, status=400)
            raw = transcribe_mms(saved_path, device=device, target_lang=target_lang)
        elif backend == "t5_paraphrase":
            instruction = request.POST.get(
                "instruction",
                "Rewrite the following Jamaican Patois into clear clinical English.",
            )
            raw = t5_rewrite(text_input, instruction=instruction, device=device)
        elif backend == "cloud_interpret":
            raw = run_interpret_patois(text_input or "")
        else:
            return JsonResponse({"ok": False, "error": f"Unknown backend '{backend}'."}, status=400)
    except TriageDependencyError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=503)
    except Exception as exc:  # noqa: BLE001
        logger.exception("triage backend failed")
        return JsonResponse({"ok": False, "error": str(exc)}, status=500)
    duration_ms = int((time.perf_counter() - started) * 1000)

    return JsonResponse(
        {
            "ok": True,
            "backend": backend,
            "device": device,
            "raw_text": raw,
            "duration_ms": duration_ms,
            "audio_saved_as": saved_path.name if saved_path else None,
        }
    )


@login_required
@require_POST
@csrf_protect
def triage_interpret_api(request):
    """Run cloud LLM interpretation over Patois text using a custom system prompt."""
    if not _triage_visible(request.user):
        return JsonResponse({"ok": False, "error": "Not authorized."}, status=403)
    payload = _json_body(request)
    raw_text = (payload.get("text") or "").strip()
    if not raw_text:
        return JsonResponse({"ok": False, "error": "No text provided."}, status=400)
    try:
        clean = run_interpret_patois(raw_text)
    except Exception as exc:  # noqa: BLE001
        logger.exception("triage interpret failed")
        return JsonResponse({"ok": False, "error": str(exc)}, status=500)
    return JsonResponse({"ok": True, "clean_text": clean})


# ----- API views -----

@login_required
@require_POST
@csrf_protect
def create_session_api(request):
    profile = _get_profile(request.user)
    audio = request.FILES.get("audio")
    note_format = request.POST.get("note_format", profile.default_note_style)
    length_mode = request.POST.get(
        "length_mode", "long_form" if profile.long_form_default else "normal"
    )
    title = request.POST.get("title", "").strip()
    chief_complaint = request.POST.get("chief_complaint", "").strip()
    transcript = request.POST.get("transcript", "").strip()
    duration_raw = request.POST.get("duration_seconds", "").strip()

    valid_formats = dict(ScribeSession.NOTE_FORMAT_CHOICES)
    valid_lengths = dict(ScribeSession.LENGTH_MODE_CHOICES)

    session = ScribeSession.objects.create(
        doctor=request.user,
        title=title,
        chief_complaint=chief_complaint,
        note_format=note_format if note_format in valid_formats else "soap",
        length_mode=length_mode if length_mode in valid_lengths else "normal",
        session_type="text" if not audio else "dictation",
        transcript=transcript,
        status="draft",
    )
    if audio:
        session.audio_file = audio
    if duration_raw.isdigit():
        session.duration_seconds = int(duration_raw)
    session.save()
    _log(
        session,
        "created",
        f"format={session.note_format} length={session.length_mode}",
    )
    if audio:
        _log(session, "uploaded", f"size={audio.size} name={audio.name}")
    return JsonResponse(
        {
            "ok": True,
            "session_id": session.pk,
            "has_audio": bool(audio),
            "transcript": session.transcript,
        }
    )


@login_required
@require_POST
@csrf_protect
def transcribe_session_api(request, pk):
    session = get_object_or_404(ScribeSession, pk=pk, doctor=request.user)
    if not session.audio_file:
        return JsonResponse(
            {"ok": False, "error": "No audio attached to session."}, status=400
        )

    session.status = "transcribing"
    session.save(update_fields=["status", "updated_at"])
    try:
        transcript = run_transcription(session.audio_file.path)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Transcription failed for session %s", pk)
        session.status = "error"
        session.error_message = str(exc)
        session.save(update_fields=["status", "error_message", "updated_at"])
        _log(session, "error", f"transcription: {exc}")
        return JsonResponse({"ok": False, "error": str(exc)}, status=500)

    session.transcript = transcript
    session.status = "review"
    session.save(update_fields=["transcript", "status", "updated_at"])
    _log(session, "transcribed", f"chars={len(transcript)}")
    return JsonResponse({"ok": True, "transcript": transcript})


@login_required
@require_POST
@csrf_protect
def generate_note_api(request, pk):
    session = get_object_or_404(ScribeSession, pk=pk, doctor=request.user)
    payload = _json_body(request)
    transcript = (payload.get("transcript") or session.transcript or "").strip()
    note_format = payload.get("note_format", session.note_format)
    length_mode = payload.get("length_mode", session.length_mode)

    if not transcript or len(transcript) < 20:
        return JsonResponse(
            {
                "ok": False,
                "error": "Transcript is too short. Record at least 30 seconds or paste more text.",
            },
            status=400,
        )

    profile = _get_profile(request.user)
    session.transcript = transcript
    session.note_format = note_format
    session.length_mode = length_mode
    session.status = "generating"
    session.save(update_fields=[
        "transcript", "note_format", "length_mode", "status", "updated_at"
    ])

    try:
        result = run_note_generation(
            transcript=transcript,
            note_format=note_format,
            specialty=profile.specialty,
            length_mode=length_mode,
            custom_instructions=profile.custom_instructions,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Note generation failed for session %s", pk)
        session.status = "error"
        session.error_message = str(exc)
        session.save(update_fields=["status", "error_message", "updated_at"])
        _log(session, "error", f"generate: {exc}")
        return JsonResponse({"ok": False, "error": str(exc)}, status=500)

    if not (result.full_note or "").strip():
        msg = (
            "The AI returned an empty note. This usually means the model spent "
            "its token budget on internal reasoning. Increase "
            "SCRIBE_MAX_COMPLETION_TOKENS in .env or switch to a non-reasoning deployment."
        )
        session.status = "error"
        session.error_message = msg
        session.save(update_fields=["status", "error_message", "updated_at"])
        _log(session, "error", "generate: empty output")
        return JsonResponse({"ok": False, "error": msg}, status=502)

    note, _ = SOAPNote.objects.update_or_create(
        session=session,
        defaults={
            "subjective": result.subjective,
            "objective": result.objective,
            "assessment": result.assessment,
            "plan": result.plan,
            "narrative": result.narrative,
            "full_note": result.full_note,
            "edited_note": result.full_note,
            "flags": result.flags,
        },
    )
    session.status = "review"
    session.save(update_fields=["status", "updated_at"])
    _log(session, "generated", f"format={result.note_format} flags={result.flags}")

    return JsonResponse(
        {
            "ok": True,
            "session_id": session.pk,
            "note_format": result.note_format,
            "subjective": note.subjective,
            "objective": note.objective,
            "assessment": note.assessment,
            "plan": note.plan,
            "narrative": note.narrative,
            "full_note": note.full_note,
            "edited_note": note.edited_note,
            "flags": note.flags,
            "review_url": f"/scribe/sessions/{session.pk}/review/",
        }
    )


@login_required
@require_POST
@csrf_protect
def save_note_api(request, pk):
    session = get_object_or_404(ScribeSession, pk=pk, doctor=request.user)
    note = getattr(session, "note", None) or SOAPNote.objects.create(session=session)
    payload = _json_body(request)

    for field in ("subjective", "objective", "assessment", "plan", "narrative", "edited_note"):
        if field in payload:
            setattr(note, field, payload[field] or "")

    if "title" in payload:
        session.title = payload["title"][:160]
    if "chief_complaint" in payload:
        session.chief_complaint = payload["chief_complaint"][:200]

    note.save()
    session.save()
    _log(session, "edited", "doctor saved edits")
    return JsonResponse({"ok": True})


@login_required
@require_POST
@csrf_protect
def finalize_session_api(request, pk):
    session = get_object_or_404(ScribeSession, pk=pk, doctor=request.user)
    note = getattr(session, "note", None)
    if note is None:
        return JsonResponse(
            {"ok": False, "error": "No note to finalize yet."}, status=400
        )
    note.review_completed = True
    note.save(update_fields=["review_completed", "updated_at"])
    session.status = "finalized"
    session.finalized_at = timezone.now()
    session.save(update_fields=["status", "finalized_at", "updated_at"])
    _log(session, "finalized", "")
    return JsonResponse({"ok": True})


@login_required
@require_POST
@csrf_protect
def suggest_improvements_api(request, pk):
    """Run an AI quality pass over the current note. Returns markdown bullets."""
    session = get_object_or_404(ScribeSession, pk=pk, doctor=request.user)
    note = getattr(session, "note", None)
    if note is None:
        return JsonResponse({"ok": False, "error": "Generate a note first."}, status=400)
    profile = _get_profile(request.user)
    note_text = note.edited_note or note.full_note or note.narrative or ""
    try:
        suggestions = run_suggest_improvements(note_text, specialty=profile.specialty)
    except Exception as exc:  # noqa: BLE001
        logger.exception("suggest_improvements failed for session %s", pk)
        return JsonResponse({"ok": False, "error": str(exc)}, status=500)
    _log(session, "edited", "ai-suggestions requested")
    return JsonResponse({"ok": True, "suggestions": suggestions})


@login_required
@require_POST
@csrf_protect
def polish_note_api(request, pk):
    """Run a grammar/clarity pass over the current note. Updates the note in place."""
    session = get_object_or_404(ScribeSession, pk=pk, doctor=request.user)
    note = getattr(session, "note", None)
    if note is None:
        return JsonResponse({"ok": False, "error": "Generate a note first."}, status=400)
    source = note.edited_note or note.full_note or note.narrative or ""
    if not source.strip():
        return JsonResponse({"ok": False, "error": "Note is empty."}, status=400)
    try:
        polished = run_polish_grammar(source)
    except Exception as exc:  # noqa: BLE001
        logger.exception("polish_grammar failed for session %s", pk)
        return JsonResponse({"ok": False, "error": str(exc)}, status=500)
    note.edited_note = polished
    # If we have S/O/A/P sections in polished output, update the structured fields.
    from .services.soap_generator import _split_soap  # local import
    sections = _split_soap(polished)
    if any(sections.values()):
        note.subjective = sections["subjective"]
        note.objective = sections["objective"]
        note.assessment = sections["assessment"]
        note.plan = sections["plan"]
    note.save()
    _log(session, "edited", "polish-grammar applied")
    return JsonResponse(
        {
            "ok": True,
            "edited_note": note.edited_note,
            "subjective": note.subjective,
            "objective": note.objective,
            "assessment": note.assessment,
            "plan": note.plan,
        }
    )


@login_required
@require_POST
@csrf_protect
def quick_transcribe_api(request):
    """Transcribe a short audio blob (quick-edit dictation). Returns text only."""
    audio = request.FILES.get("audio")
    if not audio:
        return JsonResponse({"ok": False, "error": "No audio sent."}, status=400)
    # Persist to a temp file the SDK can read.
    import os
    import tempfile

    suffix = ".webm" if audio.name.endswith(".webm") else os.path.splitext(audio.name)[1] or ".webm"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        for chunk in audio.chunks():
            tmp.write(chunk)
        tmp_path = tmp.name
    try:
        text = run_transcription(tmp_path)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Quick transcribe failed")
        return JsonResponse({"ok": False, "error": str(exc)}, status=500)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
    return JsonResponse({"ok": True, "text": (text or "").strip()})


@login_required
@require_POST
@csrf_protect
def share_note_api(request, pk):
    """Issue a 1-hour share link for the note + return WhatsApp + QR data URLs."""
    session = get_object_or_404(ScribeSession, pk=pk, doctor=request.user)
    note = getattr(session, "note", None)
    if note is None:
        return JsonResponse(
            {"ok": False, "error": "No note to share yet."}, status=400
        )

    token, expires_at = make_share_token()
    NoteShare.objects.create(session=session, token=token, expires_at=expires_at)

    text = note.edited_note or note.full_note or note.narrative or ""
    public_url = request.build_absolute_uri(
        f"/scribe/share/{token}/"
    )

    note.export_count = (note.export_count or 0) + 1
    note.save(update_fields=["export_count", "updated_at"])
    _log(session, "exported", "share link issued")

    return JsonResponse(
        {
            "ok": True,
            "share_url": public_url,
            "qr_data_url": qr_data_url(public_url),
            "whatsapp_url": whatsapp_url(text),
            "expires_at": expires_at.isoformat(),
            "text": text,
        }
    )


def share_view(request, token):
    """Public view of a shared note. No auth required, but expires after 1h."""
    share = get_object_or_404(NoteShare, token=token)
    if not share.is_valid():
        return render(request, "scribe/share_expired.html", status=410)
    share.opened_count += 1
    share.save(update_fields=["opened_count"])
    note = getattr(share.session, "note", None)
    return render(
        request,
        "scribe/share.html",
        {"session": share.session, "note": note},
    )


@login_required
@require_POST
@csrf_protect
def update_preferences_api(request):
    profile = _get_profile(request.user)
    payload = _json_body(request)

    if payload.get("theme") in {"light", "dark", "auto"}:
        profile.theme = payload["theme"]
    if "font_scale" in payload:
        try:
            scale = max(80, min(160, int(payload["font_scale"])))
            profile.font_scale = scale
        except (TypeError, ValueError):
            pass
    if payload.get("default_note_style") in {"soap", "narrative", "chart"}:
        profile.default_note_style = payload["default_note_style"]
    if "long_form_default" in payload:
        profile.long_form_default = bool(payload["long_form_default"])
    if payload.get("specialty") in dict(DoctorProfile.SPECIALTY_CHOICES):
        profile.specialty = payload["specialty"]

    profile.save()
    return JsonResponse(
        {
            "ok": True,
            "theme": profile.theme,
            "font_scale": profile.font_scale,
            "default_note_style": profile.default_note_style,
            "long_form_default": profile.long_form_default,
            "specialty": profile.specialty,
        }
    )
