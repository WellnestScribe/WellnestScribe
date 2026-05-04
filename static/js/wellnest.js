/* WellNest Scribe — front-end glue. */
(function () {
  "use strict";

  const W = window.WELLNEST || {};
  const csrf = W.csrfToken || "";

  function $(sel, root) { return (root || document).querySelector(sel); }
  function $$(sel, root) { return Array.from((root || document).querySelectorAll(sel)); }
  function fmtTime(s) {
    const m = Math.floor(s / 60), r = Math.floor(s % 60);
    return m + ":" + (r < 10 ? "0" + r : r);
  }
  function postJSON(url, payload) {
    return fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
      body: JSON.stringify(payload || {}),
    }).then((r) => r.json().then((j) => ({ ok: r.ok, body: j })));
  }
  function postForm(url, formData) {
    return fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrf },
      body: formData,
    }).then((r) => r.json().then((j) => ({ ok: r.ok, body: j })));
  }
  function setStatus(target, text, kind) {
    if (!target) return;
    target.textContent = text;
    target.classList.remove("is-error", "is-success");
    if (kind === "error") target.classList.add("is-error");
    if (kind === "success") target.classList.add("is-success");
  }

  // ---------- toast ----------
  let toastEl = null;
  let toastTimer = 0;
  function showToast(text) {
    if (!toastEl) {
      toastEl = document.createElement("div");
      toastEl.className = "wellnest-toast";
      document.body.appendChild(toastEl);
    }
    toastEl.textContent = text;
    toastEl.classList.add("is-visible");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toastEl.classList.remove("is-visible"); }, 1800);
  }
  window.WELLNEST_toast = showToast;

  // ---------- theme ----------
  const themeBtn = $("#light-dark-mode");
  if (themeBtn) {
    themeBtn.addEventListener("click", function () {
      const html = document.documentElement;
      const next = html.getAttribute("data-bs-theme") === "dark" ? "light" : "dark";
      html.setAttribute("data-bs-theme", next);
      postJSON(W.endpoints.updatePreferences, { theme: next });
    });
  }

  // ---------- font scale ----------
  const scaleInput = $("#prefFontScale");
  const scaleValue = $("#prefFontScaleValue");
  if (scaleInput) {
    let pendingTimer = null;
    scaleInput.addEventListener("input", function () {
      const v = scaleInput.value;
      document.documentElement.setAttribute("data-font-scale", v);
      if (scaleValue) scaleValue.textContent = v + "%";
      clearTimeout(pendingTimer);
      pendingTimer = setTimeout(function () {
        postJSON(W.endpoints.updatePreferences, { font_scale: parseInt(v, 10) });
      }, 350);
    });
  }

  const noteStyleSel = $("#prefNoteStyle");
  if (noteStyleSel) {
    noteStyleSel.addEventListener("change", function () {
      postJSON(W.endpoints.updatePreferences, { default_note_style: noteStyleSel.value });
      const recordSel = $("#noteFormatSelect");
      if (recordSel) recordSel.value = noteStyleSel.value;
    });
  }
  const longFormChk = $("#prefLongForm");
  if (longFormChk) {
    longFormChk.addEventListener("change", function () {
      postJSON(W.endpoints.updatePreferences, { long_form_default: longFormChk.checked });
      const recordToggle = $("#lengthModeSwitch");
      if (recordToggle) recordToggle.checked = longFormChk.checked;
    });
  }

  // ---------- session search ----------
  $$("[data-session-filter]").forEach(function (input) {
    const targetSel = input.getAttribute("data-session-filter");
    const list = document.querySelector(targetSel);
    if (!list) return;
    function applyFilter() {
      const q = input.value.trim().toLowerCase();
      Array.from(list.querySelectorAll("[data-session-search]")).forEach(function (row) {
        const hay = row.getAttribute("data-session-search") || "";
        row.classList.toggle("is-hidden", q && hay.indexOf(q) === -1);
      });
    }
    input.addEventListener("input", applyFilter);
  });

  // ---------- idle timeout ----------
  if (W.idleTimeoutMs && W.idleTimeoutMs > 0) initIdleTimeout(W.idleTimeoutMs);

  function initIdleTimeout(timeoutMs) {
    const warningMs = Math.max(30000, timeoutMs - 60000);
    let timerWarn = 0;
    let timerLogout = 0;
    let modal = null;

    function reset() {
      clearTimeout(timerWarn);
      clearTimeout(timerLogout);
      timerWarn = setTimeout(showWarning, warningMs);
      timerLogout = setTimeout(forceSignout, timeoutMs);
    }
    function showWarning() {
      const el = document.getElementById("idleModal");
      if (!el || typeof bootstrap === "undefined") return;
      modal = bootstrap.Modal.getOrCreateInstance(el);
      modal.show();
    }
    function forceSignout() {
      const form = document.createElement("form");
      form.method = "POST";
      form.action = W.endpoints.signout;
      const t = document.createElement("input");
      t.name = "csrfmiddlewaretoken"; t.value = csrf;
      form.appendChild(t);
      document.body.appendChild(form);
      form.submit();
    }
    ["mousemove", "keydown", "click", "touchstart", "scroll"].forEach(function (e) {
      document.addEventListener(e, reset, { passive: true });
    });
    reset();
  }

  // ---------- record screen ----------
  const recordRoot = document.querySelector("[data-screen='record']");
  if (recordRoot) initRecordScreen(recordRoot);

  function initRecordScreen(root) {
    const recordBtn = $("#recordBtn", root);
    const timerEl = $("#recordTimer", root);
    const waveBars = $("#recordWaveform", root);
    const statusEl = $("#recordStatus", root);
    const noteFormatSel = $("#noteFormatSelect", root);
    const lengthSwitch = $("#lengthModeSwitch", root);
    const transcriptArea = $("#manualTranscript", root);
    const generateBtn = $("#generateBtn", root);
    const fileInput = $("#audioFileInput", root);
    const uploadBtn = $("#audioUploadBtn", root);

    let mediaRecorder = null;
    let recordedChunks = [];
    let stream = null;
    let startedAt = 0;
    let timerHandle = 0;
    let analyser = null;
    let audioCtx = null;
    let waveAnimHandle = 0;
    let recordedBlob = null;
    let recordedDuration = 0;

    const BARS = 36;
    if (waveBars) {
      waveBars.innerHTML = "";
      for (let i = 0; i < BARS; i++) waveBars.appendChild(document.createElement("span"));
    }
    function buildWavePump() {
      if (!analyser || !waveBars) return;
      const data = new Uint8Array(analyser.frequencyBinCount);
      const spans = waveBars.querySelectorAll("span");
      function tick() {
        analyser.getByteFrequencyData(data);
        spans.forEach(function (sp, idx) {
          const v = data[idx * 3] || 0;
          sp.style.height = Math.max(8, (v / 255) * 46) + "px";
        });
        waveAnimHandle = requestAnimationFrame(tick);
      }
      tick();
    }
    function stopWavePump() {
      cancelAnimationFrame(waveAnimHandle);
      if (waveBars) waveBars.querySelectorAll("span").forEach(function (sp) { sp.style.height = "8px"; });
    }
    function startTimer() {
      startedAt = Date.now();
      timerHandle = setInterval(function () {
        if (timerEl) timerEl.textContent = fmtTime((Date.now() - startedAt) / 1000);
      }, 250);
    }
    function stopTimer() {
      clearInterval(timerHandle);
      recordedDuration = Math.round((Date.now() - startedAt) / 1000);
    }
    async function startRecording() {
      try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); }
      catch (err) { setStatus(statusEl, "Microphone permission denied.", "error"); return; }
      recordedChunks = [];
      const mime = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
        ? "audio/webm;codecs=opus" : "";
      mediaRecorder = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream);
      mediaRecorder.ondataavailable = function (e) { if (e.data && e.data.size > 0) recordedChunks.push(e.data); };
      mediaRecorder.onstop = onRecordingStopped;
      mediaRecorder.start(250);

      audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      const source = audioCtx.createMediaStreamSource(stream);
      analyser = audioCtx.createAnalyser();
      analyser.fftSize = 256;
      source.connect(analyser);
      buildWavePump();

      recordBtn.classList.add("is-recording");
      recordBtn.querySelector("[data-record-label]").textContent = "Stop";
      setStatus(statusEl, "Recording — speak clearly.");
      startTimer();
    }
    function stopRecording() {
      if (mediaRecorder && mediaRecorder.state !== "inactive") mediaRecorder.stop();
      stopTimer();
      stopWavePump();
      if (stream) stream.getTracks().forEach(function (t) { t.stop(); });
      if (audioCtx && audioCtx.state !== "closed") audioCtx.close();
      recordBtn.classList.remove("is-recording");
      recordBtn.querySelector("[data-record-label]").textContent = "Record";
    }
    async function onRecordingStopped() {
      const blob = new Blob(recordedChunks, { type: recordedChunks[0]?.type || "audio/webm" });
      recordedBlob = blob;
      setStatus(statusEl, "Captured " + fmtTime(recordedDuration) + " of audio. Uploading…");
      await uploadAndProcess(blob);
    }
    async function uploadAndProcess(blob) {
      const fd = new FormData();
      const ext = blob.type.indexOf("ogg") >= 0 ? "ogg" : "webm";
      fd.append("audio", blob, "wellnest-recording." + ext);
      fd.append("note_format", noteFormatSel ? noteFormatSel.value : "soap");
      fd.append("length_mode", lengthSwitch && lengthSwitch.checked ? "long_form" : "normal");
      fd.append("duration_seconds", String(recordedDuration));
      const res = await postForm(W.endpoints.createSession, fd);
      if (!res.ok || !res.body.ok) { setStatus(statusEl, (res.body && res.body.error) || "Upload failed.", "error"); return; }
      const sid = res.body.session_id;
      setStatus(statusEl, "Transcribing audio…");
      const tr = await postJSON("/scribe/api/sessions/" + sid + "/transcribe/", {});
      if (!tr.ok || !tr.body.ok) { setStatus(statusEl, (tr.body && tr.body.error) || "Transcription failed.", "error"); return; }
      if (transcriptArea) transcriptArea.value = tr.body.transcript || "";
      setStatus(statusEl, "Generating note…");
      await runGeneration(sid, tr.body.transcript || "");
    }
    async function runGeneration(sid, transcript) {
      const payload = {
        transcript: transcript,
        note_format: noteFormatSel ? noteFormatSel.value : "soap",
        length_mode: lengthSwitch && lengthSwitch.checked ? "long_form" : "normal",
      };
      const gen = await postJSON("/scribe/api/sessions/" + sid + "/generate/", payload);
      if (!gen.ok || !gen.body.ok) { setStatus(statusEl, (gen.body && gen.body.error) || "Note generation failed.", "error"); return; }
      setStatus(statusEl, "Done — opening review.", "success");
      window.location.href = gen.body.review_url;
    }

    if (recordBtn) recordBtn.addEventListener("click", function () {
      if (recordBtn.classList.contains("is-recording")) stopRecording(); else startRecording();
    });
    if (uploadBtn && fileInput) {
      uploadBtn.addEventListener("click", function () { fileInput.click(); });
      fileInput.addEventListener("change", async function () {
        const f = fileInput.files && fileInput.files[0];
        if (!f) return;
        recordedDuration = 0;
        setStatus(statusEl, "Uploading file…");
        await uploadAndProcess(f);
      });
    }
    if (generateBtn) generateBtn.addEventListener("click", async function () {
      const transcript = transcriptArea ? transcriptArea.value.trim() : "";
      if (transcript.length < 20) { setStatus(statusEl, "Type at least a couple sentences first.", "error"); return; }
      const fd = new FormData();
      fd.append("transcript", transcript);
      fd.append("note_format", noteFormatSel ? noteFormatSel.value : "soap");
      fd.append("length_mode", lengthSwitch && lengthSwitch.checked ? "long_form" : "normal");
      const res = await postForm(W.endpoints.createSession, fd);
      if (!res.ok || !res.body.ok) { setStatus(statusEl, (res.body && res.body.error) || "Could not create session.", "error"); return; }
      setStatus(statusEl, "Generating note…");
      await runGeneration(res.body.session_id, transcript);
    });
  }

  // ---------- review screen ----------
  const reviewRoot = document.querySelector("[data-screen='review']");
  if (reviewRoot) initReviewScreen(reviewRoot);

  function initReviewScreen(root) {
    const sessionId = root.getAttribute("data-session-id");
    const saveBtn = $("#saveBtn", root);
    const finalizeBtn = $("#finalizeBtn", root);
    const copyBtn = $("#copyBtn", root);
    const whatsappBtn = $("#whatsappBtn", root);
    const printBtn = $("#printBtn", root);
    const regenAllBtn = $("#regenerateAllBtn", root);
    const titleEl = $("#sessionTitle", root);
    const wordCounter = $("#wordCounter", root);
    const fields = $$("[data-note-field]", root);
    const fullNoteArea = $("[data-full-note]", root);
    const transcriptArea = $("#transcriptArea", root);
    const statusEl = $("#reviewStatus", root);

    function renderFromFields(p) {
      if (p.narrative) return p.narrative;
      const parts = [];
      if (p.subjective) parts.push("S:\n" + p.subjective);
      if (p.objective) parts.push("O:\n" + p.objective);
      if (p.assessment) parts.push("A:\n" + p.assessment);
      if (p.plan) parts.push("P:\n" + p.plan);
      return parts.join("\n\n");
    }
    function collectFieldValues() {
      const payload = {};
      fields.forEach(function (el) { payload[el.getAttribute("data-note-field")] = el.value; });
      return payload;
    }
    function collectPayload() {
      const p = collectFieldValues();
      p.title = titleEl ? titleEl.textContent.trim() : undefined;
      p.edited_note = fullNoteArea && fullNoteArea.value
        ? fullNoteArea.value
        : renderFromFields(p);
      return p;
    }

    // --- Tab sync: structured fields → narrative textarea (only if narrative
    //     hasn't been hand-edited beyond the auto-rendered form). And vice
    //     versa: edits to the full note try to parse back into S/O/A/P fields.
    function syncFromFieldsToNarrative() {
      if (!fullNoteArea) return;
      const generated = renderFromFields(collectFieldValues());
      // If the user manually changed the narrative beyond what we'd render,
      // don't overwrite it. Track a "manually edited" flag.
      if (!fullNoteArea.dataset.manualEdit) fullNoteArea.value = generated;
    }
    function parseSoapFromText(text) {
      const sections = { subjective: "", objective: "", assessment: "", plan: "" };
      const map = { "S:": "subjective", "O:": "objective", "A:": "assessment", "P:": "plan" };
      const re = /^(S:|O:|A:|P:)\s*$/m;
      let chunks = text.split(/\n(?=(?:S:|O:|A:|P:)\s*\n)/);
      // Simpler: match label + content pairs
      const matches = [...text.matchAll(/(?:^|\n)(S:|O:|A:|P:)\s*\n([\s\S]*?)(?=\n(?:S:|O:|A:|P:)\s*\n|$)/g)];
      if (matches.length === 0) return null;
      matches.forEach(function (m) {
        const key = map[m[1]];
        if (key) sections[key] = m[2].trim();
      });
      return sections;
    }
    function syncFromNarrativeToFields() {
      if (!fullNoteArea) return;
      const parsed = parseSoapFromText(fullNoteArea.value);
      if (!parsed) return;
      fields.forEach(function (el) {
        const k = el.getAttribute("data-note-field");
        if (k in parsed && parsed[k]) el.value = parsed[k];
      });
    }
    function updateWordCount() {
      if (!wordCounter) return;
      const text = fullNoteArea && fullNoteArea.value
        ? fullNoteArea.value
        : renderFromFields(collectFieldValues());
      const words = (text.trim().match(/\S+/g) || []).length;
      wordCounter.textContent = words + " words · " + text.length + " chars";
    }

    let dirtyTimer = 0;
    function markDirty() {
      clearTimeout(dirtyTimer);
      dirtyTimer = setTimeout(autosave, 1100);
      setStatus(statusEl, "Editing…");
      updateWordCount();
    }
    async function autosave() {
      const r = await postJSON("/scribe/api/sessions/" + sessionId + "/save/", collectPayload());
      if (r.ok && r.body.ok) setStatus(statusEl, "Saved", "success");
      else setStatus(statusEl, "Save failed", "error");
    }

    fields.forEach(function (el) {
      el.addEventListener("input", function () {
        syncFromFieldsToNarrative();
        markDirty();
      });
    });
    if (fullNoteArea) {
      fullNoteArea.addEventListener("input", function () {
        fullNoteArea.dataset.manualEdit = "1";
        markDirty();
      });
      fullNoteArea.addEventListener("blur", function () {
        // Try to back-propagate edits into structured fields.
        syncFromNarrativeToFields();
      });
    }
    if (transcriptArea) {
      transcriptArea.addEventListener("input", function () {
        clearTimeout(dirtyTimer);
        dirtyTimer = setTimeout(function () {
          // Save transcript via the save endpoint as part of the payload (fields-only).
          // We don't include transcript in the regular save, so add a manual call:
          postJSON("/scribe/api/sessions/" + sessionId + "/save/", { transcript: transcriptArea.value });
        }, 800);
      });
    }

    // Editable title
    if (titleEl) {
      let titleTimer = 0;
      function saveTitle() {
        const t = titleEl.textContent.trim();
        if (t.length > 160) titleEl.textContent = t.slice(0, 160);
        postJSON("/scribe/api/sessions/" + sessionId + "/save/", { title: titleEl.textContent.trim() });
        setStatus(statusEl, "Saved", "success");
      }
      titleEl.addEventListener("input", function () {
        clearTimeout(titleTimer);
        titleTimer = setTimeout(saveTitle, 800);
      });
      titleEl.addEventListener("blur", saveTitle);
      titleEl.addEventListener("keydown", function (e) {
        if (e.key === "Enter") { e.preventDefault(); titleEl.blur(); }
      });
    }

    if (saveBtn) saveBtn.addEventListener("click", function () { autosave(); });
    if (finalizeBtn) finalizeBtn.addEventListener("click", async function () {
      await autosave();
      const r = await postJSON("/scribe/api/sessions/" + sessionId + "/finalize/", {});
      if (r.ok && r.body.ok) { setStatus(statusEl, "Finalized.", "success"); showToast("Note marked reviewed"); }
      else setStatus(statusEl, "Could not finalize.", "error");
    });
    if (copyBtn) copyBtn.addEventListener("click", async function () {
      await autosave();
      const text = fullNoteArea && fullNoteArea.value ? fullNoteArea.value : renderFromFields(collectFieldValues());
      try { await navigator.clipboard.writeText(text); showToast("Copied to clipboard"); }
      catch (err) { setStatus(statusEl, "Copy failed", "error"); }
    });
    if (printBtn) printBtn.addEventListener("click", function () { window.print(); });
    if (regenAllBtn) regenAllBtn.addEventListener("click", async function () {
      if (!confirm("Regenerate the note from the current transcript? Your edits to the structured note will be replaced.")) return;
      setStatus(statusEl, "Regenerating note…");
      const r = await postJSON("/scribe/api/sessions/" + sessionId + "/generate/",
                                { transcript: transcriptArea ? transcriptArea.value : "" });
      if (r.ok && r.body.ok) window.location.reload();
      else setStatus(statusEl, (r.body && r.body.error) || "Regeneration failed.", "error");
    });
    if (whatsappBtn) whatsappBtn.addEventListener("click", async function () {
      await autosave();
      const r = await postJSON("/scribe/api/sessions/" + sessionId + "/share/", {});
      if (!r.ok || !r.body.ok) { setStatus(statusEl, (r.body && r.body.error) || "Could not build link.", "error"); return; }
      window.open(r.body.whatsapp_url, "_blank");
      showToast("Opened WhatsApp share");
    });

    // QR — pre-fetch as soon as the modal starts to open, not after
    const shareModalEl = document.getElementById("shareModal");
    const qrLoader = $("#qrLoader");
    const qrCanvas = $("#qrCanvas");
    const qrLink = $("#qrLink");
    const qrLinkRow = $("#qrLinkRow");
    const qrCopyLink = $("#qrCopyLink");
    if (shareModalEl) {
      shareModalEl.addEventListener("show.bs.modal", async function () {
        if (qrLoader) qrLoader.classList.remove("d-none");
        if (qrCanvas) { qrCanvas.classList.add("d-none"); qrCanvas.innerHTML = ""; }
        if (qrLinkRow) qrLinkRow.classList.add("d-none");
        const r = await postJSON("/scribe/api/sessions/" + sessionId + "/share/", {});
        if (!r.ok || !r.body.ok) {
          if (qrLoader) qrLoader.innerHTML = "<p class='text-danger small mb-0'>" + ((r.body && r.body.error) || "Could not build share link.") + "</p>";
          return;
        }
        if (qrLoader) qrLoader.classList.add("d-none");
        if (qrCanvas) {
          const img = document.createElement("img");
          img.src = r.body.qr_data_url;
          img.alt = "QR code for share link";
          qrCanvas.appendChild(img);
          qrCanvas.classList.remove("d-none");
        }
        if (qrLink) qrLink.value = r.body.share_url;
        if (qrLinkRow) qrLinkRow.classList.remove("d-none");
      });
    }
    if (qrCopyLink) qrCopyLink.addEventListener("click", async function () {
      try { await navigator.clipboard.writeText(qrLink.value); showToast("Link copied"); }
      catch (e) { qrLink.select(); document.execCommand("copy"); }
    });

    // Keyboard shortcuts
    document.addEventListener("keydown", function (e) {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
        e.preventDefault(); autosave();
      } else if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === "c") {
        e.preventDefault(); if (copyBtn) copyBtn.click();
      }
    });

    initQuickEditMics(root);
    updateWordCount();
  }

  // ---------- quick-edit mic (with server fallback) ----------
  function initQuickEditMics(root) {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    $$("[data-quick-mic]", root).forEach(function (btn) {
      const targetSel = btn.getAttribute("data-quick-mic");
      const target = root.querySelector(targetSel);
      if (!target) return;

      let listening = false;
      let recog = null;
      let mediaRecorder = null;
      let chunks = [];
      let stream = null;
      let helper = null;

      function ensureHelper() {
        if (helper) return helper;
        helper = document.createElement("span");
        helper.className = "quick-mic-helper";
        helper.innerHTML = '<span class="dot"></span><span class="quick-mic-helper-text">Listening…</span>';
        btn.parentNode.appendChild(helper);
        return helper;
      }
      function showHelper(text) {
        const h = ensureHelper();
        h.style.display = "inline-flex";
        h.querySelector(".quick-mic-helper-text").textContent = text;
      }
      function hideHelper() { if (helper) helper.style.display = "none"; }

      function setListening(on, label) {
        listening = on;
        btn.classList.toggle("is-listening", on);
        btn.dataset.listening = on ? "true" : "false";
        if (on) showHelper(label || "Listening…"); else hideHelper();
      }

      function startBrowserRecog() {
        recog = new SR();
        recog.lang = "en-US";
        recog.interimResults = true;
        recog.continuous = true;
        let baseText = target.value;
        if (baseText && !baseText.endsWith(" ") && !baseText.endsWith("\n")) baseText += " ";
        recog.onresult = function (e) {
          let interim = "";
          let finalChunk = "";
          for (let i = e.resultIndex; i < e.results.length; i++) {
            const tr = e.results[i][0].transcript;
            if (e.results[i].isFinal) finalChunk += tr; else interim += tr;
          }
          if (finalChunk) {
            baseText += finalChunk + " ";
            target.value = baseText + interim;
            target.dispatchEvent(new Event("input", { bubbles: true }));
          } else {
            target.value = baseText + interim;
          }
        };
        recog.onerror = function (ev) {
          setListening(false);
          if (ev.error === "not-allowed" || ev.error === "service-not-allowed") {
            showToast("Microphone permission denied");
          }
        };
        recog.onend = function () { setListening(false); };
        try { recog.start(); setListening(true, "Listening… (browser)"); }
        catch (err) { setListening(false); fallbackToServer(); }
      }

      async function fallbackToServer() {
        try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); }
        catch (err) { showToast("Microphone permission denied"); return; }
        chunks = [];
        const mime = MediaRecorder.isTypeSupported("audio/webm;codecs=opus") ? "audio/webm;codecs=opus" : "";
        mediaRecorder = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream);
        mediaRecorder.ondataavailable = function (e) { if (e.data && e.data.size > 0) chunks.push(e.data); };
        mediaRecorder.onstop = async function () {
          showHelper("Transcribing…");
          if (stream) stream.getTracks().forEach(function (t) { t.stop(); });
          const blob = new Blob(chunks, { type: chunks[0]?.type || "audio/webm" });
          const fd = new FormData();
          fd.append("audio", blob, "quick-edit.webm");
          const res = await postForm(W.endpoints.quickTranscribe, fd);
          setListening(false);
          if (res.ok && res.body.ok && res.body.text) {
            const sep = target.value && !target.value.endsWith(" ") && !target.value.endsWith("\n") ? " " : "";
            target.value = target.value + sep + res.body.text;
            target.dispatchEvent(new Event("input", { bubbles: true }));
            showToast("Inserted dictation");
          } else if (res.body && res.body.error) {
            showToast(res.body.error);
          }
        };
        mediaRecorder.start();
        setListening(true, "Listening… (server)");
      }

      btn.addEventListener("click", function () {
        if (listening) {
          if (recog) { try { recog.stop(); } catch (e) { /* noop */ } recog = null; }
          if (mediaRecorder && mediaRecorder.state !== "inactive") mediaRecorder.stop();
          setListening(false);
          return;
        }
        if (SR) startBrowserRecog(); else fallbackToServer();
      });

      // Esc stops listening anywhere.
      document.addEventListener("keydown", function (e) {
        if (e.key === "Escape" && listening) btn.click();
      });
    });
  }
})();
