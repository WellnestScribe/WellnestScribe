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
  function summarizeErrorText(text, status) {
    const raw = (text || "").trim();
    if (!raw) return "HTTP " + status;
    if (raw.startsWith("<!DOCTYPE") || raw.startsWith("<html")) {
      const titleMatch = raw.match(/<title>(.*?)<\/title>/i);
      const bodyTitleMatch = raw.match(/<h1[^>]*>(.*?)<\/h1>/i);
      const title = titleMatch ? titleMatch[1] : (bodyTitleMatch ? bodyTitleMatch[1] : "");
      return title ? title.replace(/\s+/g, " ").trim() : ("Server error (HTTP " + status + ")");
    }
    return raw;
  }
  function postJSON(url, payload) {
    return fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
      body: JSON.stringify(payload || {}),
    }).then(async function (r) {
      const text = await r.text();
      let body;
      try {
        body = text ? JSON.parse(text) : {};
      } catch (err) {
        body = { ok: false, error: summarizeErrorText(text, r.status) };
      }
      return { ok: r.ok, body: body };
    });
  }
  function postForm(url, formData) {
    return fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrf },
      body: formData,
    }).then(async function (r) {
      const text = await r.text();
      let body;
      try {
        body = text ? JSON.parse(text) : {};
      } catch (err) {
        body = { ok: false, error: summarizeErrorText(text, r.status) };
      }
      return { ok: r.ok, body: body };
    });
  }
  function setStatus(target, text, kind) {
    if (!target) return;
    target.textContent = text;
    target.classList.remove("is-error", "is-success");
    if (kind === "error") target.classList.add("is-error");
    if (kind === "success") target.classList.add("is-success");
  }
  function extractPatientName(transcript) {
    if (!transcript) return "";
    // Strip common prefix phrases, take first 1-4 capitalised words
    var t = transcript.trim()
      .replace(/^(the patient('s name)? is|patient|my name is|this is|name is)\s*/i, "")
      .replace(/[.,!?;:].*$/, "").trim();
    var words = t.split(/\s+/).filter(function(w) { return w.length > 1; }).slice(0, 4);
    // Only use if the first word looks like a proper name (starts capital or all caps)
    if (!words.length || !/^[A-Z]/.test(words[0])) return "";
    return words.join(" ");
  }

  function autoGrow(el) {
    if (!el) return;
    el.style.height = "auto";
    // Fit to content. Per Dr Adrian feedback: fields should shrink when
    // empty so the doctor doesn't have to scroll past acres of whitespace.
    // Floor at ~48px so a single empty row is still tappable on mobile.
    el.style.height = Math.min(1200, Math.max(el.scrollHeight + 2, 48)) + "px";
  }
  function syncRecordNoteStyle(value) {
    const recordSel = $("#noteFormatSelect");
    if (recordSel) recordSel.value = value;
    $$("[data-note-style]").forEach(function (btn) {
      const active = btn.getAttribute("data-note-style") === value;
      btn.classList.toggle("is-active", active);
      btn.setAttribute("aria-pressed", active ? "true" : "false");
    });
  }
  function syncSuggestiveAssistState(checked) {
    const prefToggle = $("#prefSuggestiveAssist");
    const recordToggle = $("#suggestiveAssistToggle");
    if (prefToggle && prefToggle.checked !== checked) prefToggle.checked = checked;
    if (recordToggle && recordToggle.checked !== checked) recordToggle.checked = checked;
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

  // ---------- confirm dialog (SweetAlert when available) ----------
  // Falls back to native confirm() if Swal isn't loaded yet (e.g. vendor.js
  // not on this page). Returns a Promise<boolean>.
  function confirmDialog(opts) {
    const cfg = opts || {};
    if (window.Swal && typeof window.Swal.fire === "function") {
      return window.Swal.fire({
        title: cfg.title || "Are you sure?",
        html: cfg.html || cfg.text || "",
        icon: cfg.icon || "question",
        showCancelButton: true,
        confirmButtonText: cfg.confirmText || "Confirm",
        cancelButtonText: cfg.cancelText || "Cancel",
        confirmButtonColor: cfg.confirmColor || "#0f7af2",
        cancelButtonColor: "#94a3b8",
        reverseButtons: true,
        focusCancel: !!cfg.focusCancel,
      }).then(function (r) { return !!r.isConfirmed; });
    }
    const fallbackText = (cfg.title ? cfg.title + "\n\n" : "") +
      (cfg.html ? cfg.html.replace(/<br\s*\/?>/gi, "\n").replace(/<[^>]+>/g, "") : (cfg.text || ""));
    return Promise.resolve(window.confirm(fallbackText));
  }
  window.WELLNEST_confirm = confirmDialog;

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

  // Font-size shortcut button — opens the same Display dropdown as the cog.
  const fontSizeBtn = $("#topbarFontSizeBtn");
  if (fontSizeBtn) {
    fontSizeBtn.addEventListener("click", function (e) {
      e.preventDefault();
      const cog = document.querySelector('[aria-label="Display settings"]');
      if (cog && window.bootstrap && window.bootstrap.Dropdown) {
        window.bootstrap.Dropdown.getOrCreateInstance(cog).toggle();
        setTimeout(function () {
          const r = document.getElementById("prefFontScale");
          if (r) r.focus();
        }, 50);
      } else if (cog) {
        cog.click();
      }
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
      syncRecordNoteStyle(noteStyleSel.value);
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
  const suggestiveAssistChk = $("#prefSuggestiveAssist");
  if (suggestiveAssistChk) {
    suggestiveAssistChk.addEventListener("change", function () {
      syncSuggestiveAssistState(suggestiveAssistChk.checked);
      postJSON(W.endpoints.updatePreferences, { suggestive_assist: suggestiveAssistChk.checked });
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

  // ---------- shared mic settings / calibration ----------
  const MIC_LS_KEY = "wellnest_mic_device_id";

  function initMicSettings(container) {
    const toggleBtn = $("#micSettingsToggle", container);
    const panel = $("#micSettingsPanel", container);
    const deviceSelect = $("#micDeviceSelect", container);
    const testBtn = $("#micTestBtn", container);
    const levelWrap = $("#micLevelWrap", container);
    const levelBar = $("#micLevelBar", container);
    const levelHint = $("#micLevelHint", container);
    if (!toggleBtn || !panel) return;

    let testStream = null, testCtx = null, testAnim = 0;

    async function populateDevices() {
      try {
        const devices = await navigator.mediaDevices.enumerateDevices();
        const inputs = devices.filter(function (d) { return d.kind === "audioinput"; });
        if (!deviceSelect) return;
        const saved = localStorage.getItem(MIC_LS_KEY) || "";
        deviceSelect.innerHTML = '<option value="">Default microphone</option>';
        inputs.forEach(function (d) {
          const opt = document.createElement("option");
          opt.value = d.deviceId;
          opt.textContent = d.label || ("Microphone " + d.deviceId.slice(0, 8));
          if (d.deviceId === saved) opt.selected = true;
          deviceSelect.appendChild(opt);
        });
      } catch (e) {}
    }

    toggleBtn.addEventListener("click", async function () {
      const open = panel.style.display !== "none";
      panel.style.display = open ? "none" : "";
      if (!open) {
        // Brief permission probe so device labels show (labels are hidden until
        // the user has granted mic access at least once).
        try {
          const tmp = await navigator.mediaDevices.getUserMedia({ audio: true });
          tmp.getTracks().forEach(function (t) { t.stop(); });
        } catch (e) {}
        await populateDevices();
        // Auto-start level meter — no extra click needed
        if (testBtn && !testStream) testBtn.click();
      } else {
        // Auto-stop when panel closes to release the mic
        if (testStream) stopTest();
      }
    });

    if (deviceSelect) {
      deviceSelect.addEventListener("change", function () {
        localStorage.setItem(MIC_LS_KEY, deviceSelect.value);
      });
    }

    function stopTest() {
      cancelAnimationFrame(testAnim);
      if (testStream) testStream.getTracks().forEach(function (t) { t.stop(); });
      if (testCtx && testCtx.state !== "closed") testCtx.close();
      testStream = null; testCtx = null;
      if (levelWrap) levelWrap.style.display = "none";
      if (levelBar) levelBar.style.width = "0%";
      if (testBtn) testBtn.textContent = "Test mic";
    }

    if (testBtn) {
      testBtn.addEventListener("click", async function () {
        if (testStream) { stopTest(); return; }
        const deviceId = deviceSelect ? deviceSelect.value : "";
        const constraint = deviceId
          ? { audio: { deviceId: { exact: deviceId } } }
          : { audio: true };
        try { testStream = await navigator.mediaDevices.getUserMedia(constraint); }
        catch (err) {
          if (levelHint) levelHint.textContent = "Cannot open mic: " + err.message;
          if (levelWrap) levelWrap.style.display = "";
          return;
        }
        testCtx = new (window.AudioContext || window.webkitAudioContext)();
        const src = testCtx.createMediaStreamSource(testStream);
        const analyser = testCtx.createAnalyser();
        analyser.fftSize = 512;
        src.connect(analyser);
        const data = new Uint8Array(analyser.fftSize);
        if (levelWrap) levelWrap.style.display = "";
        if (levelHint) levelHint.textContent = "Speak — bar should move.";
        if (testBtn) testBtn.textContent = "Stop test";

        function tick() {
          analyser.getByteTimeDomainData(data);
          let sum = 0;
          for (let i = 0; i < data.length; i++) { const v = (data[i] / 128) - 1; sum += v * v; }
          const pct = Math.min(100, Math.round(Math.sqrt(sum / data.length) * 300));
          if (levelBar) {
            levelBar.style.width = pct + "%";
            levelBar.style.background = pct > 70 ? "#d33b46" : pct > 35 ? "#e89c1d" : "#2d8a4e";
          }
          if (levelHint) {
            levelHint.textContent = pct < 4
              ? "No signal — check mic or try a different device."
              : pct < 15
              ? "Very low — move closer to the microphone."
              : pct < 55
              ? "Good signal — ready to record."
              : pct < 80
              ? "Strong signal — excellent."
              : "Very loud — may clip. Move slightly back.";
            levelHint.style.color = pct < 4 ? "#d33b46" : pct < 15 ? "#e89c1d" : "#2d8a4e";
          }
          testAnim = requestAnimationFrame(tick);
        }
        tick();
      });
    }
  }

  function getMicConstraint() {
    const id = localStorage.getItem(MIC_LS_KEY) || "";
    return id ? { deviceId: { exact: id } } : true;
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
    const pauseBtn = $("#recordPauseBtn", root);
    const timerEl = $("#recordTimer", root);
    const waveBars = $("#recordWaveform", root);
    const statusEl = $("#recordStatus", root);
    const noteFormatSel = $("#noteFormatSelect", root);
    const noteStyleBtns = $$("[data-note-style]", root);
    const suggestiveAssistToggle = $("#suggestiveAssistToggle", root);
    const lengthSwitch = $("#lengthModeSwitch", root);
    const transcriptArea = $("#manualTranscript", root);
    const generateBtn = $("#generateBtn", root);
    const fileInput = $("#audioFileInput", root);
    const uploadBtn = $("#audioUploadBtn", root);
    const cancelBtn = $("#recordCancelBtn", root);

    if (noteFormatSel) syncRecordNoteStyle(noteFormatSel.value);
    noteStyleBtns.forEach(function (btn) {
      btn.addEventListener("click", function () {
        const next = btn.getAttribute("data-note-style");
        if (!next || !noteFormatSel) return;
        noteFormatSel.value = next;
        syncRecordNoteStyle(next);
      });
    });
    if (suggestiveAssistToggle) {
      syncSuggestiveAssistState(suggestiveAssistToggle.checked);
      suggestiveAssistToggle.addEventListener("change", function () {
        syncSuggestiveAssistState(suggestiveAssistToggle.checked);
        postJSON(W.endpoints.updatePreferences, { suggestive_assist: suggestiveAssistToggle.checked });
        if (window.WELLNEST_toast) {
          window.WELLNEST_toast(
            suggestiveAssistToggle.checked
              ? "Suggestive assist on"
              : "Suggestive assist off"
          );
        }
      });
    }

    if (transcriptArea) {
      autoGrow(transcriptArea);
      transcriptArea.addEventListener("input", function () { autoGrow(transcriptArea); });
    }

    initMicSettings(root);
    const micDotEl = $("#micLiveDot", root);

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
    let recordCancelled = false;
    let isPaused = false;
    let pausedElapsed = 0;

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
        let sum = 0;
        spans.forEach(function (sp, idx) {
          const v = data[idx * 3] || 0;
          sum += v;
          sp.style.height = Math.max(8, (v / 255) * 46) + "px";
        });
        if (micDotEl) micDotEl.classList.toggle("is-active", (sum / spans.length) > 10);
        waveAnimHandle = requestAnimationFrame(tick);
      }
      tick();
    }
    function stopWavePump() {
      cancelAnimationFrame(waveAnimHandle);
      if (waveBars) waveBars.querySelectorAll("span").forEach(function (sp) { sp.style.height = "8px"; });
      if (micDotEl) micDotEl.classList.remove("is-active");
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
      try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: getMicConstraint() });
      } catch (err) {
        if (err.name === "OverconstrainedError" || err.name === "NotFoundError") {
          localStorage.removeItem(MIC_LS_KEY);
          try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); }
          catch (err2) { setStatus(statusEl, "Microphone permission denied.", "error"); return; }
          setStatus(statusEl, "Saved mic unavailable — switched to default.", "error");
        } else {
          setStatus(statusEl, "Microphone permission denied.", "error"); return;
        }
      }
      recordedChunks = [];
      isPaused = false;
      pausedElapsed = 0;
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

      recordCancelled = false;
      recordBtn.classList.add("is-recording");
      recordBtn.querySelector("[data-record-label]").textContent = "Stop";
      if (pauseBtn) pauseBtn.style.display = "";
      if (cancelBtn) cancelBtn.style.display = "";
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
      if (pauseBtn) {
        pauseBtn.style.display = "none";
        pauseBtn.classList.remove("is-paused");
        if (pauseBtn.querySelector("iconify-icon")) pauseBtn.querySelector("iconify-icon").setAttribute("icon", "iconamoon:pause-duotone");
        var lbl = document.getElementById("pauseBtnLabel");
        if (lbl) lbl.textContent = "Pause";
      }
      if (cancelBtn) cancelBtn.style.display = "none";
      isPaused = false;
    }

    if (pauseBtn) {
      pauseBtn.addEventListener("click", function () {
        if (!mediaRecorder || mediaRecorder.state === "inactive") return;
        if (isPaused) {
          // Resume
          try { mediaRecorder.resume(); } catch (e) {}
          isPaused = false;
          // Restart timer from accumulated elapsed
          startedAt = Date.now() - pausedElapsed * 1000;
          timerHandle = setInterval(function () {
            if (timerEl) timerEl.textContent = fmtTime((Date.now() - startedAt) / 1000);
          }, 250);
          buildWavePump();
          pauseBtn.classList.remove("is-paused");
          if (pauseBtn.querySelector("iconify-icon")) pauseBtn.querySelector("iconify-icon").setAttribute("icon", "iconamoon:pause-duotone");
          var lbl = document.getElementById("pauseBtnLabel");
          if (lbl) lbl.textContent = "Pause";
          setStatus(statusEl, "Recording resumed.");
        } else {
          // Pause
          try { mediaRecorder.pause(); } catch (e) {}
          isPaused = true;
          pausedElapsed = Math.round((Date.now() - startedAt) / 1000);
          clearInterval(timerHandle);
          stopWavePump();
          pauseBtn.classList.add("is-paused");
          if (pauseBtn.querySelector("iconify-icon")) pauseBtn.querySelector("iconify-icon").setAttribute("icon", "iconamoon:play-duotone");
          var lbl2 = document.getElementById("pauseBtnLabel");
          if (lbl2) lbl2.textContent = "Resume";
          setStatus(statusEl, "Paused — tap Resume to continue.");
        }
      });
    }
    async function onRecordingStopped() {
      if (recordCancelled) {
        recordedChunks = [];
        setStatus(statusEl, "Recording cancelled.");
        return;
      }
      const blob = new Blob(recordedChunks, { type: recordedChunks[0]?.type || "audio/webm" });
      recordedBlob = blob;
      setStatus(statusEl, "Captured " + fmtTime(recordedDuration) + " of audio. Uploading…");
      await uploadAndProcess(blob);
    }
    function collectPatientFields(fd) {
      // Patient bar lives ABOVE the card now (not inside `root`), so query
      // the whole document — these IDs are unique on the page.
      const nameEl = document.getElementById("patientName");
      const idEl = document.getElementById("patientIdentifier");
      const genderEl = document.getElementById("patientGender");
      if (nameEl && nameEl.value.trim()) fd.append("patient_name", nameEl.value.trim());
      if (idEl && idEl.value.trim()) fd.append("patient_identifier", idEl.value.trim());
      if (genderEl && genderEl.value) fd.append("patient_gender", genderEl.value);
    }

    async function uploadAndProcess(blob) {
      const fd = new FormData();
      const ext = blob.type.indexOf("ogg") >= 0 ? "ogg" : "webm";
      fd.append("audio", blob, "wellnest-recording." + ext);
      fd.append("note_format", noteFormatSel ? noteFormatSel.value : "soap");
      fd.append("length_mode", lengthSwitch ? (lengthSwitch.type === "checkbox" ? (lengthSwitch.checked ? "long_form" : "normal") : (lengthSwitch.value || "normal")) : "normal");
      fd.append("duration_seconds", String(recordedDuration));
      if (window.WELLNEST_consentGiven) fd.append("consent_acknowledged", "1");
      collectPatientFields(fd);
      const res = await postForm(W.endpoints.createSession, fd);
      if (!res.ok || !res.body.ok) { setStatus(statusEl, (res.body && res.body.error) || "Upload failed.", "error"); return; }
      const sid = res.body.session_id;
      setStatus(statusEl, "Transcribing audio…");
      const tr = await postJSON("/scribe/api/sessions/" + sid + "/transcribe/", {});
      if (!tr.ok || !tr.body.ok) { setStatus(statusEl, (tr.body && tr.body.error) || "Transcription failed.", "error"); return; }
      if (transcriptArea) {
        transcriptArea.value = tr.body.transcript || "";
        autoGrow(transcriptArea);
      }
      // Auto-populate patient name from transcript if field is empty
      var nameEl = document.getElementById("patientName");
      if (nameEl && !nameEl.value.trim() && tr.body.transcript) {
        var extracted = extractPatientName(tr.body.transcript);
        if (extracted) {
          nameEl.value = extracted;
          // Persist back to the session so history list shows the name
          postJSON("/scribe/api/sessions/" + sid + "/rename/", {patient_name: extracted});
        }
      }
      setStatus(statusEl, "Generating note…");
      await runGeneration(sid, tr.body.transcript || "");
    }
    function getRecordLengthMode() {
      if (!lengthSwitch) return "normal";
      return lengthSwitch.type === "checkbox"
        ? (lengthSwitch.checked ? "long_form" : "normal")
        : (lengthSwitch.value || "normal");
    }

    async function runGeneration(sid, transcript) {
      const tmplInstr = document.getElementById("templateInstructions");
      const payload = {
        transcript: transcript,
        note_format: noteFormatSel ? noteFormatSel.value : "soap",
        length_mode: getRecordLengthMode(),
        suggestive_assist: suggestiveAssistToggle ? suggestiveAssistToggle.checked : undefined,
        custom_instructions: tmplInstr ? (tmplInstr.value || "") : "",
      };
      const gen = await postJSON("/scribe/api/sessions/" + sid + "/generate/", payload);
      if (!gen.ok || !gen.body.ok) { setStatus(statusEl, (gen.body && gen.body.error) || "Note generation failed.", "error"); return; }
      setStatus(statusEl, "Done — opening review.", "success");
      window.location.href = gen.body.review_url;
    }

    function maybeStartRecording() {
      var gate = window.WELLNEST_beforeRecord;
      if (typeof gate === "function") { gate(startRecording); } else { startRecording(); }
    }

    if (recordBtn) recordBtn.addEventListener("click", function () {
      if (recordBtn.classList.contains("is-recording")) stopRecording(); else maybeStartRecording();
    });
    if (cancelBtn) cancelBtn.addEventListener("click", function () {
      recordCancelled = true;
      stopRecording();
      if (window.WELLNEST_toast) window.WELLNEST_toast("Recording discarded.");
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
        autoGrow(transcriptArea);
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
      if (/\[[^\]]{1,60}\]/.test(transcript)) {
        const go = await confirmDialog({
          title: "Template not filled in",
          html: "The note still has unfilled placeholders like <code>[Age]</code> or <code>[findings]</code>.<br><br>" +
                "If you generate now the AI will <strong>invent values</strong> for every blank — the result will look real but will be fabricated.<br><br>" +
                "Replace the brackets with this patient's actual details first.",
          icon: "warning",
          confirmText: "Generate anyway",
          cancelText: "Go back and fill in",
          focusCancel: true,
        });
        if (!go) return;
      }
      const fd = new FormData();
      fd.append("transcript", transcript);
      fd.append("note_format", noteFormatSel ? noteFormatSel.value : "soap");
      fd.append("length_mode", getRecordLengthMode());
      collectPatientFields(fd);
      const res = await postForm(W.endpoints.createSession, fd);
      if (!res.ok || !res.body.ok) { setStatus(statusEl, (res.body && res.body.error) || "Could not create session.", "error"); return; }
      setStatus(statusEl, "Generating note…");
      await runGeneration(res.body.session_id, transcript);
    });
  }

  // ---------- drug interaction checker ----------
  const drugCheckRoot = document.querySelector("[data-screen='drug-check']");
  if (drugCheckRoot) initDrugCheckScreen(drugCheckRoot);

  function initDrugCheckScreen(root) {
    const currentChipsBox = $("#dcCurrentChips", root);
    const herbChipsBox = $("#dcHerbChips", root);
    const currentInput = $("#dcCurrentInput", root);
    const herbInput = $("#dcHerbInput", root);
    const currentAddBtn = $("#dcCurrentAddBtn", root);
    const herbAddBtn = $("#dcHerbAddBtn", root);
    const proposedInput = $("#dcProposed", root);

    // ---- lightweight typeahead ----
    // Wire each [data-typeahead] block to its sibling [data-typeahead-list].
    // Backed by /scribe/api/drug-search/ or /api/herb-search/ depending on
    // the data-typeahead value. Free text is still allowed — selecting from
    // the list is convenience, not a constraint.
    function escHtml(s) {
      return String(s == null ? "" : s)
        .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
    }
    function wireTypeahead(wrap) {
      const kind = wrap.getAttribute("data-typeahead");
      const inp = wrap.querySelector("[data-typeahead-input]");
      const list = wrap.querySelector("[data-typeahead-list]");
      if (!inp || !list) return;
      const endpoint = kind === "herb" ? "/scribe/api/herb-search/" : "/scribe/api/drug-search/";
      let timer = 0;
      let lastQ = "";

      function hide() { list.classList.remove("is-open"); list.innerHTML = ""; }
      function open() { list.classList.add("is-open"); }
      function pick(label) {
        inp.value = label;
        hide();
        inp.dispatchEvent(new Event("typeahead-pick", { bubbles: true }));
        inp.focus();
      }
      async function fetchSuggestions(q) {
        try {
          const res = await fetch(endpoint + "?q=" + encodeURIComponent(q), { credentials: "same-origin" });
          const json = await res.json();
          return (json && json.results) || [];
        } catch (e) { return []; }
      }
      function render(results) {
        if (!results.length) { hide(); return; }
        list.innerHTML = results.map(function (r) {
          const subParts = [];
          if (r.generic && r.generic !== r.label) subParts.push(r.generic);
          if (r.drug_class) subParts.push(r.drug_class);
          const sub = subParts.join(" · ");
          return '<li role="option" data-pick="' + escHtml(r.label) + '">' +
                   '<span class="typeahead-label">' + escHtml(r.label) + '</span>' +
                   (sub ? '<span class="typeahead-sub">' + escHtml(sub) + '</span>' : '') +
                 '</li>';
        }).join("");
        list.querySelectorAll("li").forEach(function (li) {
          li.addEventListener("mousedown", function (e) {  // mousedown so input blur doesn't kill the click
            e.preventDefault();
            pick(li.getAttribute("data-pick") || "");
          });
        });
        open();
      }
      inp.addEventListener("input", function () {
        const q = inp.value.trim();
        if (q === lastQ) return;
        lastQ = q;
        clearTimeout(timer);
        if (q.length < 2) { hide(); return; }
        timer = setTimeout(async function () {
          const results = await fetchSuggestions(q);
          render(results);
        }, 140);
      });
      inp.addEventListener("blur", function () { setTimeout(hide, 120); });
      inp.addEventListener("keydown", function (e) {
        if (e.key === "Escape") hide();
        if (e.key === "Tab") hide();
      });
    }
    $$("[data-typeahead]", root).forEach(wireTypeahead);
    const ageInput = $("#dcAge", root);
    const sexInput = $("#dcSex", root);
    const conditionsInput = $("#dcConditions", root);
    const allergiesInput = $("#dcAllergies", root);
    const runBtn = $("#dcRunBtn", root);
    const statusEl = $("#dcStatus", root);
    const sevPill = $("#dcSeverityPill", root);
    const resultEl = $("#dcResult", root);
    const unrecEl = $("#dcUnrecognized", root);
    const disclaimerEl = $("#dcDisclaimer", root);

    let currentMeds = [];
    let herbs = [];

    function renderChips(list, box) {
      box.innerHTML = "";
      list.forEach(function (name, idx) {
        const chip = document.createElement("span");
        chip.className = "drug-chip";
        chip.innerHTML = escHtml(name) +
          '<button type="button" class="drug-chip-x" aria-label="Remove">&times;</button>';
        chip.querySelector(".drug-chip-x").addEventListener("click", function () {
          list.splice(idx, 1);
          renderChips(list, box);
        });
        box.appendChild(chip);
      });
    }
    function addFrom(inp, list, box) {
      const v = (inp.value || "").trim();
      if (!v) return;
      list.push(v);
      inp.value = "";
      renderChips(list, box);
      inp.focus();
    }
    currentAddBtn.addEventListener("click", function () { addFrom(currentInput, currentMeds, currentChipsBox); });
    herbAddBtn.addEventListener("click", function () { addFrom(herbInput, herbs, herbChipsBox); });
    [currentInput, herbInput].forEach(function (inp) {
      inp.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === ",") {
          e.preventDefault();
          if (inp === currentInput) addFrom(currentInput, currentMeds, currentChipsBox);
          else addFrom(herbInput, herbs, herbChipsBox);
        }
      });
    });

    function severityClass(sev) {
      switch ((sev || "").toLowerCase()) {
        case "critical": return "sev-critical";
        case "major": return "sev-major";
        case "moderate": return "sev-moderate";
        case "minor": return "sev-minor";
        default: return "sev-none";
      }
    }
    function renderResult(res) {
      const findings = (res && res.findings) || [];
      if (sevPill) {
        const sev = (res && res.overall_severity) || "none";
        sevPill.textContent = sev.toUpperCase();
        sevPill.className = "status-pill " + severityClass(sev);
        sevPill.style.display = "";
      }
      let html = "";
      if (res && res.summary) {
        html += '<p class="mb-3 fw-semibold">' + escHtml(res.summary) + '</p>';
      }
      if (!findings.length) {
        html += '<p class="text-success small mb-3">No clinically relevant findings reported.</p>';
      }
      findings.forEach(function (f) {
        html +=
          '<div class="finding-card ' + severityClass(f.severity) + ' mb-3">' +
            '<div class="d-flex justify-content-between align-items-start mb-1">' +
              '<span class="finding-type fw-semibold">' + escHtml((f.type || "").toUpperCase()) + '</span>' +
              '<span class="badge text-bg-light">' + escHtml(f.severity || "") + ' · ' + escHtml(f.confidence || "") + '</span>' +
            '</div>' +
            (f.involves && f.involves.length
              ? '<div class="small text-muted mb-1">Involves: ' + escHtml(f.involves.join(" + ")) + '</div>'
              : '') +
            (f.mechanism ? '<div class="small mb-1"><strong>Mechanism:</strong> ' + escHtml(f.mechanism) + '</div>' : '') +
            (f.clinical_effect ? '<div class="small mb-1"><strong>Effect:</strong> ' + escHtml(f.clinical_effect) + '</div>' : '') +
            (f.recommendation ? '<div class="small mb-1"><strong>Recommendation:</strong> ' + escHtml(f.recommendation) + '</div>' : '') +
            (f.alternatives && f.alternatives.length
              ? '<div class="small mb-1"><strong>Alternatives:</strong> ' + escHtml(f.alternatives.join(", ")) + '</div>'
              : '') +
            (f.evidence_strength
              ? '<div class="small text-muted">Evidence: ' + escHtml(f.evidence_strength) + '</div>'
              : '') +
          '</div>';
      });
      resultEl.innerHTML = html;

      const unrec = (res && res.unrecognized) || [];
      if (unrec.length) {
        let u = '<div class="alert alert-warning small mb-0 mt-2"><strong>Could not identify:</strong><ul class="mb-0 ps-3">';
        unrec.forEach(function (x) {
          u += '<li><strong>' + escHtml(x.input) + '</strong> — ' + escHtml(x.reason || "") +
               (x.ask_doctor ? ' <em>(' + escHtml(x.ask_doctor) + ')</em>' : '') + '</li>';
        });
        u += '</ul></div>';
        unrecEl.innerHTML = u;
      } else {
        unrecEl.innerHTML = "";
      }

      disclaimerEl.textContent = (res && res.disclaimer) || "";
    }

    runBtn.addEventListener("click", async function () {
      const proposed = (proposedInput.value || "").trim();
      if (!proposed) {
        statusEl.textContent = "Enter the proposed medication first.";
        return;
      }
      // Flush any unsubmitted text in the chip inputs.
      if ((currentInput.value || "").trim()) addFrom(currentInput, currentMeds, currentChipsBox);
      if ((herbInput.value || "").trim()) addFrom(herbInput, herbs, herbChipsBox);

      const payload = {
        current_meds: currentMeds,
        proposed_med: proposed,
        herbs: herbs,
        patient_context: {
          age: (ageInput.value || "").trim(),
          sex: sexInput.value || "",
          conditions: (conditionsInput.value || "").split(",").map(function (s) { return s.trim(); }).filter(Boolean),
          allergies: (allergiesInput.value || "").split(",").map(function (s) { return s.trim(); }).filter(Boolean),
        },
      };

      runBtn.disabled = true;
      statusEl.textContent = "Checking…";
      if (sevPill) sevPill.style.display = "none";
      resultEl.innerHTML = "";
      unrecEl.innerHTML = "";
      disclaimerEl.textContent = "";

      let r;
      try { r = await postJSON("/scribe/api/drug-check/", payload); }
      catch (err) {
        statusEl.textContent = "Network error: " + err.message;
        runBtn.disabled = false;
        return;
      }
      runBtn.disabled = false;
      if (!r.ok || !r.body || !r.body.ok) {
        statusEl.textContent = (r.body && r.body.error) || "Check failed.";
        return;
      }
      statusEl.textContent = "Result · " + (r.body.duration_ms || 0) + " ms";
      renderResult(r.body.result || {});
    });

    initQuickEditMics(root);
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

    let waveAnimHandle = 0;
    function startWavePump(analyser) {
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

    function attachBlob(blob) {
      currentAudioBlob = blob;
      const url = URL.createObjectURL(blob);
      if (player) { player.src = url; player.classList.remove("d-none"); }
      if (audioInfo) audioInfo.textContent = "Loaded " + (blob.size / 1024 | 0) + " KB · " + (blob.type || "audio");
    }

    if (uploadBtn && fileInput) {
      uploadBtn.addEventListener("click", function () { fileInput.click(); });
      fileInput.addEventListener("change", function () {
        const f = fileInput.files && fileInput.files[0];
        if (f) attachBlob(f);
      });
    }

    // Drag + drop audio anywhere on the recorder shell (and on the upload button).
    const dropTargets = [recordBtn ? recordBtn.closest(".recorder-shell") : null, uploadBtn].filter(Boolean);
    dropTargets.forEach(function (el) {
      ["dragenter", "dragover"].forEach(function (evt) {
        el.addEventListener(evt, function (e) {
          e.preventDefault(); e.stopPropagation();
          el.classList.add("is-dropping");
        });
      });
      ["dragleave", "drop"].forEach(function (evt) {
        el.addEventListener(evt, function (e) {
          e.preventDefault(); e.stopPropagation();
          el.classList.remove("is-dropping");
        });
      });
      el.addEventListener("drop", function (e) {
        const f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
        if (!f) return;
        // Accept anything audio-ish (mp3, mp4, m4a, wav, ogg, webm, video/* with audio).
        const ok = /^(audio|video)\//.test(f.type) || /\.(mp3|mp4|m4a|wav|ogg|webm|aac|flac)$/i.test(f.name);
        if (!ok) { showToast("That file type isn't supported"); return; }
        attachBlob(f);
        showToast("Loaded " + f.name);
      });
    });

    if (recordBtn) recordBtn.addEventListener("click", async function () {
      if (recordBtn.classList.contains("is-recording")) {
        if (recState.rec && recState.rec.state !== "inactive") recState.rec.stop();
        clearInterval(recState.ts);
        if (recState.stream) recState.stream.getTracks().forEach(function (t) { t.stop(); });
        if (recState.ctx && recState.ctx.state !== "closed") {
          try { recState.ctx.close(); } catch (e) { /* noop */ }
        }
        stopWavePump();
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

      // Wire AudioContext + analyser so the waveform actually pumps.
      try {
        recState.ctx = new (window.AudioContext || window.webkitAudioContext)();
        const source = recState.ctx.createMediaStreamSource(recState.stream);
        const analyser = recState.ctx.createAnalyser();
        analyser.fftSize = 256;
        source.connect(analyser);
        startWavePump(analyser);
      } catch (err) {
        // AudioContext may be blocked; recording still works, no waveform.
      }

      recState.started = Date.now();
      recState.ts = setInterval(function () {
        if (timer) timer.textContent = fmtTime((Date.now() - recState.started) / 1000);
      }, 250);
      recordBtn.classList.add("is-recording");
      recordBtn.querySelector("[data-record-label]").textContent = "Stop";
    });

    // Backend dropdown reveals the relevant model_id row (omni only — Gemma
    // lives in section 4 now as an interpreter choice).
    const omniRow = $("#triageOmniRow", root);
    const modelIdInput = $("#triageModelId", root);
    const gemmaModelIdInput = $("#triageGemmaModelId", root);  // section 4
    function syncBackendRows() {
      const v = backendSel.value;
      if (omniRow) omniRow.style.display = v === "omni" ? "block" : "none";
    }
    if (backendSel) backendSel.addEventListener("change", syncBackendRows);
    syncBackendRows();

    // Denoise / diarize toggles + speakers — read at submit time.
    const denoiseChk = $("#triageDenoise", root);
    const diarizeChk = $("#triageDiarize", root);
    const numSpeakersInp = $("#triageNumSpeakers", root);

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
        const result = job.result || {};
        rawOut.value = result.raw_text || "";
        autoGrowAny(rawOut);
        const extras = [];
        if (result.denoise_applied) extras.push("denoised");
        if (result.diarize_applied) extras.push("diarized (" + (result.diarize_segments || []).length + " segments)");
        if (result.audio_saved_as) extras.push("saved " + result.audio_saved_as);
        if (timings) {
          timings.textContent = job.backend + " · " + job.device + " · " + job.elapsed_ms + " ms"
            + (extras.length ? " · " + extras.join(" · ") : "");
        }
        // Diarize panel — only shows when the run actually produced labels.
        const diarWrap = $("#triageDiarizedWrap", root);
        const diarOut = $("#triageDiarizedOut", root);
        if (diarWrap && diarOut) {
          if (result.diarize_applied && result.diarized_text) {
            diarOut.value = result.diarized_text;
            diarWrap.classList.remove("d-none");
            if (typeof autoGrowAny === "function") autoGrowAny(diarOut);
          } else if (diarizeChk && diarizeChk.checked && !result.diarize_applied) {
            // Toggle was on but no labels came back — likely lib not installed.
            diarOut.value = "[diarization did not run] No speaker labels returned. "
              + "Check the env probe — pyannote.audio or the 'diarize' lib must be "
              + "installed. Click 'Install diarize' in the audio-libs panel on the right.";
            diarWrap.classList.remove("d-none");
            showToast("Diarize toggle was on but no segments returned — see panel.");
          } else {
            diarWrap.classList.add("d-none");
          }
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

    function buildRunForm() {
      const fd = new FormData();
      fd.append("backend", backendSel.value);
      fd.append("device", deviceSel.value);
      fd.append("target_lang", langInput.value || "jam");
      fd.append("text_input", textIn.value || "");
      if (modelIdInput) fd.append("model_id", modelIdInput.value || "facebook/omnilingual-asr-7b-ctc");
      if (denoiseChk && denoiseChk.checked) fd.append("denoise", "1");
      if (diarizeChk && diarizeChk.checked) fd.append("diarize", "1");
      if (numSpeakersInp) fd.append("num_speakers", numSpeakersInp.value || "2");
      if (currentAudioBlob) {
        const ext = currentAudioBlob.type.indexOf("ogg") >= 0 ? "ogg" :
                    (currentAudioBlob.type.indexOf("mpeg") >= 0 ? "mp3" : "webm");
        fd.append("audio", currentAudioBlob, "triage." + ext);
      }
      return fd;
    }

    if (runBtn) runBtn.addEventListener("click", async function () {
      const fd = buildRunForm();
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

    // Section 4 — interpreter choice (Azure cloud vs Gemma local).
    const interpreterSel = $("#triageInterpreter", root);
    const interpreterDeviceSel = $("#triageInterpreterDevice", root);

    function buildInterpretPayload(textOverride) {
      const text = (textOverride || rawOut.value || textIn.value || "").trim();
      return {
        text: text,
        interpreter: (interpreterSel && interpreterSel.value) || "azure",
        device: (interpreterDeviceSel && interpreterDeviceSel.value) || "cpu",
        gemma_model_id: (gemmaModelIdInput && gemmaModelIdInput.value) || "Qwen/Qwen3-1.7B",
      };
    }

    if (interpretBtn) interpretBtn.addEventListener("click", async function () {
      const payload = buildInterpretPayload();
      if (!payload.text) { showToast("Run a backend first or paste raw text."); return; }
      interpretBtn.disabled = true;
      const orig = interpretBtn.innerHTML;
      const stageLabel = payload.interpreter === "gemma_local"
        ? "Gemma — first run is ~60–120s cold start"
        : "Azure cloud LLM";
      interpretBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> Interpreting (' + stageLabel + ')…';
      let r;
      try { r = await postJSON("/scribe/api/triage/interpret/", payload); }
      catch (err) { interpretBtn.disabled = false; interpretBtn.innerHTML = orig; showToast("Network error"); return; }
      interpretBtn.disabled = false;
      interpretBtn.innerHTML = orig;
      if (!r.ok || !r.body || !r.body.ok) {
        showToast((r.body && r.body.error) || "Interpretation failed.");
        return;
      }
      cleanOut.value = r.body.clean_text || "";
      autoGrowAny(cleanOut);
      // Show timing under the box.
      if (timings && r.body.duration_ms != null) {
        const tag = (r.body.interpreter || "azure") + (r.body.device ? " · " + r.body.device : "");
        timings.textContent = "interpret: " + tag + " · " + r.body.duration_ms + " ms";
      }
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

    // ---- Audio-libs install (denoise + diarize) ----
    const installAudioStatus = $("#installAudioStatus", root);
    const audioBtnIds = ["#installDenoiseBtn", "#installDiarizeBtn", "#installAudioBothBtn"];
    const audioBtns = audioBtnIds.map(function (sel) { return $(sel, root); }).filter(Boolean);

    async function startAudioInstall(target) {
      const btn = target === "denoise" ? $("#installDenoiseBtn", root) :
                  target === "diarize" ? $("#installDiarizeBtn", root) :
                  $("#installAudioBothBtn", root);
      const origs = audioBtns.map(function (b) { return [b, b.innerHTML]; });
      audioBtns.forEach(function (b) { b.disabled = true; });
      if (btn) btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> Installing…';
      if (installAudioStatus) installAudioStatus.textContent = "Starting pip install (" + target + ")…";

      let r;
      try {
        r = await postJSON("/scribe/api/triage/install-audio/", { target: target });
      } catch (err) {
        origs.forEach(function (pair) { pair[0].disabled = false; pair[0].innerHTML = pair[1]; });
        if (installAudioStatus) installAudioStatus.textContent = "Network error: " + err.message;
        return;
      }
      if (!r.ok || !r.body || !r.body.ok) {
        origs.forEach(function (pair) { pair[0].disabled = false; pair[0].innerHTML = pair[1]; });
        if (installAudioStatus) installAudioStatus.textContent = (r.body && r.body.error) || "Install did not start.";
        return;
      }
      const startedAt = Date.now();
      if (installAudioStatus) {
        installAudioStatus.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> '
          + "Installing " + (r.body.packages || []).join(", ")
          + ". Toggle denoise/diarize on the next run once installed. Elapsed: 0s";
      }
      const t = setInterval(function () {
        const elapsed = Math.round((Date.now() - startedAt) / 1000);
        if (installAudioStatus) {
          installAudioStatus.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> '
            + "Installing in background. Elapsed: " + elapsed + "s.";
        }
        // Stop after 4 min — keep buttons re-enabled so user can retry.
        if (elapsed > 240) {
          clearInterval(t);
          origs.forEach(function (pair) { pair[0].disabled = false; pair[0].innerHTML = pair[1]; });
          if (installAudioStatus) {
            installAudioStatus.innerHTML = '<span class="text-success">Install probably finished. '
              + 'Try the toggle on the next run; reinstall if it still says "not installed".</span>';
          }
        }
      }, 5000);
    }
    window.WELLNEST_triage_install_audio = startAudioInstall;

    // ---- Conversation mode ----
    // Single record button. Runs the full pipeline end-to-end with the
    // toggles + backend chosen below. Only the final clinical English is
    // shown, plus an elapsed counter so the doctor can feel the latency.
    const convoToggle = $("#triageConversationMode", root);
    const convoPanel = $("#triageConversationPanel", root);
    const stepwise = $("#triageStepwise", root);
    const convoRecordBtn = $("#convoRecordBtn", root);
    const convoTimerEl = $("#convoTimer", root);
    const convoStageEl = $("#convoStage", root);
    const convoFinalOut = $("#convoFinalOut", root);
    const convoTimingsEl = $("#convoTimings", root);
    const clinicalOnlyToggle = $("#convoClinicalOnlyToggle", root);
    const convoModeDesc = $("#convoModeDesc", root);

    function syncConvoVisibility() {
      const on = !!(convoToggle && convoToggle.checked);
      if (convoPanel) convoPanel.style.display = on ? "block" : "none";
      if (stepwise) stepwise.style.display = on ? "none" : "";
    }
    if (convoToggle) convoToggle.addEventListener("change", syncConvoVisibility);
    syncConvoVisibility();

    function syncClinicalOnlyMode() {
      const on = !!(clinicalOnlyToggle && clinicalOnlyToggle.checked);
      if (convoModeDesc) convoModeDesc.style.display = on ? "none" : "";
      if (convoStageEl) convoStageEl.style.display = on ? "none" : "";
      if (convoTimingsEl) convoTimingsEl.style.display = on ? "none" : "";
      if (convoDemoCard) convoDemoCard.style.display = on ? "none" : "";
      if (convoFinalOut) autoGrow(convoFinalOut);
    }
    if (clinicalOnlyToggle) clinicalOnlyToggle.addEventListener("change", syncClinicalOnlyMode);

    initMicSettings($("#triageConversationPanel", root) || root);

    if (convoFinalOut) {
      autoGrow(convoFinalOut);
      convoFinalOut.addEventListener("input", function () { autoGrow(convoFinalOut); });
    }

    const convoProgressWrap = $("#convoProgressWrap", root);
    const convoProgressBar = $("#convoProgressBar", root);
    const convoProgressLabel = $("#convoProgressLabel", root);

    let convoRecState = { rec: null, stream: null, started: 0, ts: 0, chunks: [] };
    let convoBlob = null;
    let convoPollTimer = 0;

    function extractClinicalSummary(text) {
      if (!text) return text;
      const match = text.match(/\*{0,2}clinical summary:?\*{0,2}\s*/i);
      if (!match) return text;
      return text.slice(match.index + match[0].length).trim();
    }

    function setConvoProgress(pct, label) {
      if (convoProgressWrap) convoProgressWrap.style.display = pct > 0 ? "" : "none";
      if (convoProgressBar) {
        convoProgressBar.style.width = pct + "%";
        convoProgressBar.setAttribute("aria-valuenow", String(pct));
      }
      if (convoProgressLabel) convoProgressLabel.textContent = label || "";
    }

    function setConvoStage(text, kind) {
      if (!convoStageEl) return;
      convoStageEl.classList.remove("text-danger");
      if (kind === "error") {
        convoStageEl.textContent = text;
        convoStageEl.style.display = "";
        convoStageEl.classList.add("text-danger");
        setConvoProgress(0, "");
      } else if (kind === "success") {
        convoStageEl.style.display = "none";
        setConvoProgress(100, "Done");
        setTimeout(function () { setConvoProgress(0, ""); }, 1500);
      } else {
        convoStageEl.style.display = "none";
      }
    }

    function resetConvoBtn() {
      if (!convoRecordBtn) return;
      convoRecordBtn.classList.remove("is-recording");
      const lbl = convoRecordBtn.querySelector("[data-record-label]");
      if (lbl) lbl.textContent = "Talk";
    }

    async function pollConvoJob(jobId, startMs) {
      try {
        const res = await fetch("/scribe/api/triage/jobs/" + jobId + "/", { credentials: "same-origin" });
        const j = await res.json();
        if (!j.ok) { clearInterval(convoPollTimer); setConvoStage(j.error || "poll failed", "error"); return; }
        const job = j.job;
        const elapsed = Date.now() - startMs;
        if (job.status === "running" || job.status === "pending") {
          setConvoProgress(Math.min(30 + Math.floor(elapsed / 2000) * 5, 72), "Processing…");
          return;
        }
        clearInterval(convoPollTimer);
        if (job.status === "error") {
          setConvoStage("error: " + (job.error || "unknown"), "error");
          return;
        }
        const raw = (job.result && job.result.raw_text) || "";
        // Pipe raw output → cloud interpret automatically.
        setConvoProgress(82, "Processing…");
        let r2;
        try {
          r2 = await postJSON("/scribe/api/triage/interpret/", buildInterpretPayload(raw));
        } catch (err) { setConvoStage("network error: " + err.message, "error"); return; }
        const finalText = (r2.body && r2.body.ok) ? (r2.body.clean_text || "") : raw;
        if (convoFinalOut) {
          convoFinalOut.value = extractClinicalSummary(finalText || raw);
          autoGrow(convoFinalOut);
        }
        const total = Date.now() - startMs;
        if (convoTimingsEl) {
          convoTimingsEl.textContent = job.backend + " · " + job.device + " · total " + fmtElapsed(total);
        }
        setConvoStage("done", "success");
        // Kick off demographics extraction on whatever the doctor sees in the
        // final output. Best-effort: failures stay quiet, panel just doesn't show.
        runConvoDemographics(finalText || raw);
      } catch (err) { /* keep polling */ }
    }

    // ---- Conversation-mode demographics panel ----
    const convoDemoCard = $("#convoDemographicsCard", root);
    const convoDemoStatus = $("#convoDemoStatus", root);
    const convoDemoReRun = $("#convoDemoReRun", root);

    function getNested(obj, path) {
      const parts = path.split(".");
      let cur = obj;
      for (let i = 0; i < parts.length; i++) {
        if (cur == null) return "";
        cur = cur[parts[i]];
      }
      return cur == null ? "" : cur;
    }
    function applyDemographics(data) {
      if (!convoDemoCard) return;
      // Only fill BLANK fields — never overwrite what the nurse already
      // typed/dictated. The AI is a fallback, not the source of truth.
      $$("[data-demo]", convoDemoCard).forEach(function (el) {
        if ((el.value || "").trim()) return;
        el.value = String(getNested(data, el.getAttribute("data-demo")) || "");
      });
      $$("[data-demo-list]", convoDemoCard).forEach(function (el) {
        if ((el.value || "").trim()) return;
        const k = el.getAttribute("data-demo-list");
        const arr = Array.isArray(data[k]) ? data[k] : [];
        el.value = arr.join(", ");
      });
    }
    let convoDemoMicsBound = false;
    // Wire field-level mics up front so the nurse can dictate INTO the
    // demographics fields while talking to the patient — not just after
    // the pipeline runs. initQuickEditMics is idempotent over per-button
    // listeners (each button only ever gets one).
    if (convoDemoCard && !convoDemoMicsBound) {
      initQuickEditMics(convoDemoCard);
      convoDemoMicsBound = true;
      if (convoDemoStatus) {
        convoDemoStatus.textContent = "Type or use the mic on any field. AI fills the blanks when the pipeline finishes.";
      }
    }
    async function runConvoDemographics(text) {
      if (!convoDemoCard || !text || !text.trim()) return;
      if (convoDemoStatus) convoDemoStatus.textContent = "Extracting demographics…";
      let r;
      try {
        r = await postJSON("/scribe/api/triage/extract-demographics/", { text: text });
      } catch (err) {
        if (convoDemoStatus) convoDemoStatus.textContent = "Could not extract: " + err.message;
        return;
      }
      if (!r.ok || !r.body || !r.body.ok) {
        if (convoDemoStatus) convoDemoStatus.textContent = (r.body && r.body.error) || "Extraction failed.";
        return;
      }
      applyDemographics(r.body.data || {});
      if (convoDemoStatus) {
        convoDemoStatus.textContent = "AI filled the blank fields. Anything you'd typed first stayed put. Edit or dictate corrections freely.";
      }
    }
    if (convoDemoReRun) {
      convoDemoReRun.addEventListener("click", function () {
        const txt = convoFinalOut ? convoFinalOut.value : "";
        runConvoDemographics(txt);
      });
    }

    async function startConvoRun() {
      const fd = buildRunForm();
      // Replace audio with the conversation blob.
      if (convoBlob) {
        fd.delete("audio");
        const ext = convoBlob.type.indexOf("ogg") >= 0 ? "ogg" :
                    (convoBlob.type.indexOf("mpeg") >= 0 ? "mp3" : "webm");
        fd.set("audio", convoBlob, "convo." + ext);
      }
      setConvoProgress(15, "Processing…");
      let r;
      try { r = await postForm("/scribe/api/triage/run/", fd); }
      catch (err) { setConvoStage("network error: " + err.message, "error"); return; }
      if (!r.ok || !r.body || !r.body.ok) {
        setConvoStage((r.body && r.body.error) || "could not start", "error");
        return;
      }
      const jobId = r.body.job_id;
      const startMs = Date.now();
      pollConvoJob(jobId, startMs);
      clearInterval(convoPollTimer);
      convoPollTimer = setInterval(function () { pollConvoJob(jobId, startMs); }, 2000);
    }

    if (convoRecordBtn) convoRecordBtn.addEventListener("click", async function () {
      if (convoRecordBtn.classList.contains("is-recording")) {
        if (convoRecState.rec && convoRecState.rec.state !== "inactive") convoRecState.rec.stop();
        clearInterval(convoRecState.ts);
        if (convoRecState.stream) convoRecState.stream.getTracks().forEach(function (t) { t.stop(); });
        resetConvoBtn();
        return;
      }
      try {
        convoRecState.stream = await navigator.mediaDevices.getUserMedia({ audio: getMicConstraint() });
      } catch (err) {
        if (err.name === "OverconstrainedError" || err.name === "NotFoundError") {
          localStorage.removeItem(MIC_LS_KEY);
          try { convoRecState.stream = await navigator.mediaDevices.getUserMedia({ audio: true }); }
          catch (err2) { setConvoStage("microphone permission denied", "error"); return; }
        } else { setConvoStage("microphone permission denied", "error"); return; }
      }
      const mime = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
        ? "audio/webm;codecs=opus" : "";
      convoRecState.chunks = [];
      convoRecState.rec = mime
        ? new MediaRecorder(convoRecState.stream, { mimeType: mime })
        : new MediaRecorder(convoRecState.stream);
      convoRecState.rec.ondataavailable = function (e) {
        if (e.data && e.data.size > 0) convoRecState.chunks.push(e.data);
      };
      convoRecState.rec.onstop = async function () {
        convoBlob = new Blob(convoRecState.chunks, { type: convoRecState.chunks[0]?.type || "audio/webm" });
        await startConvoRun();
      };
      convoRecState.rec.start(250);
      convoRecState.started = Date.now();
      convoRecState.ts = setInterval(function () {
        if (convoTimerEl) convoTimerEl.textContent = fmtTime((Date.now() - convoRecState.started) / 1000);
      }, 250);
      convoRecordBtn.classList.add("is-recording");
      const lbl = convoRecordBtn.querySelector("[data-record-label]");
      if (lbl) lbl.textContent = "Stop";
      setConvoProgress(5, "Recording…");
    });
  }

  // ---------- review screen ----------
  // NB: invocation is moved to AFTER the NATVNS option-list `const`s further
  // below — otherwise initBodyDiagram() hits a TDZ ReferenceError on
  // WOUND_TYPES the first time the review screen renders.
  const reviewRoot = document.querySelector("[data-screen='review']");

  function initReviewScreen(root) {
    const sessionId = root.getAttribute("data-session-id");
    const isFinalized = root.getAttribute("data-finalized") === "1";
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

    function renderBodyMarkers() {
      // Read saved body markers + wound_chart from the json_script blocks
      // and produce a plain-text summary that can be appended to the note
      // when copying / sharing / printing.
      try {
        const mEl = document.getElementById("bodyMarkersData");
        const cEl = document.getElementById("woundChartData");
        const markers = mEl && mEl.textContent.trim() ? JSON.parse(mEl.textContent) : [];
        const chart = cEl && cEl.textContent.trim() ? JSON.parse(cEl.textContent) : {};
        const lines = [];
        const factors = (chart && chart.factors_delaying_healing) || [];
        if (factors.length) {
          lines.push("Factors delaying healing: " + factors.join(", ").replace(/_/g, " ") + ".");
        }
        if (Array.isArray(markers) && markers.length) {
          markers.forEach(function (m, idx) {
            const seg = ["Wound #" + (idx + 1) + (m.date_added ? " (" + m.date_added + ")" : "")];
            const detail = [];
            if (m.wound_type) detail.push(m.wound_type.replace(/_/g, " "));
            if (m.duration) detail.push("dur " + m.duration);
            const dims = [m.length_cm, m.width_cm, m.depth_cm].filter(Boolean).join("x");
            if (dims) detail.push(dims + " cm");
            if (m.tracking_cm) detail.push("tracking " + m.tracking_cm + " cm");
            if (m.exudate || m.exudate_type) {
              detail.push("exudate " + [m.exudate, m.exudate_type].filter(Boolean).join("/"));
            }
            if (Array.isArray(m.peri_wound) && m.peri_wound.length) {
              detail.push("peri-wound: " + m.peri_wound.join(", ").replace(/_/g, " "));
            }
            if (Array.isArray(m.infection_signs) && m.infection_signs.length) {
              detail.push("infection: " + m.infection_signs.join(", ").replace(/_/g, " "));
            }
            if (m.treatment_goal) detail.push("goal: " + m.treatment_goal.replace(/_/g, " "));
            if (m.analgesia && m.analgesia !== "none") detail.push("analgesia: " + m.analgesia.replace(/_/g, " "));
            if (m.referred_to) detail.push("ref: " + m.referred_to);
            if (m.notes) detail.push("notes: " + m.notes);
            seg.push("  " + detail.join(" · "));
            lines.push(seg.join("\n"));
          });
        }
        return lines.length ? "WOUND CHART:\n" + lines.join("\n") : "";
      } catch (e) { return ""; }
    }

    function renderFromFields(p) {
      let body;
      if (p.narrative) {
        body = p.narrative;
      } else {
        const parts = [];
        if (p.subjective) parts.push("S:\n" + p.subjective);
        if (p.objective) parts.push("O:\n" + p.objective);
        if (p.assessment) parts.push("A:\n" + p.assessment);
        if (p.plan) parts.push("P:\n" + p.plan);
        body = parts.join("\n\n");
      }
      const wound = renderBodyMarkers();
      return wound ? body + "\n\n" + wound : body;
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
      if (!fullNoteArea.dataset.manualEdit) {
        fullNoteArea.value = generated;
        autoGrow(fullNoteArea);
      }
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
        if (k in parsed && parsed[k]) {
          el.value = parsed[k];
          autoGrow(el);
        }
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
      if (isFinalized) return;  // session is locked — never POST edits
      const r = await postJSON("/scribe/api/sessions/" + sessionId + "/save/", collectPayload());
      if (r.ok && r.body.ok) setStatus(statusEl, "Saved", "success");
      else setStatus(statusEl, "Save failed", "error");
    }

    // Belt-and-braces: when the note is finalized, programmatically lock
    // every editable surface. CSS hides interaction; this prevents form
    // submission even if a clever user removes the CSS class.
    if (isFinalized) {
      if (titleEl) titleEl.setAttribute("contenteditable", "false");
      fields.forEach(function (el) { el.readOnly = true; el.disabled = true; });
      if (fullNoteArea) { fullNoteArea.readOnly = true; fullNoteArea.disabled = true; }
      if (transcriptArea) { transcriptArea.readOnly = true; transcriptArea.disabled = true; }
      [saveBtn, finalizeBtn, regenAllBtn, $("#polishBtn", root), $("#improveBtn", root),
       $("#copyAllBtn", root)].forEach(function (b) {
        if (b) b.disabled = true;
      });
      // Block any future per-marker save attempts from the body diagram.
      window.WELLNEST_finalized = true;
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
      const ok = await confirmDialog({
        title: "Mark this note as reviewed?",
        html:
          "Once reviewed, all fields lock — no further edits allowed " +
          "(including transcript, body diagram, and SOAP sections)." +
          "<br><br>Make any final tweaks first. This protects the clinical record.",
        icon: "warning",
        confirmText: "Yes, mark reviewed",
        cancelText: "Keep editing",
      });
      if (!ok) return;
      await autosave();
      const r = await postJSON("/scribe/api/sessions/" + sessionId + "/finalize/", {});
      if (r.ok && r.body.ok) {
        setStatus(statusEl, "Finalized.", "success");
        showToast("Note marked reviewed — page will reload locked.");
        setTimeout(function () { window.location.reload(); }, 900);
      } else {
        setStatus(statusEl, "Could not finalize.", "error");
      }
    });
    const deleteSessionBtn = $("#deleteSessionBtn", root);
    if (deleteSessionBtn) deleteSessionBtn.addEventListener("click", async function () {
      const ok = await confirmDialog({
        title: "Delete this session permanently?",
        html:
          "This removes the <strong>audio recording, transcript, and clinical note</strong> from the system. " +
          "It cannot be undone.<br><br>" +
          "Use this when a patient exercises their <strong>right to erasure</strong> under the Data Protection Act, " +
          "or if the recording was made in error.",
        icon: "danger",
        confirmText: "Yes, delete permanently",
        cancelText: "Cancel",
      });
      if (!ok) return;
      const r = await postJSON("/scribe/api/sessions/" + sessionId + "/delete/", {});
      if (r.ok && r.body.ok) {
        showToast("Session deleted.");
        setTimeout(function () { window.location.href = r.body.redirect || "/scribe/sessions/"; }, 700);
      } else {
        setStatus(statusEl, (r.body && r.body.error) || "Delete failed.", "error");
      }
    });

    if (copyBtn) copyBtn.addEventListener("click", async function () {
      await autosave();
      const text = fullNoteArea && fullNoteArea.value ? fullNoteArea.value : renderFromFields(collectFieldValues());
      const disclaimer = "\n\n---\nGenerated by WellNest Scribe AI — clinician review required before use in medical records.";
      try { await navigator.clipboard.writeText(text + disclaimer); showToast("Copied to clipboard"); }
      catch (err) { setStatus(statusEl, "Copy failed", "error"); }
    });

    // ── "Copy all" button in the Freed-style copy-all bar ──
    const copyAllBtn = $("#copyAllBtn", root);
    if (copyAllBtn) {
      copyAllBtn.addEventListener("click", async function () {
        await autosave();
        const text = fullNoteArea && fullNoteArea.value
          ? fullNoteArea.value
          : renderFromFields(collectFieldValues());
        const disclaimer = "\n\n---\nGenerated by WellNest Scribe AI — clinician review required before use in medical records.";
        try {
          await navigator.clipboard.writeText(text + disclaimer);
          copyAllBtn.innerHTML = '<iconify-icon icon="iconamoon:check-circle-1-duotone" class="me-1 align-middle"></iconify-icon>Copied!';
          setTimeout(function () {
            copyAllBtn.innerHTML = '<iconify-icon icon="iconamoon:copy-duotone" class="me-1 align-middle"></iconify-icon>Copy all';
          }, 2000);
        } catch (err) { setStatus(statusEl, "Copy failed", "error"); }
      });
    }

    // ── Per-section copy buttons ──
    $$("[data-copy-section]", root).forEach(function (btn) {
      btn.addEventListener("click", function (e) {
        e.stopPropagation();
        const sectionId = btn.getAttribute("data-copy-section");
        const ta = $("[data-note-field='" + sectionId + "']", root);
        if (!ta || !ta.value.trim()) { showToast("Section is empty"); return; }
        navigator.clipboard.writeText(ta.value.trim())
          .then(function () {
            const origIcon = btn.innerHTML;
            btn.innerHTML = '<iconify-icon icon="iconamoon:check-circle-1-duotone"></iconify-icon>';
            setTimeout(function () { btn.innerHTML = origIcon; }, 1800);
            showToast("Section copied");
          })
          .catch(function () { showToast("Copy failed"); });
      });
    });

    // ── Thumbs up / down per section (visual feedback only) ──
    $$("[data-thumb]", root).forEach(function (btn) {
      btn.addEventListener("click", function (e) {
        e.stopPropagation();
        const dir = btn.getAttribute("data-thumb");
        const sectionId = btn.getAttribute("data-section");
        const section = $("[data-section-id='" + sectionId + "']", root)
                     || btn.closest(".note-section");
        if (!section) return;
        const upBtn = $("[data-thumb='up'][data-section='" + sectionId + "']", root);
        const downBtn = $("[data-thumb='down'][data-section='" + sectionId + "']", root);
        const wasActive = btn.classList.contains("is-positive") || btn.classList.contains("is-negative");
        if (upBtn) upBtn.classList.remove("is-positive");
        if (downBtn) downBtn.classList.remove("is-negative");
        if (!wasActive) {
          if (dir === "up") { btn.classList.add("is-positive"); showToast("Marked — well captured"); }
          else { btn.classList.add("is-negative"); showToast("Marked — needs improvement"); }
        }
      });
    });

    // ── Section collapse / expand ──
    const COLLAPSE_LS_KEY = "wn_review_collapsed_" + sessionId;
    function getCollapsed() {
      try { return JSON.parse(localStorage.getItem(COLLAPSE_LS_KEY) || "[]"); } catch (e) { return []; }
    }
    function saveCollapsed(list) {
      try { localStorage.setItem(COLLAPSE_LS_KEY, JSON.stringify(list)); } catch (e) {}
    }
    function applyCollapseState() {
      const collapsed = getCollapsed();
      $$(".note-section[data-section-id]", root).forEach(function (sec) {
        const id = sec.getAttribute("data-section-id");
        sec.classList.toggle("is-collapsed", collapsed.indexOf(id) >= 0);
      });
    }
    $$(".note-section-collapse-trigger", root).forEach(function (trigger) {
      trigger.addEventListener("click", function (e) {
        const sec = trigger.closest(".note-section");
        if (!sec) return;
        const id = sec.getAttribute("data-section-id");
        sec.classList.toggle("is-collapsed");
        const collapsed = getCollapsed();
        const idx = collapsed.indexOf(id);
        if (sec.classList.contains("is-collapsed")) {
          if (idx < 0) collapsed.push(id);
        } else {
          if (idx >= 0) collapsed.splice(idx, 1);
        }
        saveCollapsed(collapsed);
      });
    });
    applyCollapseState();
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
    function attachAutoGrow(el) {
      autoGrow(el);
      el.addEventListener("input", function () { autoGrow(el); });
    }
    $$("textarea", root).forEach(attachAutoGrow);

    initQuickEditMics(root);
    initBodyDiagram(root, sessionId);
    updateWordCount();
  }

  // ---------- body diagram ----------
  // NATVNS option lists used by the per-marker wound cards.
  const WOUND_TYPES = [
    ["", "—"],
    ["leg_ulcer", "Leg ulcer"],
    ["surgical", "Surgical"],
    ["diabetic", "Diabetic ulcer"],
    ["pressure", "Pressure ulcer"],
    ["other", "Other"],
  ];
  const EXUDATE_LEVELS = [
    ["", "—"], ["dry", "Dry / moist"], ["wet", "Wet"], ["saturated", "Saturated / leaking *"],
  ];
  const EXUDATE_TYPES = [
    ["", "—"], ["serous", "Serous (straw)"], ["haemoserous", "Haemoserous"],
    ["cloudy", "Cloudy / milky"], ["green_brown", "Green / brown *"],
  ];
  const PERI_WOUND = [
    ["macerated", "Macerated"], ["oedematous", "Oedematous *"],
    ["erythema", "Erythema *"], ["excoriated", "Excoriated"],
    ["fragile", "Fragile"], ["dry_scaly", "Dry / scaly"], ["healthy", "Healthy / intact"],
  ];
  const INFECTION_SIGNS = [
    ["heat", "Heat *"], ["new_slough", "New slough / necrosis *"],
    ["increasing_pain", "↑ Pain *"], ["increasing_exudate", "↑ Exudate *"],
    ["increasing_odour", "↑ Odour *"], ["friable", "Friable granulation *"],
  ];
  const TREATMENT_GOALS = [
    ["", "—"], ["debridement", "Debridement"], ["absorption", "Absorption"],
    ["hydration", "Hydration"], ["protection", "Protect / promote healing"],
    ["palliative", "Palliative / conservative"], ["reduce_bacterial_load", "Reduce bacterial load"],
  ];

  // Now safe to boot the review screen — all NATVNS option lists exist.
  if (reviewRoot) initReviewScreen(reviewRoot);

  function initBodyDiagram(root, sessionId) {
    const overlay = $("#bodyDiagramOverlay", root);
    const cardsWrap = $("#bodyMarkerCards", root);
    const counter = $("#bodyMarkerCount", root);
    const clearAllBtn = $("#bodyClearAllBtn", root);
    const factorsBox = $("#healingFactors", root);
    if (!overlay || !cardsWrap) return;

    // Load saved state from <script type="application/json"> tags injected by
    // the template's json_script filter. This is the safe way to embed
    // server-side JSON into a page — handles apostrophes / quotes / unicode.
    let markers = [];
    try {
      const el = document.getElementById("bodyMarkersData");
      if (el && el.textContent.trim()) {
        const parsed = JSON.parse(el.textContent);
        if (Array.isArray(parsed)) markers = parsed;
      }
    } catch (e) { markers = []; }

    let factors = [];
    try {
      const el = document.getElementById("woundChartData");
      if (el && el.textContent.trim()) {
        const chart = JSON.parse(el.textContent) || {};
        if (Array.isArray(chart.factors_delaying_healing)) {
          factors = chart.factors_delaying_healing;
        }
      }
    } catch (e) { factors = []; }

    // Pre-check the healing-factor pills from saved chart state.
    if (factorsBox && factors.length) {
      factorsBox.querySelectorAll('input[type="checkbox"]').forEach(function (cb) {
        if (factors.indexOf(cb.value) >= 0) cb.checked = true;
      });
    }

    let saveTimer = 0;
    function persist() {
      // Mirror current state back into the json_script blocks so the
      // export helper (renderBodyMarkers) always reads the latest values
      // without a page reload.
      try {
        const mEl = document.getElementById("bodyMarkersData");
        const cEl = document.getElementById("woundChartData");
        if (mEl) mEl.textContent = JSON.stringify(markers);
        if (cEl) cEl.textContent = JSON.stringify({ factors_delaying_healing: factors });
      } catch (e) { /* no-op */ }
      if (window.WELLNEST_finalized) return;  // locked — don't POST edits
      clearTimeout(saveTimer);
      saveTimer = setTimeout(function () {
        postJSON("/scribe/api/sessions/" + sessionId + "/save/", {
          body_markers: markers,
          wound_chart: { factors_delaying_healing: factors },
        });
      }, 600);
    }

    function escAttr(s) { return String(s || "").replace(/"/g, "&quot;"); }
    function optionsHtml(opts, selected) {
      return opts.map(function (o) {
        const sel = o[0] === (selected || "") ? " selected" : "";
        return '<option value="' + escAttr(o[0]) + '"' + sel + '>' + o[1] + '</option>';
      }).join("");
    }
    function checkboxRow(name, opts, currentList) {
      const cur = Array.isArray(currentList) ? currentList : [];
      return opts.map(function (o) {
        const checked = cur.indexOf(o[0]) >= 0 ? " checked" : "";
        return '<label class="quick-pill" style="font-size:0.78rem;padding:4px 9px;">' +
          '<input type="checkbox" data-bm-list="' + name + '" value="' + escAttr(o[0]) + '" hidden' + checked + '> ' +
          o[1] + '</label>';
      }).join(" ");
    }

    function renderMarkers() {
      overlay.querySelectorAll(".body-marker").forEach(function (el) { el.remove(); });
      markers.forEach(function (m, idx) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "body-marker";
        btn.style.left = m.x + "%";
        btn.style.top = m.y + "%";
        btn.textContent = String(idx + 1);
        const tipParts = [];
        if (m.wound_type) tipParts.push(m.wound_type.replace(/_/g, " "));
        if (m.length_cm || m.width_cm) tipParts.push((m.length_cm || "?") + "×" + (m.width_cm || "?") + " cm");
        btn.setAttribute("data-label", tipParts.join(" · ") || "marker");
        btn.addEventListener("contextmenu", function (e) {
          e.preventDefault();
          markers.splice(idx, 1);
          renderAll(); persist();
        });
        btn.addEventListener("click", function (e) {
          e.stopPropagation();
          const card = cardsWrap.querySelector('[data-marker-card="' + idx + '"]');
          if (card) {
            card.scrollIntoView({ behavior: "smooth", block: "center" });
            const inp = card.querySelector("select, input");
            if (inp) inp.focus();
          }
        });
        overlay.appendChild(btn);
      });
    }

    function renderCards() {
      cardsWrap.innerHTML = "";
      if (!markers.length) {
        cardsWrap.innerHTML = '<p class="text-muted small mb-0">No markers yet — click on the diagram to drop one.</p>';
        if (counter) counter.textContent = "0 markers";
        return;
      }
      markers.forEach(function (m, idx) {
        const card = document.createElement("div");
        card.className = "card";
        card.setAttribute("data-marker-card", String(idx));
        card.innerHTML =
          '<div class="card-body p-3">' +
            '<div class="d-flex align-items-center justify-content-between mb-2">' +
              '<span class="fw-semibold small">Wound #' + (idx + 1) +
                (m.date_added ? ' <span class="text-muted fw-normal">· ' + escAttr(m.date_added) + '</span>' : '') +
                '</span>' +
              '<button type="button" class="btn btn-link text-danger p-0" data-bm-del title="Delete">' +
                '<iconify-icon icon="iconamoon:trash-duotone"></iconify-icon></button>' +
            '</div>' +

            '<div class="row g-2 mb-2">' +
              '<div class="col-7"><label class="form-label small text-muted mb-1">Type</label>' +
                '<select class="form-select form-select-sm" data-bm="wound_type">' + optionsHtml(WOUND_TYPES, m.wound_type) + '</select></div>' +
              '<div class="col-5"><label class="form-label small text-muted mb-1">Duration</label>' +
                '<input type="text" class="form-control form-control-sm" data-bm="duration" placeholder="3 weeks" value="' + escAttr(m.duration) + '"></div>' +
            '</div>' +

            '<div class="row g-2 mb-2">' +
              '<div class="col-3"><label class="form-label small text-muted mb-1">L (cm)</label>' +
                '<input type="text" class="form-control form-control-sm" data-bm="length_cm" value="' + escAttr(m.length_cm) + '"></div>' +
              '<div class="col-3"><label class="form-label small text-muted mb-1">W (cm)</label>' +
                '<input type="text" class="form-control form-control-sm" data-bm="width_cm" value="' + escAttr(m.width_cm) + '"></div>' +
              '<div class="col-3"><label class="form-label small text-muted mb-1">D (cm)</label>' +
                '<input type="text" class="form-control form-control-sm" data-bm="depth_cm" value="' + escAttr(m.depth_cm) + '"></div>' +
              '<div class="col-3"><label class="form-label small text-muted mb-1">Track</label>' +
                '<input type="text" class="form-control form-control-sm" data-bm="tracking_cm" value="' + escAttr(m.tracking_cm) + '"></div>' +
            '</div>' +

            '<details class="mb-2">' +
              '<summary class="small fw-semibold text-muted">Tissue type (% — total 100)</summary>' +
              '<div class="row g-2 mt-2">' +
                ['necrotic', 'slough', 'granulating', 'epithelialising', 'hypergranulating', 'haematoma', 'bone_tendon'].map(function (k) {
                  const lbl = k === 'bone_tendon' ? 'Bone/tendon' : k[0].toUpperCase() + k.slice(1);
                  return '<div class="col-6 col-md-4"><label class="form-label small text-muted mb-1">' + lbl + ' %</label>' +
                    '<input type="number" min="0" max="100" class="form-control form-control-sm" data-bm="tissue_' + k + '" value="' + escAttr(m['tissue_' + k]) + '"></div>';
                }).join("") +
              '</div>' +
            '</details>' +

            '<div class="row g-2 mb-2">' +
              '<div class="col-6"><label class="form-label small text-muted mb-1">Exudate level</label>' +
                '<select class="form-select form-select-sm" data-bm="exudate">' + optionsHtml(EXUDATE_LEVELS, m.exudate) + '</select></div>' +
              '<div class="col-6"><label class="form-label small text-muted mb-1">Exudate type</label>' +
                '<select class="form-select form-select-sm" data-bm="exudate_type">' + optionsHtml(EXUDATE_TYPES, m.exudate_type) + '</select></div>' +
            '</div>' +

            '<div class="mb-2"><label class="form-label small text-muted mb-1">Peri-wound skin</label>' +
              '<div class="quick-templates-pills">' + checkboxRow('peri_wound', PERI_WOUND, m.peri_wound) + '</div></div>' +

            '<div class="mb-2"><label class="form-label small text-muted mb-1">Signs of infection (2+ = possible infection)</label>' +
              '<div class="quick-templates-pills">' + checkboxRow('infection_signs', INFECTION_SIGNS, m.infection_signs) + '</div></div>' +

            '<div class="row g-2 mb-2">' +
              '<div class="col-7"><label class="form-label small text-muted mb-1">Treatment goal</label>' +
                '<select class="form-select form-select-sm" data-bm="treatment_goal">' + optionsHtml(TREATMENT_GOALS, m.treatment_goal) + '</select></div>' +
              '<div class="col-5"><label class="form-label small text-muted mb-1">Analgesia</label>' +
                '<select class="form-select form-select-sm" data-bm="analgesia">' +
                  optionsHtml([["", "—"], ["none", "None"], ["predressing", "Pre-dressing only"], ["regular", "Regular / ongoing"]], m.analgesia) +
                '</select></div>' +
            '</div>' +

            '<label class="form-label small text-muted mb-1">Notes</label>' +
            '<textarea class="form-control form-control-sm" rows="2" data-bm="notes">' + (m.notes ? String(m.notes).replace(/</g, "&lt;") : "") + '</textarea>' +

            '<label class="form-label small text-muted mb-1 mt-2">Referred to</label>' +
            '<input type="text" class="form-control form-control-sm" data-bm="referred_to" ' +
              'placeholder="TVN / Physio / Podiatrist / Dietician / other" value="' + escAttr(m.referred_to) + '">' +
          '</div>';

        // Wire per-field change handlers
        card.querySelectorAll("[data-bm]").forEach(function (el) {
          const key = el.getAttribute("data-bm");
          const evt = (el.tagName === "SELECT") ? "change" : "input";
          el.addEventListener(evt, function () {
            markers[idx][key] = el.value;
            persist();
            // Light tooltip refresh
            const dot = overlay.querySelectorAll(".body-marker")[idx];
            if (dot) {
              const tips = [];
              if (markers[idx].wound_type) tips.push(markers[idx].wound_type.replace(/_/g, " "));
              if (markers[idx].length_cm || markers[idx].width_cm)
                tips.push((markers[idx].length_cm || "?") + "×" + (markers[idx].width_cm || "?") + " cm");
              dot.setAttribute("data-label", tips.join(" · ") || "marker");
            }
          });
        });
        // Checkbox-list handlers
        card.querySelectorAll("[data-bm-list]").forEach(function (cb) {
          cb.addEventListener("change", function () {
            const key = cb.getAttribute("data-bm-list");
            const list = Array.from(card.querySelectorAll('[data-bm-list="' + key + '"]:checked')).map(function (c) { return c.value; });
            markers[idx][key] = list;
            persist();
          });
        });
        card.querySelector("[data-bm-del]").addEventListener("click", function () {
          markers.splice(idx, 1); renderAll(); persist();
        });
        cardsWrap.appendChild(card);
      });
      if (counter) counter.textContent = markers.length + " marker" + (markers.length === 1 ? "" : "s");
    }

    function renderAll() {
      try { renderMarkers(); }
      catch (e) { console.error("[wellnest] renderMarkers failed:", e); }
      try { renderCards(); }
      catch (e) {
        console.error("[wellnest] renderCards failed:", e);
        if (cardsWrap) {
          cardsWrap.innerHTML = '<p class="small text-danger">Could not render wound cards. ' +
            'Check the browser console for details. Marker count: ' + markers.length + '</p>';
        }
      }
    }

    overlay.addEventListener("click", function (e) {
      if (e.target !== overlay) return;
      const rect = overlay.getBoundingClientRect();
      const x = ((e.clientX - rect.left) / rect.width) * 100;
      const y = ((e.clientY - rect.top) / rect.height) * 100;
      const now = new Date();
      const isoDate = now.getFullYear() + "-" +
                      String(now.getMonth() + 1).padStart(2, "0") + "-" +
                      String(now.getDate()).padStart(2, "0");
      markers.push({ x: x, y: y, date_added: isoDate });
      renderAll();
      persist();
    });

    if (clearAllBtn) clearAllBtn.addEventListener("click", function () {
      if (!markers.length) return;
      if (!confirm("Clear all " + markers.length + " markers?")) return;
      markers = [];
      renderAll();
      persist();
    });

    if (factorsBox) {
      factorsBox.querySelectorAll('input[type="checkbox"]').forEach(function (cb) {
        cb.addEventListener("change", function () {
          factors = Array.from(factorsBox.querySelectorAll('input:checked')).map(function (c) { return c.value; });
          persist();
        });
      });
    }

    renderAll();
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
            autoGrow(target);
            target.dispatchEvent(new Event("input", { bubbles: true }));
          } else {
            target.value = baseText + interim;
            autoGrow(target);
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
            autoGrow(target);
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

  // ---------- collapsible sidebar sections ----------
  $$(".nav-section-toggle").forEach(function (toggle) {
    var section = toggle.getAttribute("data-section");
    if (!section) return;
    var content = document.getElementById(section);
    var chevron = document.getElementById(section + "-chevron");
    if (!content) return;

    function setCollapsed(collapsed, animate) {
      content.style.display = collapsed ? "none" : "";
      if (chevron) chevron.style.transform = collapsed ? "rotate(180deg)" : "";
      localStorage.setItem("nav-" + section + "-collapsed", collapsed ? "1" : "0");
    }

    var stored = localStorage.getItem("nav-" + section + "-collapsed");
    if (stored === "1") setCollapsed(true, false);

    toggle.addEventListener("click", function () {
      var collapsed = content.style.display === "none";
      setCollapsed(!collapsed, true);
    });
  });
})();
