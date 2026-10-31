from __future__ import annotations

import asyncio
import importlib.metadata
import importlib.util
import json
import os
import re
import shutil
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field


ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = ROOT / "app" / "static"
DATA_DIR = ROOT / "data"
VOICES_DIR = DATA_DIR / "voices"
OUTPUTS_DIR = DATA_DIR / "outputs"
MODELS_DIR = DATA_DIR / "models"
ALLOWED_AUDIO = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".webm", ".aac"}
TRANSCRIPTION_MODELS = {"tiny", "base", "small"}
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_SCRIPT_CHARS = 50_000
MAX_TRANSCRIPTION_BYTES = 500 * 1024 * 1024
CHUNK_TARGET_WORDS = 70
CHUNK_MAX_WORDS = 90
CHUNK_MAX_CHARS = 560
CHUNK_PAUSE_SECONDS = 0.28
for directory in (VOICES_DIR, OUTPUTS_DIR, MODELS_DIR):
    directory.mkdir(parents=True, exist_ok=True)

# Keep model weights beside the app instead of leaking data into a user-level cache.
os.environ.setdefault("HF_HOME", str(MODELS_DIR / "huggingface"))
os.environ.setdefault("HF_HUB_CACHE", str(MODELS_DIR / "huggingface" / "hub"))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_name(value: str, fallback: str = "voice") -> str:
    value = re.sub(r"[^a-zA-Z0-9 _-]+", "", value).strip()
    return value[:48] or fallback


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def output_audio_path(output_id: str, voice_name: str) -> Path:
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"SevenLabs-{safe_name(voice_name, 'voice').replace(' ', '-')}-{timestamp}-{output_id[:8]}.wav"
    return OUTPUTS_DIR / filename


def record_audio_path(record: dict[str, Any], output_id: str) -> Path:
    stored = record.get("audio_path")
    return Path(stored) if stored else OUTPUTS_DIR / f"{output_id}.wav"


def public_voice(record: dict[str, Any]) -> dict[str, Any]:
    return {key: record.get(key) for key in ("id", "name", "created_at", "source_name", "duration_hint")}


@dataclass
class ModelHandle:
    model: Any
    device: str
    loaded_at: float


class VoiceEngine:
    MODEL_ID = "OpenBMB/VoxCPM2"
    MODEL_DIR = MODELS_DIR / "voxcpm2"
    DOWNLOAD_BYTES = 2_290_000_000

    def __init__(self) -> None:
        self._handle: ModelHandle | None = None
        self._load_lock = threading.Lock()
        self._generate_lock = threading.Lock()
        self._download_lock = threading.Lock()
        self._download_started_at = 0.0
        self._download_start_size = 0
        self._download_error: str | None = None
        self._downloading = False

    @staticmethod
    def device() -> str:
        try:
            import torch

            return "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            return "unavailable"

    @staticmethod
    def device_for_model(model_name: str = "voxcpm2") -> str:
        override = os.environ.get("LOCAL_VOICE_DEVICE", "auto").lower()
        if override in {"cpu", "cuda"}:
            return override

        try:
            import torch

            if not torch.cuda.is_available():
                return "cpu"
            memory_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3)
            return "cuda" if memory_gb >= 6 else "cpu"
        except ImportError:
            return "cpu"

    @staticmethod
    def installed() -> bool:
        return importlib.util.find_spec("voxcpm") is not None

    @classmethod
    def model_downloaded(cls) -> bool:
        return (cls.MODEL_DIR / "config.json").is_file() and any(cls.MODEL_DIR.rglob("*.safetensors"))

    @classmethod
    def model_size(cls) -> int:
        if not cls.MODEL_DIR.exists():
            return 0
        return sum(path.stat().st_size for path in cls.MODEL_DIR.rglob("*") if path.is_file())

    @staticmethod
    def detected_device() -> str:
        if importlib.util.find_spec("torch") is None:
            return "unavailable"
        try:
            if "+cpu" in importlib.metadata.version("torch").lower():
                return "cpu"
            system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
            return "cuda" if (system_root / "System32" / "nvidia-smi.exe").is_file() else "cpu"
        except importlib.metadata.PackageNotFoundError:
            return "cpu"

    def status(self) -> dict[str, Any]:
        downloaded_bytes = self.model_size()
        elapsed = max(0.001, time.time() - self._download_started_at) if self._downloading else 0
        transferred = max(0, downloaded_bytes - self._download_start_size)
        return {
            "installed": self.installed(),
            "device": self._handle.device if self._handle else self.detected_device(),
            "loaded_model": "voxcpm2" if self._handle else None,
            "offline_ready": self._handle is not None,
            "model_downloaded": self.model_downloaded(),
            "is_downloading": self._downloading,
            "downloaded_bytes": downloaded_bytes,
            "download_percent": round(min(99.9, downloaded_bytes / self.DOWNLOAD_BYTES * 100), 1) if self._downloading else (100.0 if self.model_downloaded() else 0.0),
            "download_speed_mbps": round(transferred / 1024 / 1024 / elapsed, 1) if elapsed else 0.0,
            "download_error": self._download_error,
        }

    def start_download(self) -> bool:
        with self._download_lock:
            if self._downloading or self.model_downloaded():
                return False
            self._downloading = True
            self._download_error = None
            self._download_started_at = time.time()
            self._download_start_size = self.model_size()
            threading.Thread(target=self._download_model, daemon=True, name="voxcpm-download").start()
            return True

    def _download_model(self) -> None:
        try:
            from huggingface_hub import snapshot_download

            self.MODEL_DIR.mkdir(parents=True, exist_ok=True)
            snapshot_download(repo_id=self.MODEL_ID, local_dir=str(self.MODEL_DIR))
        except Exception as error:
            self._download_error = str(error)
        finally:
            self._downloading = False

    def _load(self) -> ModelHandle:
        with self._load_lock:
            if self._handle:
                return self._handle

            if not self.installed():
                raise RuntimeError("The voice engine is not installed. Run setup.ps1 first.")
            if not self.model_downloaded():
                raise RuntimeError("Download the VoxCPM2 voice engine before generating audio.")

            device = self.device_for_model()
            if device == "unavailable":
                raise RuntimeError("PyTorch is not installed. Run setup.ps1 first.")

            from voxcpm import VoxCPM

            model = VoxCPM.from_pretrained(
                str(self.MODEL_DIR),
                load_denoiser=False,
                optimize=device == "cuda",
                device=device,
                local_files_only=True,
            )
            self._handle = ModelHandle(model, device, time.time())
            return self._handle

    def generate(
        self,
        mode: str,
        text: str,
        reference_path: Path | None,
        output_path: Path,
        style_prompt: str,
        reference_transcript: str,
        guidance: float,
        inference_steps: int,
        seed: int,
    ) -> dict[str, Any]:
        with self._generate_lock:
            handle = self._load()

            try:
                import soundfile as sf

                if mode not in {"design", "clone", "ultimate"}:
                    raise ValueError("Choose Voice Design, Clone, or Ultimate Clone mode.")
                if mode != "design" and reference_path is None:
                    raise ValueError("Choose a saved voice for cloning.")
                if mode == "ultimate" and not reference_transcript.strip():
                    raise ValueError("Ultimate Clone needs the exact transcript of the reference audio.")

                spoken_text = f"({style_prompt.strip()}){text}" if style_prompt.strip() else text
                values: dict[str, Any] = {
                    "text": spoken_text,
                    "cfg_value": guidance,
                    "inference_timesteps": inference_steps,
                    "seed": seed,
                    # Preserve the submitted script exactly. VoxCPM's optional
                    # normalizer can rewrite numbers and punctuation.
                    "normalize": False,
                }
                if mode == "clone":
                    values["reference_wav_path"] = str(reference_path)
                elif mode == "ultimate":
                    values["prompt_wav_path"] = str(reference_path)
                    values["prompt_text"] = reference_transcript.strip()

                wave = handle.model.generate(**values)
                sample_rate = int(handle.model.tts_model.sample_rate)
                sf.write(str(output_path), wave, sample_rate, subtype="PCM_16")
                return {
                    "duration_seconds": round(len(wave) / sample_rate, 2),
                    "device": handle.device,
                    "seed": seed,
                }
            except RuntimeError as error:
                if "out of memory" in str(error).lower():
                    try:
                        import torch

                        if torch.cuda.is_available():
                            torch.cuda.empty_cache()
                    except ImportError:
                        pass
                    raise RuntimeError("VoxCPM2 ran out of GPU memory. Close other GPU apps or use CPU mode.") from error
                raise


class TranscriptionEngine:
    def __init__(self) -> None:
        self._models: dict[str, Any] = {}
        self._device: str | None = None
        self._load_lock = threading.Lock()
        self._transcribe_lock = threading.Lock()

    @staticmethod
    def installed() -> bool:
        return importlib.util.find_spec("faster_whisper") is not None

    def status(self) -> dict[str, Any]:
        return {
            "installed": self.installed(),
            "loaded": bool(self._models),
            "loaded_models": sorted(self._models),
            "device": self._device or VoiceEngine.detected_device(),
        }

    def _load(self, model_name: str) -> Any:
        if model_name not in TRANSCRIPTION_MODELS:
            raise ValueError("Choose the Tiny, Base, or Small transcription model.")
        with self._load_lock:
            if model_name in self._models:
                return self._models[model_name]
            if not self.installed():
                raise RuntimeError("The transcriber is not installed. Run setup.ps1 again.")

            from faster_whisper import WhisperModel

            device = "cuda" if VoiceEngine.device_for_model() == "cuda" else "cpu"
            compute_type = "float16" if device == "cuda" else "int8"
            model = WhisperModel(
                model_name,
                device=device,
                compute_type=compute_type,
                download_root=str(MODELS_DIR / "faster-whisper"),
            )
            self._models[model_name] = model
            self._device = device
            return model

    def transcribe(self, audio_path: Path, language: str | None = None, model_name: str = "base") -> dict[str, Any]:
        with self._transcribe_lock:
            model = self._load(model_name)
            segments, info = model.transcribe(
                str(audio_path),
                language=language or None,
                beam_size=5,
                vad_filter=True,
                condition_on_previous_text=True,
            )
            rows = []
            text_parts = []
            for segment in segments:
                text = segment.text.strip()
                if not text:
                    continue
                rows.append({"start": round(segment.start, 2), "end": round(segment.end, 2), "text": text})
                text_parts.append(text)
            return {
                "text": " ".join(text_parts).strip(),
                "language": info.language,
                "language_probability": round(info.language_probability, 3),
                "duration_seconds": round(info.duration, 2),
                "segments": rows,
                "device": self._device,
                "model": model_name,
            }


def _split_oversized_text(text: str, max_words: int, max_chars: int) -> list[str]:
    """Split a long sentence at clauses, then words, without rewriting it."""
    clauses = [part.strip() for part in re.split(r"(?<=[,;:—–])\s+", text) if part.strip()]
    if len(clauses) == 1:
        words = text.split()
        chunks: list[str] = []
        current: list[str] = []
        for word in words:
            candidate = " ".join((*current, word))
            if current and (len(current) >= max_words or len(candidate) > max_chars):
                chunks.append(" ".join(current))
                current = [word]
            else:
                current.append(word)
        if current:
            chunks.append(" ".join(current))
        return chunks

    chunks = []
    current = ""
    for clause in clauses:
        if len(clause.split()) > max_words or len(clause) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_split_oversized_text(clause, max_words, max_chars))
            continue
        candidate = f"{current} {clause}".strip()
        if current and (len(candidate.split()) > max_words or len(candidate) > max_chars):
            chunks.append(current)
            current = clause
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def split_script(
    text: str,
    target_words: int = CHUNK_TARGET_WORDS,
    max_words: int = CHUNK_MAX_WORDS,
    max_chars: int = CHUNK_MAX_CHARS,
) -> list[str]:
    """Create model-safe chunks at natural boundaries while preserving all words."""
    normalized = re.sub(r"[ \t]+", " ", text.strip())
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    if not normalized:
        return []

    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+|(?<=[.!?][\"'”’)])\s+|\n+", normalized) if part.strip()]
    units: list[str] = []
    for sentence in sentences:
        if len(sentence.split()) > max_words or len(sentence) > max_chars:
            units.extend(_split_oversized_text(sentence, max_words, max_chars))
        else:
            units.append(sentence)

    chunks: list[str] = []
    current = ""
    for unit in units:
        candidate = f"{current} {unit}".strip()
        candidate_words = len(candidate.split())
        if current and (candidate_words > max_words or len(candidate) > max_chars or len(current.split()) >= target_words):
            chunks.append(current)
            current = unit
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def combine_wav_files(paths: list[Path], output_path: Path, pause_seconds: float = CHUNK_PAUSE_SECONDS) -> float:
    import wave

    if not paths:
        raise RuntimeError("No generated audio was available to combine.")

    chunks: list[bytes] = []
    parameters: tuple[int, int, int] | None = None
    total_frames = 0
    for path in paths:
        with wave.open(str(path), "rb") as source:
            current = (source.getnchannels(), source.getsampwidth(), source.getframerate())
            if parameters is None:
                parameters = current
            elif current != parameters:
                raise RuntimeError("Generated audio parts do not share the same WAV format.")
            frame_count = source.getnframes()
            chunks.append(source.readframes(frame_count))
            total_frames += frame_count

    assert parameters is not None
    channels, sample_width, sample_rate = parameters
    pause_frames = int(sample_rate * pause_seconds)
    pause = b"\x00" * pause_frames * channels * sample_width
    with wave.open(str(output_path), "wb") as destination:
        destination.setnchannels(channels)
        destination.setsampwidth(sample_width)
        destination.setframerate(sample_rate)
        for index, chunk in enumerate(chunks):
            if index:
                destination.writeframes(pause)
                total_frames += pause_frames
            destination.writeframes(chunk)
    return round(total_frames / sample_rate, 2)


engine = VoiceEngine()
transcriber = TranscriptionEngine()
app = FastAPI(title="SevenLabs", docs_url=None, redoc_url=None)


class GenerateRequest(BaseModel):
    voice_id: str | None = Field(default=None, max_length=64)
    text: str = Field(min_length=1, max_length=MAX_SCRIPT_CHARS)
    mode: str = Field(default="clone", pattern="^(design|clone|ultimate)$")
    style_prompt: str = Field(default="", max_length=1_000)
    reference_transcript: str = Field(default="", max_length=10_000)
    guidance: float = Field(default=2.0, ge=1.0, le=4.0)
    inference_steps: int = Field(default=10, ge=4, le=30)
    seed: int = Field(default=0, ge=0, le=2_147_483_647)
    consent: bool


class ChunkPreviewRequest(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_SCRIPT_CHARS)


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "engine": engine.status(),
        "transcriber": transcriber.status(),
        "models": ["voxcpm2"],
        "modes": ["design", "clone", "ultimate"],
    }


@app.post("/api/model/download")
async def download_voice_model() -> dict[str, Any]:
    started = engine.start_download()
    return {"started": started, **engine.status()}


@app.post("/api/chunks")
async def preview_chunks(request: ChunkPreviewRequest) -> dict[str, Any]:
    chunks = split_script(request.text)
    return {
        "count": len(chunks),
        "chunks": [{"number": index + 1, "words": len(chunk.split()), "text": chunk} for index, chunk in enumerate(chunks)],
    }


@app.get("/api/voices")
async def list_voices() -> list[dict[str, Any]]:
    records = []
    for metadata_path in VOICES_DIR.glob("*/voice.json"):
        record = read_json(metadata_path)
        if record:
            records.append(public_voice(record))
    return sorted(records, key=lambda item: item.get("created_at") or "", reverse=True)


@app.post("/api/voices", status_code=201)
async def create_voice(
    name: str = Form(...),
    consent: bool = Form(...),
    sample: UploadFile = File(...),
) -> dict[str, Any]:
    if not consent:
        raise HTTPException(400, "Confirm that you own this voice or have permission to use it.")

    suffix = Path(sample.filename or "sample.wav").suffix.lower()
    if suffix not in ALLOWED_AUDIO:
        raise HTTPException(400, "Use a WAV, MP3, M4A, FLAC, OGG, AAC, or WebM audio file.")

    voice_id = uuid.uuid4().hex
    voice_dir = VOICES_DIR / voice_id
    voice_dir.mkdir(parents=True)
    audio_path = voice_dir / f"reference{suffix}"
    total = 0

    try:
        with audio_path.open("wb") as destination:
            while chunk := await sample.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, "The voice sample is larger than 50 MB.")
                destination.write(chunk)

        if total < 1_024:
            raise HTTPException(400, "The voice sample is empty or too short.")

        record = {
            "id": voice_id,
            "name": safe_name(name, "My voice"),
            "created_at": now_iso(),
            "source_name": safe_name(Path(sample.filename or "recording").name, "recording.wav"),
            "reference_file": audio_path.name,
            "consent_confirmed": True,
        }
        write_json(voice_dir / "voice.json", record)
        return public_voice(record)
    except Exception:
        shutil.rmtree(voice_dir, ignore_errors=True)
        raise


@app.delete("/api/voices/{voice_id}", status_code=204, response_class=Response)
async def delete_voice(voice_id: str) -> Response:
    voice_dir = VOICES_DIR / safe_name(voice_id, "invalid")
    if not voice_dir.exists() or voice_dir.parent != VOICES_DIR:
        raise HTTPException(404, "Voice not found")
    shutil.rmtree(voice_dir)
    return Response(status_code=204)


@app.get("/api/history")
async def history() -> list[dict[str, Any]]:
    records = []
    for metadata_path in OUTPUTS_DIR.glob("*.json"):
        record = read_json(metadata_path)
        if record:
            records.append(record)
    return sorted(records, key=lambda item: item.get("created_at") or "", reverse=True)[:100]


def resolve_generation_voice(request: GenerateRequest) -> tuple[dict[str, Any], Path | None]:
    if request.mode == "design":
        return {"id": None, "name": "Designed voice"}, None
    if not request.voice_id:
        raise HTTPException(400, "Choose a saved voice for cloning.")
    voice_dir = VOICES_DIR / safe_name(request.voice_id, "invalid")
    voice_record = read_json(voice_dir / "voice.json")
    if not voice_record:
        raise HTTPException(404, "Voice not found")
    reference_path = voice_dir / voice_record["reference_file"]
    if not reference_path.exists():
        raise HTTPException(404, "The reference audio for this voice is missing.")
    if request.mode == "ultimate" and not request.reference_transcript.strip():
        raise HTTPException(400, "Ultimate Clone needs the exact transcript of the reference audio.")
    return voice_record, reference_path


@app.post("/api/generate")
async def generate(request: GenerateRequest) -> dict[str, Any]:
    if not request.consent:
        raise HTTPException(400, "Consent confirmation is required.")

    voice_record, reference_path = resolve_generation_voice(request)

    output_id = uuid.uuid4().hex
    output_path = output_audio_path(output_id, voice_record["name"])
    seed = request.seed or int.from_bytes(os.urandom(4), "little")

    try:
        result = await asyncio.to_thread(
            engine.generate,
            request.mode,
            request.text.strip(),
            reference_path,
            output_path,
            request.style_prompt,
            request.reference_transcript,
            request.guidance,
            request.inference_steps,
            seed,
        )
    except Exception as error:
        output_path.unlink(missing_ok=True)
        raise HTTPException(500, str(error)) from error

    record = {
        "id": output_id,
        "voice_id": voice_record.get("id"),
        "voice_name": voice_record["name"],
        "text": request.text.strip(),
        "model": "voxcpm2",
        "mode": request.mode,
        "style_prompt": request.style_prompt.strip(),
        "seed": result["seed"],
        "created_at": now_iso(),
        "duration_seconds": result["duration_seconds"],
        "device": result["device"],
        "synthetic": True,
        "watermarked": False,
        "audio_url": f"/api/audio/{output_id}",
        "download_url": f"/api/audio/{output_id}?download=1",
        "audio_path": str(output_path),
    }
    write_json(OUTPUTS_DIR / f"{output_id}.json", record)
    return record


@app.post("/api/generate-long")
async def generate_long(request: GenerateRequest) -> dict[str, Any]:
    if not request.consent:
        raise HTTPException(400, "Consent confirmation is required.")

    voice_record, reference_path = resolve_generation_voice(request)

    script = request.text.strip()
    chunks = split_script(script)
    if not chunks:
        raise HTTPException(400, "Write a script before generating.")

    output_id = uuid.uuid4().hex
    output_path = output_audio_path(output_id, voice_record["name"])
    base_seed = request.seed or int.from_bytes(os.urandom(4), "little")
    devices: set[str] = set()

    try:
        with tempfile.TemporaryDirectory(prefix="sevenlabs-") as temp_dir:
            chunk_paths = []
            used_seeds = []
            for index, chunk in enumerate(chunks):
                chunk_path = Path(temp_dir) / f"chunk-{index:04d}.wav"
                result = await asyncio.to_thread(
                    engine.generate,
                    request.mode,
                    chunk,
                    reference_path,
                    chunk_path,
                    request.style_prompt,
                    request.reference_transcript,
                    request.guidance,
                    request.inference_steps,
                    base_seed,
                )
                chunk_paths.append(chunk_path)
                used_seeds.append(result["seed"])
                devices.add(result["device"])
            duration = await asyncio.to_thread(combine_wav_files, chunk_paths, output_path)
    except Exception as error:
        output_path.unlink(missing_ok=True)
        raise HTTPException(500, str(error)) from error

    record = {
        "id": output_id,
        "voice_id": voice_record.get("id"),
        "voice_name": voice_record["name"],
        "text": script,
        "model": "voxcpm2",
        "mode": request.mode,
        "style_prompt": request.style_prompt.strip(),
        "seed": base_seed,
        "chunk_seeds": used_seeds,
        "chunk_count": len(chunks),
        "created_at": now_iso(),
        "duration_seconds": duration,
        "device": ", ".join(sorted(devices)),
        "synthetic": True,
        "watermarked": False,
        "long_form": True,
        "audio_url": f"/api/audio/{output_id}",
        "download_url": f"/api/audio/{output_id}?download=1",
        "audio_path": str(output_path),
    }
    write_json(OUTPUTS_DIR / f"{output_id}.json", record)
    return record


@app.post("/api/transcribe")
async def transcribe_audio(
    audio: UploadFile = File(...),
    language: str = Form(default="auto"),
    model: str = Form(default="base"),
) -> dict[str, Any]:
    if model not in TRANSCRIPTION_MODELS:
        raise HTTPException(400, "Choose the Tiny, Base, or Small transcription model.")
    suffix = Path(audio.filename or "audio.wav").suffix.lower()
    if suffix not in ALLOWED_AUDIO:
        raise HTTPException(400, "Use a WAV, MP3, M4A, FLAC, OGG, AAC, or WebM audio file.")

    temp_path = OUTPUTS_DIR / f"transcribe-{uuid.uuid4().hex}{suffix}"
    total = 0
    try:
        with temp_path.open("wb") as destination:
            while chunk := await audio.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_TRANSCRIPTION_BYTES:
                    raise HTTPException(413, "The audio file is larger than 500 MB.")
                destination.write(chunk)
        if total < 1_024:
            raise HTTPException(400, "The audio file is empty or too short.")
        return await asyncio.to_thread(
            transcriber.transcribe,
            temp_path,
            None if language == "auto" else language,
            model,
        )
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(500, str(error)) from error
    finally:
        temp_path.unlink(missing_ok=True)


@app.get("/api/audio/{output_id}")
async def audio(output_id: str, download: bool = False) -> FileResponse:
    output_id = safe_name(output_id, "invalid")
    metadata = read_json(OUTPUTS_DIR / f"{output_id}.json")
    path = record_audio_path(metadata, output_id)
    if not path.exists() or path.suffix.lower() != ".wav":
        raise HTTPException(404, "Audio not found")

    filename = path.name
    return FileResponse(path, media_type="audio/wav", filename=filename if download else None)


@app.delete("/api/history/{output_id}", status_code=204, response_class=Response)
async def delete_output(output_id: str) -> Response:
    output_id = safe_name(output_id, "invalid")
    metadata_path = OUTPUTS_DIR / f"{output_id}.json"
    metadata = read_json(metadata_path)
    audio_path = record_audio_path(metadata, output_id)
    if not audio_path.exists() and not metadata_path.exists():
        raise HTTPException(404, "Generation not found")
    audio_path.unlink(missing_ok=True)
    metadata_path.unlink(missing_ok=True)
    return Response(status_code=204)


app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")

