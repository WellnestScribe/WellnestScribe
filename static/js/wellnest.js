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

  // Quick templates for the manual transcript textarea on the record screen.
  const ENCOUNTER_TEMPLATES = {
    htn: "Hypertension follow-up. [Age] [sex] returns for routine BP review. " +
         "Reports compliance with [drug + dose]. [Side effects: yes/no]. " +
         "[Headache/dizziness/blurred vision: yes/no]. " +
         "BP today [xxx/xx], HR [xx]. Plan: [continue same / increase dose / add agent]. " +
         "Recheck BP in [interval]. Lifestyle counselling on salt, exercise.",
    dm: "Diabetes follow-up. [Age] [sex] with type 2 DM on [metformin / glibenclamide / insulin]. " +
        "Reports [compliance / missed doses]. [Hypoglycaemia episodes: yes/no]. " +
        "Recent FBS [x] mmol/L; HbA1c [x%] if known. Foot exam: [findings]. " +
        "Plan: [continue / adjust dose / add agent]. Recheck in [interval]. " +
        "Counselled on diet, foot care, and warning signs.",
    urti: "Acute URTI. [Age] [sex] presents with [cough / sore throat / runny nose] " +
          "for [duration]. [Fever: yes/no]. [SOB: yes/no]. " +
          "On exam: T [x], RR [x], SpO2 [x]%. Chest [clear/findings]. " +
          "Assessment: viral URTI. Plan: paracetamol PRN, fluids, rest. " +
          "Return if SOB, persistent fever > [duration], chest pain.",
    gastro: "Acute gastroenteritis. [Age] [sex] with [vomiting / diarrhoea] " +
            "for [duration]. [Number of episodes]. [Blood/mucus: yes/no]. " +
            "Hydration status: [findings]. Plan: ORS, paracetamol PRN. " +
            "Return if persistent vomiting, blood in stool, lethargy.",
    antenatal: "Antenatal visit. [Age] G[x]P[x] at [GA] weeks. LMP [date]. " +
               "Reports [fetal movements: yes/no]. No headache, no visual changes, " +
               "no epigastric pain. BP [xxx/xx]. Fundal height [x cm]. " +
               "FHR [xxx]. Continue folic acid, iron. Next visit in [interval].",
    paeds: "Paediatric visit. [Age] [sex] brought by [parent/guardian]. " +
           "Reports [symptom] for [duration]. Feeding [normal/reduced]. " +
           "Activity [normal/reduced]. T [x], HR [x], RR [x], SpO2 [x]%. " +
           "Immunisations [up to date / due]. Plan: [treatment]. " +
           "Return if fever > [x], reduced feeding, lethargy.",
  };

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
    $$("[data-template]").forEach(function (link) {
      link.addEventListener("click", function (e) {
        e.preventDefault();
        const key = link.getAttribute("data-template");
        const tpl = ENCOUNTER_TEMPLATES[key];
        if (!tpl || !transcriptArea) return;
        transcriptArea.value = (transcriptArea.value
          ? transcriptArea.value.trim() + "\n\n"
          : "") + tpl;
        transcriptArea.focus();
        // Mark this pill as applied + clear other pills.
        $$("[data-template]").forEach(function (other) { other.classList.remove("is-applied"); });
        link.classList.add("is-applied");
        if (window.WELLNEST_toast) window.WELLNEST_toast("Template inserted — fill in the brackets");
      });
    });

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

  // ---------- triage sandbox ----------
  const triageRoot = document.querySelector("[data-screen='triage']");
  if (triageRoot) initTriageScreen(triageRoot);

  function initTriageScreen(root) {
    const recordBtn = $("#triageRecordBtn", root);
    const uploadBtn = $("#triageUploadBtn", root);
    const fileInput = $("#triageFileInput", root);
    const player = $("#triagePlayer", root);
    const audioInfo = $("#triageAudioInfo", root);
    const timer = $("#triageTimer", root);
    const waveBars = $("#triageWaveform", root);
    const backendSel = $("#triageBackend", root);
    const deviceSel = $("#triageDevice", root);
    const langInput = $("#triageLang", root);
    const textIn = $("#triageTextIn", root);
    const runBtn = $("#triageRunBtn", root);
    const rawOut = $("#triageRawOut", root);
    const timings = $("#triageTimings", root);
    const cleanOut = $("#triageCleanOut", root);
    const interpretBtn = $("#triageInterpretBtn", root);

    let currentAudioBlob = null;
    let recState = { rec: null, stream: null, ctx: null, started: 0, ts: 0 };

    const BARS = 36;
    if (waveBars) {
      waveBars.innerHTML = "";
      for (let i = 0; i < BARS; i++) waveBars.appendChild(document.createElement("span"));
    }

    function attachBlob(blob) {
      currentAudioBlob = blob;
      const url = URL.createObjectURL(blob);
      if (player) { player.src = url; player.classList.remove("d-none"); }
      if (audioInfo) audioInfo.textContent = "Loaded " + (blob.size / 1024 | 0) + " KB · " + blob.type;
    }

    if (uploadBtn && fileInput) {
      uploadBtn.addEventListener("click", function () { fileInput.click(); });
      fileInput.addEventListener("change", function () {
        const f = fileInput.files && fileInput.files[0];
        if (f) attachBlob(f);
      });
    }

    if (recordBtn) recordBtn.addEventListener("click", async function () {
      if (recordBtn.classList.contains("is-recording")) {
        if (recState.rec && recState.rec.state !== "inactive") recState.rec.stop();
        clearInterval(recState.ts);
        if (recState.stream) recState.stream.getTracks().forEach(function (t) { t.stop(); });
        if (recState.ctx && recState.ctx.state !== "closed") recState.ctx.close();
        recordBtn.classList.remove("is-recording");
        recordBtn.querySelector("[data-record-label]").textContent = "Record";
        return;
      }
      try { recState.stream = await navigator.mediaDevices.getUserMedia({ audio: true }); }
      catch (err) { showToast("Mic permission denied"); return; }
      const mime = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
        ? "audio/webm;codecs=opus" : "";
      const chunks = [];
      recState.rec = mime ? new MediaRecorder(recState.stream, { mimeType: mime }) : new MediaRecorder(recState.stream);
      recState.rec.ondataavailable = function (e) { if (e.data && e.data.size > 0) chunks.push(e.data); };
      recState.rec.onstop = function () {
        const blob = new Blob(chunks, { type: chunks[0]?.type || "audio/webm" });
        attachBlob(blob);
      };
      recState.rec.start(250);
      recState.started = Date.now();
      recState.ts = setInterval(function () {
        if (timer) timer.textContent = fmtTime((Date.now() - recState.started) / 1000);
      }, 250);
      recordBtn.classList.add("is-recording");
      recordBtn.querySelector("[data-record-label]").textContent = "Stop";
    });

    // Backend dropdown shows the model_id row only for omni.
    const omniRow = $("#triageOmniRow", root);
    const modelIdInput = $("#triageModelId", root);
    function syncOmniRow() {
      if (!omniRow) return;
      omniRow.style.display = backendSel.value === "omni" ? "block" : "none";
    }
    if (backendSel) backendSel.addEventListener("change", syncOmniRow);
    syncOmniRow();

    let pollJobTimer = 0;
    function stopJobPoll() { clearInterval(pollJobTimer); pollJobTimer = 0; }

    async function pollJob(jobId, runStartMs) {
      try {
        const res = await fetch("/scribe/api/triage/jobs/" + jobId + "/", { credentials: "same-origin" });
        const j = await res.json();
        if (!j.ok) { showToast(j.error || "Job poll failed"); stopJobPoll(); resetRunBtn(); return; }
        const job = j.job;
        const elapsed = Date.now() - runStartMs;
        if (job.status === "running" || job.status === "pending") {
          if (timings) {
            timings.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> '
              + job.backend + " · " + job.device + " · " + job.stage
              + " · elapsed " + fmtElapsed(elapsed);
          }
          return;
        }
        stopJobPoll();
        resetRunBtn();
        if (job.status === "error") {
          rawOut.value = "[error] " + (job.error || "unknown error");
          if (timings) timings.textContent = job.backend + " · " + job.device + " · failed in " + fmtElapsed(elapsed);
          showToast(job.error || "Run failed");
          return;
        }
        // status = done
        rawOut.value = (job.result && job.result.raw_text) || "";
        if (timings) {
          timings.textContent = job.backend + " · " + job.device + " · " + job.elapsed_ms + " ms"
            + (job.result && job.result.audio_saved_as ? " · saved " + job.result.audio_saved_as : "");
        }
        if (typeof autoGrowAny === "function") autoGrowAny(rawOut);
      } catch (err) {
        // network blip — keep polling
      }
    }

    function resetRunBtn() {
      if (!runBtn) return;
      runBtn.disabled = false;
      runBtn.innerHTML = '<iconify-icon icon="iconamoon:player-play-duotone" class="me-1 align-middle"></iconify-icon> Run backend';
    }

    if (runBtn) runBtn.addEventListener("click", async function () {
      const fd = new FormData();
      fd.append("backend", backendSel.value);
      fd.append("device", deviceSel.value);
      fd.append("target_lang", langInput.value || "jam");
      fd.append("text_input", textIn.value || "");
      if (modelIdInput) fd.append("model_id", modelIdInput.value || "facebook/omnilingual-asr-7b-ctc");
      if (currentAudioBlob) {
        const ext = currentAudioBlob.type.indexOf("ogg") >= 0 ? "ogg" :
                    (currentAudioBlob.type.indexOf("mpeg") >= 0 ? "mp3" : "webm");
        fd.append("audio", currentAudioBlob, "triage." + ext);
      }
      runBtn.disabled = true;
      runBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> Submitting…';
      rawOut.value = "";
      if (timings) timings.textContent = "";

      let r;
      try { r = await postForm("/scribe/api/triage/run/", fd); }
      catch (err) {
        resetRunBtn();
        showToast("Network error: " + err.message);
        return;
      }
      if (!r.ok || !r.body || !r.body.ok) {
        resetRunBtn();
        showToast((r.body && r.body.error) || "Run could not start.");
        if (r.body && r.body.error) rawOut.value = "[error] " + r.body.error;
        return;
      }
      const jobId = r.body.job_id;
      const startMs = Date.now();
      runBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> Running… (cancel = leave page)';
      stopJobPoll();
      pollJob(jobId, startMs);  // immediate first poll
      pollJobTimer = setInterval(function () { pollJob(jobId, startMs); }, 2000);
    });

    if (interpretBtn) interpretBtn.addEventListener("click", async function () {
      const text = (rawOut.value || textIn.value || "").trim();
      if (!text) { showToast("Run a backend first or paste raw text."); return; }
      interpretBtn.disabled = true;
      const orig = interpretBtn.innerHTML;
      interpretBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> Interpreting…';
      let r;
      try { r = await postJSON("/scribe/api/triage/interpret/", { text: text }); }
      catch (err) { interpretBtn.disabled = false; interpretBtn.innerHTML = orig; showToast("Network error"); return; }
      interpretBtn.disabled = false;
      interpretBtn.innerHTML = orig;
      if (!r.ok || !r.body || !r.body.ok) {
        showToast((r.body && r.body.error) || "Interpretation failed.");
        return;
      }
      cleanOut.value = r.body.clean_text || "";
    });

    function autoGrowAny(el) {
      el.style.height = "auto";
      el.style.height = Math.min(800, el.scrollHeight + 4) + "px";
    }
    [rawOut, cleanOut, textIn].forEach(function (el) {
      if (!el) return;
      autoGrowAny(el);
      el.addEventListener("input", function () { autoGrowAny(el); });
    });

    // ---- env probe + install + download wiring ----
    const downloadBtn = $("#downloadModelsBtn", root);
    const downloadStatus = $("#downloadStatus", root);
    const installCpuBtn = $("#installDepsCpuBtn", root);
    const installCudaBtn = $("#installDepsCudaBtn", root);
    const installStatus = $("#installStatus", root);
    let installPollTimer = 0;
    let downloadPollTimer = 0;
    let installStartedAt = 0;

    function fmtElapsed(ms) {
      const s = Math.round(ms / 1000);
      if (s < 60) return s + "s";
      return Math.floor(s / 60) + "m " + (s % 60) + "s";
    }

    async function probe() {
      try {
        const res = await fetch("/scribe/api/triage/probe/", { credentials: "same-origin" });
        const j = await res.json();
        if (!j.ok) return j;
        const env = j.env;
        // Update visible env list cells.
        const mmsEl = root.querySelector("[data-env-mms]");
        const t5El = root.querySelector("[data-env-t5]");
        if (mmsEl) mmsEl.textContent = env.model_cached_mms ? "yes" : "no";
        if (t5El) t5El.textContent = env.model_cached_t5 ? "yes" : "no";
        return j;
      } catch (e) {
        return null;
      }
    }

    async function startInstall(profile, forceReinstall) {
      const reinstallBtn = $("#reinstallCudaBtn", root);
      const btn = reinstallBtn && forceReinstall ? reinstallBtn :
                  (profile === "cuda" ? installCudaBtn : installCpuBtn);
      const otherBtn = profile === "cuda" ? installCpuBtn : installCudaBtn;
      if (!btn) return;
      const orig = btn.innerHTML;
      btn.disabled = true;
      if (otherBtn) otherBtn.disabled = true;
      btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> Installing…';
      if (installStatus) installStatus.textContent = "Starting pip install (" + profile +
        (forceReinstall ? ", force-reinstall" : "") + ")…";

      let r;
      try {
        r = await postJSON("/scribe/api/triage/install/",
                           { profile: profile, force_reinstall: !!forceReinstall });
      } catch (err) {
        btn.disabled = false;
        if (otherBtn) otherBtn.disabled = false;
        btn.innerHTML = orig;
        if (installStatus) installStatus.textContent = "Network error: " + err.message;
        return;
      }
      if (!r.ok || !r.body || !r.body.ok) {
        btn.disabled = false;
        if (otherBtn) otherBtn.disabled = false;
        btn.innerHTML = orig;
        if (installStatus) installStatus.textContent = (r.body && r.body.error) || "Install did not start.";
        return;
      }

      installStartedAt = Date.now();
      if (installStatus) {
        installStatus.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> '
          + 'Install running in background (' + profile + '). This typically takes 2–6 minutes for torch + transformers. Elapsed: 0s';
      }
      // Poll the env probe every 5s; flip UI when transformers + torch + librosa appear.
      clearInterval(installPollTimer);
      installPollTimer = setInterval(async function () {
        const j = await probe();
        const elapsed = Date.now() - installStartedAt;
        if (installStatus) {
          installStatus.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> '
            + 'Installing (' + profile + '). Elapsed: ' + fmtElapsed(elapsed)
            + '. The page reloads once deps are ready.';
        }
        if (j && j.ok && j.env.transformers && j.env.torch && j.env.librosa) {
          clearInterval(installPollTimer);
          if (installStatus) {
            installStatus.innerHTML = '<span class="text-success fw-semibold">'
              + '✓ Deps installed in ' + fmtElapsed(elapsed)
              + '. Reloading page so the Download button unlocks…</span>';
          }
          setTimeout(function () { window.location.reload(); }, 1500);
        }
      }, 5000);
    }

    // Expose to window so inline onclick attributes can call them too — defensive
    // against any case where the addEventListener binding races or is missed.
    window.WELLNEST_triage_install = startInstall;
    console.log("[wellnest] triage init OK", {
      installCpuBtn: !!installCpuBtn,
      installCudaBtn: !!installCudaBtn,
      downloadBtn: !!downloadBtn,
    });
    if (installCpuBtn) installCpuBtn.addEventListener("click", function () { startInstall("cpu"); });
    if (installCudaBtn) installCudaBtn.addEventListener("click", function () { startInstall("cuda"); });

    async function startDownload() {
      if (!downloadBtn) return;
      if (downloadBtn.disabled) return;
      downloadBtn.disabled = true;
      const orig = downloadBtn.innerHTML;
      downloadBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> Downloading… (~5 GB)';
      if (downloadStatus) {
        downloadStatus.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> '
          + 'Started in the background. Polling cache status…';
      }
      let r;
      try { r = await postJSON("/scribe/api/triage/download/", { target: "all" }); }
      catch (err) {
        downloadBtn.disabled = false;
        downloadBtn.innerHTML = orig;
        if (downloadStatus) downloadStatus.textContent = "Network error: " + err.message;
        return;
      }
      if (!r.ok || !r.body || !r.body.ok) {
        downloadBtn.disabled = false;
        downloadBtn.innerHTML = orig;
        if (downloadStatus) downloadStatus.textContent = (r.body && r.body.error) || "Download could not start.";
        return;
      }
      const startedAt = Date.now();
      clearInterval(downloadPollTimer);
      downloadPollTimer = setInterval(async function () {
        const j = await probe();
        const elapsed = Date.now() - startedAt;
        if (downloadStatus) {
          downloadStatus.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> '
            + 'Downloading. Elapsed: ' + fmtElapsed(elapsed)
            + '. ~5 GB total — first run takes 5–15 min depending on your link.';
        }
        if (j && j.ok && j.env.model_cached_mms && j.env.model_cached_t5) {
          clearInterval(downloadPollTimer);
          if (downloadStatus) {
            downloadStatus.innerHTML = '<span class="text-success fw-semibold">'
              + '✓ Both models cached in ' + fmtElapsed(elapsed) + '. Ready to run.</span>';
          }
          downloadBtn.classList.add("btn-success");
          downloadBtn.classList.remove("btn-outline-primary");
          downloadBtn.innerHTML = '<iconify-icon icon="iconamoon:check-circle-1-duotone" class="me-1 align-middle"></iconify-icon> Models ready';
        }
      }, 8000);
    }
    window.WELLNEST_triage_download = startDownload;
    if (downloadBtn) downloadBtn.addEventListener("click", startDownload);
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
    function resetQrModal() {
      if (qrLoader) {
        qrLoader.classList.remove("d-none");
        qrLoader.innerHTML = '<div class="spinner-border text-primary" role="status"><span class="visually-hidden">Loading…</span></div>'
                          + '<p class="text-muted small mt-2 mb-0">Building share link…</p>';
      }
      if (qrCanvas) { qrCanvas.classList.add("d-none"); qrCanvas.innerHTML = ""; }
      if (qrLinkRow) qrLinkRow.classList.add("d-none");
    }
    function showQrError(msg) {
      if (qrLoader) {
        qrLoader.classList.remove("d-none");
        qrLoader.innerHTML = "<p class='text-danger small mb-0'>" + msg + "</p>";
      }
    }
    async function loadShareLink() {
      resetQrModal();
      let r;
      try {
        r = await postJSON("/scribe/api/sessions/" + sessionId + "/share/", {});
      } catch (err) {
        console.error("share fetch failed", err);
        showQrError("Network error: " + err.message);
        return;
      }
      if (!r.ok || !r.body || !r.body.ok) {
        showQrError((r.body && r.body.error) || "Could not build share link.");
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
    }
    if (shareModalEl) {
      shareModalEl.addEventListener("show.bs.modal", loadShareLink);
    }
    if (qrCopyLink) qrCopyLink.addEventListener("click", async function () {
      try { await navigator.clipboard.writeText(qrLink.value); showToast("Link copied"); }
      catch (e) { qrLink.select(); document.execCommand("copy"); }
    });

    // Suggest improvements
    const improveBtn = $("#improveBtn", root);
    const improveResult = $("#improveResult", root);
    const improveBody = $("#improveBody", root);
    if (improveBtn) improveBtn.addEventListener("click", async function () {
      improveBtn.disabled = true;
      const originalLabel = improveBtn.innerHTML;
      improveBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1" role="status"></span> Checking…';
      await autosave();
      let r;
      try { r = await postJSON("/scribe/api/sessions/" + sessionId + "/improve/", {}); }
      catch (err) {
        improveBtn.disabled = false;
        improveBtn.innerHTML = originalLabel;
        showToast("Network error: " + err.message);
        return;
      }
      improveBtn.disabled = false;
      improveBtn.innerHTML = originalLabel;
      if (!r.ok || !r.body || !r.body.ok) {
        showToast((r.body && r.body.error) || "Could not get suggestions.");
        return;
      }
      const lines = (r.body.suggestions || "").split(/\r?\n/).filter(Boolean);
      improveBody.innerHTML = "<ul class='list-unstyled mb-0'>" +
        lines.map(function (l) {
          const txt = l.replace(/^\s*[-*•]\s*/, "");
          return '<li class="d-flex gap-2 mb-2"><iconify-icon icon="iconamoon:lightning-1-duotone" class="text-primary mt-1"></iconify-icon><span>' +
                 txt.replace(/[<>&]/g, function (c) { return ({"<":"&lt;",">":"&gt;","&":"&amp;"})[c]; }) +
                 '</span></li>';
        }).join("") + "</ul>";
      improveResult.classList.remove("d-none");
    });

    // Keyboard shortcuts
    document.addEventListener("keydown", function (e) {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
        e.preventDefault(); autosave();
      } else if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === "c") {
        e.preventDefault(); if (copyBtn) copyBtn.click();
      }
    });

    // Polish grammar
    const polishBtn = $("#polishBtn", root);
    if (polishBtn) polishBtn.addEventListener("click", async function () {
      polishBtn.disabled = true;
      const originalLabel = polishBtn.innerHTML;
      polishBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1" role="status"></span> Polishing…';
      await autosave();
      let r;
      try { r = await postJSON("/scribe/api/sessions/" + sessionId + "/polish/", {}); }
      catch (err) { polishBtn.disabled = false; polishBtn.innerHTML = originalLabel; showToast("Network error: " + err.message); return; }
      polishBtn.disabled = false;
      polishBtn.innerHTML = originalLabel;
      if (!r.ok || !r.body || !r.body.ok) {
        showToast((r.body && r.body.error) || "Polish failed.");
        return;
      }
      // Apply returned text to fields + narrative.
      fields.forEach(function (el) {
        const k = el.getAttribute("data-note-field");
        if (k && k in r.body) { el.value = r.body[k] || ""; autoGrow(el); }
      });
      if (fullNoteArea) {
        fullNoteArea.value = r.body.edited_note || "";
        delete fullNoteArea.dataset.manualEdit;
        autoGrow(fullNoteArea);
      }
      updateWordCount();
      showToast("Grammar polished");
    });

    // Auto-grow all editable textareas in this view.
    function autoGrow(el) {
      el.style.height = "auto";
      el.style.height = Math.min(800, el.scrollHeight + 4) + "px";
    }
    function attachAutoGrow(el) {
      autoGrow(el);
      el.addEventListener("input", function () { autoGrow(el); });
    }
    fields.forEach(attachAutoGrow);
    if (fullNoteArea) attachAutoGrow(fullNoteArea);
    if (transcriptArea) attachAutoGrow(transcriptArea);

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
