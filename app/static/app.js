const $ = (selector) => document.querySelector(selector);
const state = { voices: [], history: [], selectedVoiceId: null, mode: "clone", modelDownloaded: false, modelPoll: null, sampleBlob: null, sampleName: "recording.wav", recorder: null, mediaStream: null, timerId: null, startedAt: 0, generating: false, transcribeFile: null, chunkCount: 0, chunkTimer: null };
const elements = {
  systemState: $("#systemState"), systemText: $("#systemText"), voiceList: $("#voiceList"), voiceEmpty: $("#voiceEmpty"), addVoiceButton: $("#addVoiceButton"), recordButton: $("#recordButton"), fileInput: $("#fileInput"),
  scriptInput: $("#scriptInput"), wordCount: $("#wordCount"), chunkCount: $("#chunkCount"), characterCount: $("#characterCount"), splitMessage: $("#splitMessage"), modeTabs: [...document.querySelectorAll("[data-mode]")], stylePrompt: $("#stylePrompt"), stylePromptLabel: $("#stylePromptLabel"), referenceTranscript: $("#referenceTranscript"), referenceTranscriptField: $("#referenceTranscriptField"), modeHelp: $("#modeHelp"), guidanceRange: $("#guidanceRange"), guidanceValue: $("#guidanceValue"), inferenceSteps: $("#inferenceSteps"), engineSetup: $("#engineSetup"), engineSetupTitle: $("#engineSetupTitle"), engineSetupText: $("#engineSetupText"), downloadModelButton: $("#downloadModelButton"), engineDownloadTrack: $("#engineDownloadTrack"), engineDownloadBar: $("#engineDownloadBar"), consentCheckbox: $("#consentCheckbox"), consentText: $("#consentText"), generateButton: $("#generateButton"), generateLabel: $("#generateLabel"), generationProgress: $("#generationProgress"), progressLabel: $("#progressLabel"), progressTimer: $("#progressTimer"), errorBanner: $("#errorBanner"),
  historyList: $("#historyList"), historyEmpty: $("#historyEmpty"), transcribeDrop: $("#transcribeDrop"), transcribeInput: $("#transcribeInput"), transcribeFileName: $("#transcribeFileName"), transcribeLanguage: $("#transcribeLanguage"), transcribeModel: $("#transcribeModel"), transcribeButton: $("#transcribeButton"), transcriptOutput: $("#transcriptOutput"), copyTranscript: $("#copyTranscript"), transcribeStatus: $("#transcribeStatus"),
  voiceDialog: $("#voiceDialog"), dialogTitle: $("#dialogTitle"), dialogDescription: $("#dialogDescription"), voiceNameInput: $("#voiceNameInput"), recordingStage: $("#recordingStage"), recordingStatus: $("#recordingStatus"), recordingTimer: $("#recordingTimer"), samplePreview: $("#samplePreview"), voiceConsent: $("#voiceConsent"), dialogRecordButton: $("#dialogRecordButton"), saveVoiceButton: $("#saveVoiceButton"),
};

async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) { let message = `Request failed (${response.status})`; try { message = (await response.json()).detail || message; } catch {} throw new Error(message); }
  return response.status === 204 ? null : response.json();
}
function formatTime(seconds) { const value = Math.max(0, Math.floor(seconds)); return `${Math.floor(value / 60)}:${String(value % 60).padStart(2, "0")}`; }
function formatDate(iso) { const delta = Date.now() - new Date(iso).getTime(); if (delta < 60_000) return "just now"; if (delta < 3_600_000) return `${Math.floor(delta / 60_000)}m ago`; if (delta < 86_400_000) return `${Math.floor(delta / 3_600_000)}h ago`; return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(new Date(iso)); }
function showError(message) { elements.errorBanner.textContent = message; elements.errorBanner.hidden = false; }
function clearError() { elements.errorBanner.hidden = true; }

function updateGenerateState() {
  const voiceReady = state.mode === "design" || state.selectedVoiceId;
  const transcriptReady = state.mode !== "ultimate" || elements.referenceTranscript.value.trim();
  const ready = state.modelDownloaded && voiceReady && transcriptReady && elements.scriptInput.value.trim() && elements.consentCheckbox.checked;
  elements.generateButton.disabled = state.generating || !ready;
  elements.generateLabel.textContent = state.generating ? "Creating full audio…" : "Generate full audio";
}

function setMode(mode) {
  state.mode = mode;
  elements.modeTabs.forEach((button) => { const active = button.dataset.mode === mode; button.classList.toggle("active", active); button.setAttribute("aria-selected", String(active)); });
  elements.referenceTranscriptField.hidden = mode !== "ultimate";
  elements.stylePromptLabel.innerHTML = mode === "ultimate" ? "Style direction <small>optional</small>" : mode === "design" ? "Voice description <small>required for best results</small>" : "Style direction <small>optional</small>";
  elements.stylePrompt.placeholder = mode === "design" ? "Young narrator, warm tone, clear diction, medium pace…" : "Warm, confident, conversational, medium pace…";
  elements.modeHelp.textContent = mode === "design" ? "Create a new voice from a written description—no sample required." : mode === "ultimate" ? "Continue from a saved voice using the exact transcript of its reference audio." : "Clone a saved voice and optionally steer its emotion, pace, and style.";
  elements.consentText.textContent = mode === "design" ? "I will use this synthetic voice responsibly." : "I own this voice or have permission to use it.";
  updateGenerateState();
}

function renderEngineStatus(engine) {
  state.modelDownloaded = Boolean(engine.model_downloaded);
  elements.engineSetup.hidden = state.modelDownloaded;
  elements.engineDownloadTrack.hidden = !engine.is_downloading;
  elements.engineDownloadBar.style.width = `${engine.download_percent || 0}%`;
  elements.downloadModelButton.disabled = engine.is_downloading;
  elements.downloadModelButton.textContent = engine.is_downloading ? `${engine.download_percent || 0}%` : "Download model";
  elements.engineSetupTitle.textContent = engine.download_error ? "Model download paused" : engine.is_downloading ? "Downloading VoxCPM2" : "VoxCPM2 is required";
  elements.engineSetupText.textContent = engine.download_error || (engine.is_downloading ? `${engine.download_speed_mbps || 0} MB/s · keep SevenLabs open` : "Download the local voice model once, then use it offline.");
  updateGenerateState();
  if (engine.is_downloading && !state.modelPoll) state.modelPoll = setInterval(refreshEngineStatus, 1000);
  if (!engine.is_downloading && state.modelPoll) { clearInterval(state.modelPoll); state.modelPoll = null; }
}

async function refreshEngineStatus() { try { const health = await api("/api/health"); renderEngineStatus(health.engine); } catch {} }
async function downloadModel() { clearError(); try { const engine = await api("/api/model/download", { method: "POST" }); renderEngineStatus(engine); } catch (error) { showError(error.message); } }
async function updateScriptStats() {
  const text = elements.scriptInput.value;
  const words = text.trim() ? text.trim().split(/\s+/).length : 0;
  elements.wordCount.textContent = words.toLocaleString();
  elements.characterCount.textContent = `${text.length.toLocaleString()} / 50,000`;
  updateGenerateState();
  clearTimeout(state.chunkTimer);
  if (!text.trim()) { state.chunkCount = 0; elements.chunkCount.textContent = "0"; elements.splitMessage.textContent = "Nothing will be rewritten or added."; return; }
  state.chunkTimer = setTimeout(async () => {
    try {
      const result = await api("/api/chunks", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }) });
      if (elements.scriptInput.value !== text) return;
      state.chunkCount = result.count;
      elements.chunkCount.textContent = result.count;
      elements.splitMessage.textContent = result.count > 1 ? `Will generate ${result.count} safe parts and join them into one WAV.` : "This script fits safely in one generation.";
    } catch { elements.splitMessage.textContent = "SevenLabs will split this automatically when you generate."; }
  }, 350);
}

function renderVoices() {
  elements.voiceList.replaceChildren(); elements.voiceEmpty.hidden = state.voices.length > 0;
  if (!state.selectedVoiceId && state.voices[0]) state.selectedVoiceId = state.voices[0].id;
  state.voices.forEach((voice) => {
    const item = $("#voiceItemTemplate").content.firstElementChild.cloneNode(true); item.classList.toggle("selected", voice.id === state.selectedVoiceId);
    item.querySelector("strong").textContent = voice.name; item.querySelector("small").textContent = `Saved ${formatDate(voice.created_at)}`;
    item.querySelector(".voice-select").addEventListener("click", () => { state.selectedVoiceId = voice.id; renderVoices(); updateGenerateState(); });
    item.querySelector(".item-delete").addEventListener("click", async () => { if (!confirm(`Delete ${voice.name}?`)) return; try { await api(`/api/voices/${voice.id}`, { method: "DELETE" }); state.voices = state.voices.filter((entry) => entry.id !== voice.id); if (state.selectedVoiceId === voice.id) state.selectedVoiceId = state.voices[0]?.id || null; renderVoices(); updateGenerateState(); } catch (error) { showError(error.message); } });
    elements.voiceList.append(item);
  });
}
function setPlayIcon(button, playing) { button.innerHTML = playing ? '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 7v10M15 7v10"/></svg>' : '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 7 8 5-8 5Z" /></svg>'; }
function renderHistory() {
  elements.historyList.replaceChildren(); elements.historyEmpty.hidden = state.history.length > 0;
  state.history.forEach((entry) => {
    const item = $("#historyItemTemplate").content.firstElementChild.cloneNode(true); const audio = item.querySelector("audio"); const play = item.querySelector(".play-button");
    item.querySelector("strong").textContent = entry.long_form ? `${entry.voice_name} · full audio` : entry.voice_name; item.querySelector("p").textContent = entry.text;
    item.querySelector(".history-model").textContent = `${entry.mode || entry.model} · ${formatTime(entry.duration_seconds || 0)}${entry.chunk_count ? ` · ${entry.chunk_count} parts` : ""}`; item.querySelector(".history-time").textContent = formatDate(entry.created_at); audio.src = entry.audio_url;
    play.addEventListener("click", async () => { document.querySelectorAll(".history-item audio").forEach((other) => { if (other !== audio) other.pause(); }); if (audio.paused) await audio.play(); else audio.pause(); });
    audio.addEventListener("play", () => setPlayIcon(play, true)); audio.addEventListener("pause", () => setPlayIcon(play, false)); audio.addEventListener("ended", () => setPlayIcon(play, false));
    const download = item.querySelector(".download-button"); download.href = entry.download_url; download.download = "";
    item.querySelector(".history-delete").addEventListener("click", async () => { try { await api(`/api/history/${entry.id}`, { method: "DELETE" }); state.history = state.history.filter((row) => row.id !== entry.id); renderHistory(); } catch (error) { showError(error.message); } });
    elements.historyList.append(item);
  });
}

function resetVoiceDialog() { stopMediaTracks(); state.sampleBlob = null; state.sampleName = "recording.wav"; elements.samplePreview.hidden = true; elements.samplePreview.removeAttribute("src"); elements.voiceConsent.checked = false; elements.saveVoiceButton.disabled = true; elements.recordingStage.classList.remove("recording"); elements.recordingStatus.textContent = "Ready to record"; elements.recordingTimer.textContent = "0:00"; elements.dialogRecordButton.textContent = "Start recording"; elements.voiceNameInput.value = "My voice"; }
function openRecordDialog() { resetVoiceDialog(); elements.dialogTitle.textContent = "Record a sample"; elements.dialogDescription.textContent = "Speak naturally for 10–30 seconds."; elements.recordingStage.hidden = false; elements.dialogRecordButton.hidden = false; elements.voiceDialog.showModal(); }
function openUploadDialog(file) { resetVoiceDialog(); state.sampleBlob = file; state.sampleName = file.name || "sample.wav"; elements.dialogTitle.textContent = "Save this voice"; elements.dialogDescription.textContent = "Name the voice and confirm permission."; elements.recordingStage.hidden = true; elements.dialogRecordButton.hidden = true; elements.samplePreview.src = URL.createObjectURL(file); elements.samplePreview.hidden = false; elements.voiceNameInput.value = file.name.replace(/\.[^.]+$/, "").slice(0, 48) || "My voice"; elements.voiceDialog.showModal(); updateSaveVoiceState(); }
function stopMediaTracks() { if (state.mediaStream) state.mediaStream.getTracks().forEach((track) => track.stop()); state.mediaStream = null; if (state.timerId) clearInterval(state.timerId); state.timerId = null; }
function mergeBuffers(buffers) { const length = buffers.reduce((total, buffer) => total + buffer.length, 0); const merged = new Float32Array(length); let offset = 0; buffers.forEach((buffer) => { merged.set(buffer, offset); offset += buffer.length; }); return merged; }
function encodeWav(samples, sampleRate) { const buffer = new ArrayBuffer(44 + samples.length * 2); const view = new DataView(buffer); const write = (offset, value) => [...value].forEach((char, index) => view.setUint8(offset + index, char.charCodeAt(0))); write(0, "RIFF"); view.setUint32(4, 36 + samples.length * 2, true); write(8, "WAVE"); write(12, "fmt "); view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true); view.setUint32(24, sampleRate, true); view.setUint32(28, sampleRate * 2, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true); write(36, "data"); view.setUint32(40, samples.length * 2, true); let offset = 44; samples.forEach((sample) => { const value = Math.max(-1, Math.min(1, sample)); view.setInt16(offset, value < 0 ? value * 0x8000 : value * 0x7fff, true); offset += 2; }); return new Blob([view], { type: "audio/wav" }); }
async function toggleRecording() {
  if (state.recorder) { state.recorder.stop(); return; }
  try { const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } }); state.mediaStream = stream; const AudioContextClass = window.AudioContext || window.webkitAudioContext; const context = new AudioContextClass(); const source = context.createMediaStreamSource(stream); const processor = context.createScriptProcessor(4096, 1, 1); const buffers = []; processor.onaudioprocess = (event) => buffers.push(new Float32Array(event.inputBuffer.getChannelData(0))); source.connect(processor); processor.connect(context.destination); state.startedAt = Date.now(); state.recorder = { stop: async () => { processor.disconnect(); source.disconnect(); await context.close(); stopMediaTracks(); const duration = (Date.now() - state.startedAt) / 1000; state.sampleBlob = encodeWav(mergeBuffers(buffers), context.sampleRate); state.sampleName = "recording.wav"; state.recorder = null; elements.recordingStage.classList.remove("recording"); elements.recordingStatus.textContent = duration < 5 ? "Short sample — 10 seconds works better" : "Sample ready"; elements.dialogRecordButton.textContent = "Record again"; elements.samplePreview.src = URL.createObjectURL(state.sampleBlob); elements.samplePreview.hidden = false; updateSaveVoiceState(); } }; elements.recordingStage.classList.add("recording"); elements.recordingStatus.textContent = "Listening"; elements.dialogRecordButton.textContent = "Stop recording"; state.timerId = setInterval(() => { elements.recordingTimer.textContent = formatTime((Date.now() - state.startedAt) / 1000); }, 250);
  } catch { elements.recordingStatus.textContent = "Microphone access failed"; showError("Allow microphone access, or upload an audio file instead."); }
}
function updateSaveVoiceState() { elements.saveVoiceButton.disabled = !state.sampleBlob || !elements.voiceConsent.checked || !elements.voiceNameInput.value.trim(); }
async function saveVoice() { if (!state.sampleBlob) return; elements.saveVoiceButton.disabled = true; elements.saveVoiceButton.textContent = "Saving…"; const data = new FormData(); data.append("name", elements.voiceNameInput.value.trim()); data.append("consent", "true"); data.append("sample", state.sampleBlob, state.sampleName); try { const voice = await api("/api/voices", { method: "POST", body: data }); state.voices.unshift(voice); state.selectedVoiceId = voice.id; elements.voiceDialog.close(); renderVoices(); updateGenerateState(); clearError(); } catch (error) { showError(error.message); } finally { elements.saveVoiceButton.textContent = "Save voice"; updateSaveVoiceState(); } }

async function generateSpeech() {
  if (elements.generateButton.disabled) return; clearError(); state.generating = true; updateGenerateState(); elements.generationProgress.hidden = false;
  const parts = state.chunkCount || 1; elements.progressLabel.textContent = `Generating and joining ${parts} ${parts === 1 ? "part" : "parts"}`; const started = Date.now(); const timer = setInterval(() => { elements.progressTimer.textContent = formatTime((Date.now() - started) / 1000); }, 250);
  try { const entry = await api("/api/generate-long", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ voice_id: state.mode === "design" ? null : state.selectedVoiceId, text: elements.scriptInput.value.trim(), mode: state.mode, style_prompt: elements.stylePrompt.value.trim(), reference_transcript: elements.referenceTranscript.value.trim(), guidance: Number(elements.guidanceRange.value) / 10, inference_steps: Number(elements.inferenceSteps.value), seed: 0, consent: elements.consentCheckbox.checked }) }); state.history.unshift(entry); renderHistory(); elements.progressLabel.textContent = "Full audio is ready"; const firstAudio = elements.historyList.querySelector("audio"); if (firstAudio) await firstAudio.play().catch(() => {}); setTimeout(() => { elements.generationProgress.hidden = true; }, 1200);
  } catch (error) { elements.generationProgress.hidden = true; showError(error.message); } finally { clearInterval(timer); state.generating = false; updateGenerateState(); }
}

function chooseTranscribeFile(file) { if (!file) return; state.transcribeFile = file; elements.transcribeFileName.textContent = file.name; elements.transcribeButton.disabled = false; elements.transcribeStatus.textContent = `${(file.size / 1024 / 1024).toFixed(1)} MB · ready to transcribe locally`; }
async function transcribeAudio() { if (!state.transcribeFile) return; elements.transcribeButton.disabled = true; elements.transcribeButton.textContent = "Transcribing…"; elements.transcribeStatus.textContent = "Listening to the entire file. Keep SevenLabs open."; const data = new FormData(); data.append("audio", state.transcribeFile, state.transcribeFile.name); data.append("language", elements.transcribeLanguage.value); data.append("model", elements.transcribeModel.value); try { const result = await api("/api/transcribe", { method: "POST", body: data }); elements.transcriptOutput.value = result.text; elements.copyTranscript.disabled = !result.text; elements.transcribeStatus.textContent = `${formatTime(result.duration_seconds)} audio · ${result.language.toUpperCase()} · Whisper ${result.model.toUpperCase()} on ${result.device.toUpperCase()}`; } catch (error) { elements.transcribeStatus.textContent = error.message; } finally { elements.transcribeButton.disabled = false; elements.transcribeButton.textContent = "Transcribe"; } }

async function initialise() { try { const [health, voices, history] = await Promise.all([api("/api/health"), api("/api/voices"), api("/api/history")]); state.voices = voices; state.history = history; elements.systemState.classList.add(health.engine.installed ? "ready" : "error"); const model = health.engine.model_downloaded ? "VoxCPM2 ready" : "VoxCPM2 download needed"; elements.systemText.textContent = health.engine.installed ? `Local · ${health.engine.device.toUpperCase()} · ${model}` : "Setup required"; renderEngineStatus(health.engine); renderVoices(); renderHistory(); setMode("clone"); } catch { elements.systemState.classList.add("error"); elements.systemText.textContent = "Preview mode"; renderVoices(); renderHistory(); setMode("clone"); } }

elements.scriptInput.addEventListener("input", updateScriptStats); elements.consentCheckbox.addEventListener("change", updateGenerateState); elements.referenceTranscript.addEventListener("input", updateGenerateState); elements.guidanceRange.addEventListener("input", () => { elements.guidanceValue.textContent = (Number(elements.guidanceRange.value) / 10).toFixed(1); }); elements.modeTabs.forEach((button) => button.addEventListener("click", () => setMode(button.dataset.mode))); elements.downloadModelButton.addEventListener("click", downloadModel);
elements.recordButton.addEventListener("click", openRecordDialog); elements.addVoiceButton.addEventListener("click", openRecordDialog); elements.fileInput.addEventListener("change", () => { const file = elements.fileInput.files[0]; if (file) openUploadDialog(file); elements.fileInput.value = ""; });
elements.dialogRecordButton.addEventListener("click", toggleRecording); elements.voiceConsent.addEventListener("change", updateSaveVoiceState); elements.voiceNameInput.addEventListener("input", updateSaveVoiceState); elements.saveVoiceButton.addEventListener("click", saveVoice); elements.generateButton.addEventListener("click", generateSpeech); elements.voiceDialog.addEventListener("close", resetVoiceDialog);
elements.transcribeInput.addEventListener("change", () => chooseTranscribeFile(elements.transcribeInput.files[0])); elements.transcribeButton.addEventListener("click", transcribeAudio); elements.copyTranscript.addEventListener("click", async () => { await navigator.clipboard.writeText(elements.transcriptOutput.value); elements.copyTranscript.textContent = "Copied"; setTimeout(() => { elements.copyTranscript.textContent = "Copy text"; }, 1200); });
["dragenter", "dragover"].forEach((name) => elements.transcribeDrop.addEventListener(name, (event) => { event.preventDefault(); elements.transcribeDrop.classList.add("dragging"); })); ["dragleave", "drop"].forEach((name) => elements.transcribeDrop.addEventListener(name, (event) => { event.preventDefault(); elements.transcribeDrop.classList.remove("dragging"); })); elements.transcribeDrop.addEventListener("drop", (event) => chooseTranscribeFile(event.dataTransfer.files[0]));
document.addEventListener("keydown", (event) => { if (event.ctrlKey && event.key === "Enter") generateSpeech(); });
updateScriptStats(); initialise();
