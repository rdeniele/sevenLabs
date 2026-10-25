const $ = (selector) => document.querySelector(selector);

const state = {
  voices: [],
  history: [],
  selectedVoiceId: null,
  sampleBlob: null,
  sampleName: "recording.wav",
  recorder: null,
  mediaStream: null,
  timerId: null,
  startedAt: 0,
  generating: false,
};

const elements = {
  systemState: $("#systemState"), systemText: $("#systemText"),
  voiceList: $("#voiceList"), voiceEmpty: $("#voiceEmpty"), addVoiceButton: $("#addVoiceButton"),
  recordButton: $("#recordButton"), fileInput: $("#fileInput"), scriptInputs: [...document.querySelectorAll(".script-input")],
  modelSelect: $("#modelSelect"),
  languageSelect: $("#languageSelect"), expressionRange: $("#expressionRange"), expressionValue: $("#expressionValue"),
  fidelityRange: $("#fidelityRange"), fidelityValue: $("#fidelityValue"), consentCheckbox: $("#consentCheckbox"),
  generateButton: $("#generateButton"), generateLabel: $("#generateLabel"), generationHint: $("#generationHint"), generationProgress: $("#generationProgress"),
  progressLabel: $("#progressLabel"), progressTimer: $("#progressTimer"), errorBanner: $("#errorBanner"),
  historyList: $("#historyList"), historyEmpty: $("#historyEmpty"), voiceDialog: $("#voiceDialog"),
  voiceForm: $("#voiceForm"), dialogTitle: $("#dialogTitle"), dialogDescription: $("#dialogDescription"),
  voiceNameInput: $("#voiceNameInput"), recordingStage: $("#recordingStage"), recordingStatus: $("#recordingStatus"),
  recordingTimer: $("#recordingTimer"), samplePreview: $("#samplePreview"), voiceConsent: $("#voiceConsent"),
  dialogRecordButton: $("#dialogRecordButton"), saveVoiceButton: $("#saveVoiceButton"),
};

async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try { message = (await response.json()).detail || message; } catch {}
    throw new Error(message);
  }
  if (response.status === 204) return null;
  return response.json();
}

function formatTime(seconds) {
  const value = Math.max(0, Math.floor(seconds));
  return `${Math.floor(value / 60)}:${String(value % 60).padStart(2, "0")}`;
}

function formatDate(iso) {
  const date = new Date(iso);
  const delta = Date.now() - date.getTime();
  if (delta < 60_000) return "just now";
  if (delta < 3_600_000) return `${Math.floor(delta / 60_000)} min ago`;
  if (delta < 86_400_000) return `${Math.floor(delta / 3_600_000)} hr ago`;
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(date);
}

function showError(message) {
  elements.errorBanner.textContent = message;
  elements.errorBanner.hidden = false;
}

function clearError() { elements.errorBanner.hidden = true; }

function updateScriptStats() {
  elements.scriptInputs.forEach((input) => {
    const text = input.value;
    const words = text.trim() ? text.trim().split(/\s+/).length : 0;
    const field = input.closest(".script-field");
    field.querySelector("[data-word-count]").textContent = `${words} ${words === 1 ? "word" : "words"}`;
    field.querySelector("[data-character-count]").textContent = `${text.length.toLocaleString()} / 5,000`;
  });
  updateGenerateState();
}

function queuedScripts() {
  return elements.scriptInputs.map((input) => input.value.trim()).filter(Boolean);
}

function updateGenerateState() {
  const hasVoice = Boolean(state.selectedVoiceId);
  const scripts = queuedScripts();
  const hasText = scripts.length > 0;
  const hasConsent = elements.consentCheckbox.checked;
  elements.generateButton.disabled = state.generating || !hasVoice || !hasText || !hasConsent;
  if (scripts.length > 1) elements.generateLabel.textContent = `Generate ${scripts.length} phases`;
  else if (scripts.length === 1) elements.generateLabel.textContent = "Generate 1 phase";
  else elements.generateLabel.textContent = "Generate queued phases";

  if (state.generating) elements.generationHint.textContent = "Your queued phases will continue automatically.";
  else if (!hasVoice) elements.generationHint.textContent = "Add or select a voice sample to begin.";
  else if (!hasText) elements.generationHint.textContent = "Write a script for your voice to speak.";
  else if (!hasConsent) elements.generationHint.textContent = "Confirm permission before generating.";
  else elements.generationHint.textContent = "Ready. Your audio will stay on this machine.";
}

function renderVoices() {
  elements.voiceList.replaceChildren();
  elements.voiceEmpty.hidden = state.voices.length > 0;
  if (!state.selectedVoiceId && state.voices[0]) state.selectedVoiceId = state.voices[0].id;

  state.voices.forEach((voice) => {
    const item = $("#voiceItemTemplate").content.firstElementChild.cloneNode(true);
    item.classList.toggle("selected", voice.id === state.selectedVoiceId);
    item.querySelector("strong").textContent = voice.name;
    item.querySelector("small").textContent = `Saved ${formatDate(voice.created_at)}`;
    item.querySelector(".voice-select").addEventListener("click", () => {
      state.selectedVoiceId = voice.id;
      renderVoices();
      updateGenerateState();
    });
    item.querySelector(".item-delete").addEventListener("click", async () => {
      if (!confirm(`Delete ${voice.name}? The reference sample will be removed from this computer.`)) return;
      try {
        await api(`/api/voices/${voice.id}`, { method: "DELETE" });
        state.voices = state.voices.filter((entry) => entry.id !== voice.id);
        if (state.selectedVoiceId === voice.id) state.selectedVoiceId = state.voices[0]?.id || null;
        renderVoices(); updateGenerateState();
      } catch (error) { showError(error.message); }
    });
    elements.voiceList.append(item);
  });
}

function renderHistory() {
  elements.historyList.replaceChildren();
  elements.historyEmpty.hidden = state.history.length > 0;
  state.history.forEach((entry) => {
    const item = $("#historyItemTemplate").content.firstElementChild.cloneNode(true);
    const audio = item.querySelector("audio");
    const play = item.querySelector(".play-button");
    item.querySelector("strong").textContent = entry.voice_name;
    item.querySelector("p").textContent = entry.text;
    item.querySelector(".history-model").textContent = `${entry.model} · ${entry.duration_seconds || 0}s`;
    item.querySelector(".history-time").textContent = formatDate(entry.created_at);
    audio.src = entry.audio_url;
    play.addEventListener("click", async () => {
      document.querySelectorAll(".history-item audio").forEach((other) => { if (other !== audio) other.pause(); });
      if (audio.paused) await audio.play(); else audio.pause();
    });
    audio.addEventListener("play", () => { play.querySelector("span").textContent = "Ⅱ"; });
    audio.addEventListener("pause", () => { play.querySelector("span").textContent = "▶"; });
    audio.addEventListener("ended", () => { play.querySelector("span").textContent = "▶"; });
    const download = item.querySelector(".download-button");
    download.href = entry.download_url;
    download.download = "";
    item.querySelector(".history-delete").addEventListener("click", async () => {
      try {
        await api(`/api/history/${entry.id}`, { method: "DELETE" });
        state.history = state.history.filter((row) => row.id !== entry.id);
        renderHistory();
      } catch (error) { showError(error.message); }
    });
    elements.historyList.append(item);
  });
}

function resetVoiceDialog() {
  stopMediaTracks();
  state.sampleBlob = null;
  state.sampleName = "recording.wav";
  elements.samplePreview.hidden = true;
  elements.samplePreview.removeAttribute("src");
  elements.voiceConsent.checked = false;
  elements.saveVoiceButton.disabled = true;
  elements.recordingStage.classList.remove("recording");
  elements.recordingStatus.textContent = "Ready to record";
  elements.recordingTimer.textContent = "0:00";
  elements.dialogRecordButton.textContent = "Start recording";
  elements.voiceNameInput.value = "My voice";
}

function openRecordDialog() {
  resetVoiceDialog();
  elements.dialogTitle.textContent = "Record a sample";
  elements.dialogDescription.textContent = "Speak naturally for 10-30 seconds. Read the prompt or say anything you like.";
  elements.recordingStage.hidden = false;
  elements.dialogRecordButton.hidden = false;
  elements.voiceDialog.showModal();
}

function openUploadDialog(file) {
  resetVoiceDialog();
  state.sampleBlob = file;
  state.sampleName = file.name || "sample.wav";
  elements.dialogTitle.textContent = "Save this voice";
  elements.dialogDescription.textContent = "Name the voice and confirm you have permission to clone it.";
  elements.recordingStage.hidden = true;
  elements.dialogRecordButton.hidden = true;
  elements.samplePreview.src = URL.createObjectURL(file);
  elements.samplePreview.hidden = false;
  elements.voiceNameInput.value = file.name.replace(/\.[^.]+$/, "").slice(0, 48) || "My voice";
  elements.voiceDialog.showModal();
  updateSaveVoiceState();
}

function stopMediaTracks() {
  if (state.mediaStream) state.mediaStream.getTracks().forEach((track) => track.stop());
  state.mediaStream = null;
  if (state.timerId) clearInterval(state.timerId);
  state.timerId = null;
}

function mergeBuffers(buffers) {
  const length = buffers.reduce((total, buffer) => total + buffer.length, 0);
  const merged = new Float32Array(length);
  let offset = 0;
  buffers.forEach((buffer) => { merged.set(buffer, offset); offset += buffer.length; });
  return merged;
}

function encodeWav(samples, sampleRate) {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const write = (offset, value) => [...value].forEach((char, index) => view.setUint8(offset + index, char.charCodeAt(0)));
  write(0, "RIFF"); view.setUint32(4, 36 + samples.length * 2, true); write(8, "WAVE"); write(12, "fmt ");
  view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true); view.setUint32(28, sampleRate * 2, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
  write(36, "data"); view.setUint32(40, samples.length * 2, true);
  let offset = 44;
  samples.forEach((sample) => { const value = Math.max(-1, Math.min(1, sample)); view.setInt16(offset, value < 0 ? value * 0x8000 : value * 0x7fff, true); offset += 2; });
  return new Blob([view], { type: "audio/wav" });
}

async function toggleRecording() {
  if (state.recorder) {
    state.recorder.stop();
    return;
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
    state.mediaStream = stream;
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    const context = new AudioContextClass();
    const source = context.createMediaStreamSource(stream);
    const processor = context.createScriptProcessor(4096, 1, 1);
    const buffers = [];
    processor.onaudioprocess = (event) => buffers.push(new Float32Array(event.inputBuffer.getChannelData(0)));
    source.connect(processor); processor.connect(context.destination);
    state.startedAt = Date.now();
    state.recorder = {
      stop: async () => {
        processor.disconnect(); source.disconnect(); await context.close(); stopMediaTracks();
        const duration = (Date.now() - state.startedAt) / 1000;
        state.sampleBlob = encodeWav(mergeBuffers(buffers), context.sampleRate);
        state.sampleName = "recording.wav";
        state.recorder = null;
        elements.recordingStage.classList.remove("recording");
        elements.recordingStatus.textContent = duration < 5 ? "Short sample. 10 seconds works better." : "Sample ready";
        elements.dialogRecordButton.textContent = "Record again";
        elements.samplePreview.src = URL.createObjectURL(state.sampleBlob);
        elements.samplePreview.hidden = false;
        updateSaveVoiceState();
      },
    };
    elements.recordingStage.classList.add("recording");
    elements.recordingStatus.textContent = "Listening";
    elements.dialogRecordButton.textContent = "Stop recording";
    state.timerId = setInterval(() => { elements.recordingTimer.textContent = formatTime((Date.now() - state.startedAt) / 1000); }, 250);
  } catch (error) {
    elements.recordingStatus.textContent = "Microphone access failed";
    showError("Allow microphone access in your browser, or upload an audio file instead.");
  }
}

function updateSaveVoiceState() {
  elements.saveVoiceButton.disabled = !state.sampleBlob || !elements.voiceConsent.checked || !elements.voiceNameInput.value.trim();
}

async function saveVoice() {
  if (!state.sampleBlob) return;
  elements.saveVoiceButton.disabled = true;
  elements.saveVoiceButton.textContent = "Saving...";
  const data = new FormData();
  data.append("name", elements.voiceNameInput.value.trim());
  data.append("consent", "true");
  data.append("sample", state.sampleBlob, state.sampleName);
  try {
    const voice = await api("/api/voices", { method: "POST", body: data });
    state.voices.unshift(voice);
    state.selectedVoiceId = voice.id;
    elements.voiceDialog.close();
    renderVoices(); updateGenerateState(); clearError();
  } catch (error) { showError(error.message); }
  finally { elements.saveVoiceButton.textContent = "Save voice"; updateSaveVoiceState(); }
}

async function generateSpeech() {
  if (elements.generateButton.disabled) return;
  const scripts = queuedScripts();
  clearError(); state.generating = true; updateGenerateState();
  elements.generationProgress.hidden = false;
  elements.progressLabel.textContent = `Preparing ${scripts.length} ${scripts.length === 1 ? "phase" : "phases"}`;
  const started = Date.now();
  const timer = setInterval(() => { elements.progressTimer.textContent = formatTime((Date.now() - started) / 1000); }, 250);
  try {
    const previousHistory = [...state.history];
    const generated = [];
    for (let index = 0; index < scripts.length; index += 1) {
      elements.progressLabel.textContent = `Generating phase ${index + 1} of ${scripts.length}`;
      const entry = await api("/api/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          voice_id: state.selectedVoiceId,
          text: scripts[index],
          model: elements.modelSelect.value,
          language: elements.languageSelect.value,
          exaggeration: Number(elements.expressionRange.value) / 100,
          cfg_weight: Number(elements.fidelityRange.value) / 100,
          seed: 0,
          consent: elements.consentCheckbox.checked,
        }),
      });
      generated.push(entry);
      state.history = [...generated, ...previousHistory];
      renderHistory();
    }
    elements.progressLabel.textContent = `${scripts.length} ${scripts.length === 1 ? "phase" : "phases"} generated`;
    const firstAudio = elements.historyList.querySelector("audio");
    if (firstAudio) await firstAudio.play().catch(() => {});
    setTimeout(() => { elements.generationProgress.hidden = true; }, 1100);
  } catch (error) { elements.generationProgress.hidden = true; showError(error.message); }
  finally { clearInterval(timer); state.generating = false; updateGenerateState(); }
}

async function initialise() {
  try {
    const [health, voices, history] = await Promise.all([api("/api/health"), api("/api/voices"), api("/api/history")]);
    state.voices = voices; state.history = history;
    const engine = health.engine;
    elements.systemState.classList.add(engine.installed ? "ready" : "error");
    elements.systemText.textContent = engine.installed ? `Local engine · ${engine.device.toUpperCase()}` : "Engine setup required";
    renderVoices(); renderHistory(); updateGenerateState();
  } catch {
    elements.systemState.classList.add("error");
    elements.systemText.textContent = "Preview mode";
    renderVoices(); renderHistory(); updateGenerateState();
  }
}

elements.scriptInputs.forEach((input) => input.addEventListener("input", updateScriptStats));
elements.consentCheckbox.addEventListener("change", updateGenerateState);
elements.expressionRange.addEventListener("input", () => { elements.expressionValue.textContent = elements.expressionRange.value; });
elements.fidelityRange.addEventListener("input", () => { elements.fidelityValue.textContent = elements.fidelityRange.value; });
elements.modelSelect.addEventListener("change", () => {
  const multilingual = elements.modelSelect.value === "multilingual";
  elements.languageSelect.disabled = !multilingual;
  if (!multilingual) elements.languageSelect.value = "en";
});
elements.recordButton.addEventListener("click", openRecordDialog);
elements.addVoiceButton.addEventListener("click", openRecordDialog);
elements.fileInput.addEventListener("change", () => { const file = elements.fileInput.files[0]; if (file) openUploadDialog(file); elements.fileInput.value = ""; });
elements.dialogRecordButton.addEventListener("click", toggleRecording);
elements.voiceConsent.addEventListener("change", updateSaveVoiceState);
elements.voiceNameInput.addEventListener("input", updateSaveVoiceState);
elements.saveVoiceButton.addEventListener("click", saveVoice);
elements.generateButton.addEventListener("click", generateSpeech);
elements.voiceDialog.addEventListener("close", resetVoiceDialog);
document.addEventListener("keydown", (event) => { if (event.ctrlKey && event.key === "Enter") generateSpeech(); });

elements.languageSelect.disabled = true;
updateScriptStats();
initialise();

