from __future__ import annotations

import asyncio
import importlib.util
import inspect
import json
import os
import re
import shutil
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
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_SCRIPT_CHARS = 5_000
STRICT_READING_OPTIONS = {
    # Stay close to Chatterbox's tuned defaults. Aggressive filtering can make
    # Nano select silence tokens for the rest of an otherwise valid take.
    "temperature": 0.65,
    "top_p": 0.95,
    "top_k": 1000,
    "repetition_penalty": 1.2,
}

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


def public_voice(record: dict[str, Any]) -> dict[str, Any]:
    return {key: record.get(key) for key in ("id", "name", "created_at", "source_name", "duration_hint")}


@dataclass
class ModelHandle:
    name: str
    model: Any
    device: str
    loaded_at: float


class VoiceEngine:
    def __init__(self) -> None:
        self._handle: ModelHandle | None = None
        self._load_lock = threading.Lock()
        self._generate_lock = threading.Lock()

    @staticmethod
    def device() -> str:
        try:
            import torch

            return "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            return "unavailable"

    @staticmethod
    def device_for_model(model_name: str) -> str:
        override = os.environ.get("LOCAL_VOICE_DEVICE", "auto").lower()
        if override in {"cpu", "cuda"}:
            return override

        try:
            import torch

            if not torch.cuda.is_available():
                return "cpu"
            memory_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3)
            minimums = {"nano": 6, "turbo": 8, "multilingual": 10}
            return "cuda" if memory_gb >= minimums[model_name] else "cpu"
        except (ImportError, KeyError):
            return "cpu"

    @staticmethod
    def installed() -> bool:
        return importlib.util.find_spec("chatterbox") is not None

    @staticmethod
    def detected_device() -> str:
        if importlib.util.find_spec("torch") is None:
            return "unavailable"
        return "cuda" if shutil.which("nvidia-smi") else "cpu"

    def status(self) -> dict[str, Any]:
        return {
            "installed": self.installed(),
            "device": self._handle.device if self._handle else self.detected_device(),
            "loaded_model": self._handle.name if self._handle else None,
            "offline_ready": self._handle is not None,
        }

    def _load(self, model_name: str) -> ModelHandle:
        with self._load_lock:
            if self._handle and self._handle.name == model_name:
                return self._handle

            if not self.installed():
                raise RuntimeError("The voice engine is not installed. Run setup.ps1 first.")

            device = self.device_for_model(model_name)
            if device == "unavailable":
                raise RuntimeError("PyTorch is not installed. Run setup.ps1 first.")

            if model_name == "nano":
                from chatterbox.tts_turbo import ChatterboxTurboTTS

                model = ChatterboxTurboTTS.from_pretrained(device=device, nano=True)
            elif model_name == "turbo":
                from chatterbox.tts_turbo import ChatterboxTurboTTS

                model = ChatterboxTurboTTS.from_pretrained(device=device)
            elif model_name == "multilingual":
                from chatterbox.mtl_tts import ChatterboxMultilingualTTS

                model = ChatterboxMultilingualTTS.from_pretrained(device=device, t3_model="v3")
            else:
                raise ValueError("Unknown model")

            self._handle = ModelHandle(model_name, model, device, time.time())
            return self._handle

    @staticmethod
    def _supported_kwargs(callable_obj: Any, values: dict[str, Any]) -> dict[str, Any]:
        signature = inspect.signature(callable_obj)
        accepts_any = any(param.kind == inspect.Parameter.VAR_KEYWORD for param in signature.parameters.values())
        if accepts_any:
            return values
        return {key: value for key, value in values.items() if key in signature.parameters}

    @staticmethod
    def _speech_end_sample(
        wave: Any,
        sample_rate: int,
        threshold: float = 0.001,
        frame_seconds: float = 0.1,
    ) -> int:
        """Find the end of audible speech using frame RMS, ignoring watermark noise."""
        activity = wave.float()
        if getattr(activity, "ndim", 1) > 1:
            activity = activity.pow(2).mean(dim=0).sqrt()
        else:
            activity = activity.abs()

        total_samples = int(activity.shape[-1])
        if total_samples == 0:
            return 0
        frame_samples = max(1, int(sample_rate * frame_seconds))
        complete_frames = total_samples // frame_samples
        last_active_end = 0

        if complete_frames:
            framed = activity[: complete_frames * frame_samples].reshape(complete_frames, frame_samples)
            frame_rms = framed.pow(2).mean(dim=1).sqrt()
            active_frames = (frame_rms > threshold).nonzero(as_tuple=False).flatten()
            if active_frames.numel():
                last_active_end = (int(active_frames[-1].item()) + 1) * frame_samples

        remainder_start = complete_frames * frame_samples
        if remainder_start < total_samples:
            remainder_rms = activity[remainder_start:].pow(2).mean().sqrt()
            if float(remainder_rms.item()) > threshold:
                last_active_end = total_samples

        return last_active_end

    @classmethod
    def _trim_trailing_silence(
        cls,
        wave: Any,
        sample_rate: int,
        threshold: float = 0.001,
        minimum_tail_seconds: float = 1.0,
        keep_seconds: float = 0.35,
    ) -> Any:
        """Remove a long silent tail while preserving natural sentence room."""
        speech_end = cls._speech_end_sample(wave, sample_rate, threshold)
        if speech_end == 0:
            return wave

        tail_samples = wave.shape[-1] - speech_end
        if tail_samples <= int(sample_rate * minimum_tail_seconds):
            return wave

        end = min(wave.shape[-1], speech_end + int(sample_rate * keep_seconds))
        return wave[..., :end]

    @classmethod
    def _spoken_seconds(cls, wave: Any, sample_rate: int, threshold: float = 0.001) -> float:
        return float(cls._speech_end_sample(wave, sample_rate, threshold) / sample_rate)

    @classmethod
    def _needs_silence_retry(cls, wave: Any, sample_rate: int, text: str) -> bool:
        word_count = len(text.split())
        if word_count < 20:
            return False
        minimum_expected_seconds = min(12.0, word_count * 0.15)
        return cls._spoken_seconds(wave, sample_rate) < minimum_expected_seconds

    def generate(
        self,
        model_name: str,
        text: str,
        reference_path: Path,
        output_path: Path,
        language: str,
        exaggeration: float,
        cfg_weight: float,
        seed: int,
    ) -> dict[str, Any]:
        with self._generate_lock:
            handle = self._load(model_name)

            try:
                import torch
                import torchaudio as ta

                values: dict[str, Any] = {
                    "audio_prompt_path": str(reference_path),
                    "exaggeration": exaggeration,
                    "cfg_weight": cfg_weight,
                    **STRICT_READING_OPTIONS,
                }
                if model_name == "multilingual":
                    values["language_id"] = language

                kwargs = self._supported_kwargs(handle.model.generate, values)
                def generate_once(attempt_seed: int) -> Any:
                    torch.manual_seed(attempt_seed)
                    if torch.cuda.is_available():
                        torch.cuda.manual_seed_all(attempt_seed)
                    attempt = handle.model.generate(text, **kwargs)
                    if getattr(attempt, "ndim", 1) == 1:
                        attempt = attempt.unsqueeze(0)
                    return attempt

                used_seed = seed
                wave = generate_once(used_seed)
                for offset in (1, 2):
                    if not self._needs_silence_retry(wave, handle.model.sr, text):
                        break
                    retry_seed = (seed + offset) % (2**32)
                    retry_wave = generate_once(retry_seed)
                    if self._spoken_seconds(retry_wave, handle.model.sr) > self._spoken_seconds(wave, handle.model.sr):
                        wave = retry_wave
                        used_seed = retry_seed

                wave = self._trim_trailing_silence(wave, handle.model.sr)
                ta.save(str(output_path), wave.detach().cpu(), handle.model.sr)
                duration = float(wave.shape[-1] / handle.model.sr)
                return {"duration_seconds": round(duration, 2), "device": handle.device, "seed": used_seed}
            except RuntimeError as error:
                if "out of memory" in str(error).lower():
                    try:
                        import torch

                        if torch.cuda.is_available():
                            torch.cuda.empty_cache()
                    except ImportError:
                        pass
                    raise RuntimeError("The selected model ran out of GPU memory. Try Nano or close other GPU apps.") from error
                raise


engine = VoiceEngine()
app = FastAPI(title="SevenLabs", docs_url=None, redoc_url=None)


class GenerateRequest(BaseModel):
    voice_id: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1, max_length=MAX_SCRIPT_CHARS)
    model: str = Field(default="nano", pattern="^(nano|turbo|multilingual)$")
    language: str = Field(default="en", min_length=2, max_length=12)
    exaggeration: float = Field(default=0.5, ge=0.0, le=1.0)
    cfg_weight: float = Field(default=0.5, ge=0.0, le=1.0)
    seed: int = Field(default=0, ge=0, le=2_147_483_647)
    consent: bool


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "engine": engine.status(), "models": ["nano", "turbo", "multilingual"]}


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


@app.post("/api/generate")
async def generate(request: GenerateRequest) -> dict[str, Any]:
    if not request.consent:
        raise HTTPException(400, "Consent confirmation is required.")

    voice_dir = VOICES_DIR / safe_name(request.voice_id, "invalid")
    voice_record = read_json(voice_dir / "voice.json")
    if not voice_record:
        raise HTTPException(404, "Voice not found")

    reference_path = voice_dir / voice_record["reference_file"]
    if not reference_path.exists():
        raise HTTPException(404, "The reference audio for this voice is missing.")

    output_id = uuid.uuid4().hex
    output_path = OUTPUTS_DIR / f"{output_id}.wav"
    seed = request.seed or int.from_bytes(os.urandom(4), "little")

    try:
        result = await asyncio.to_thread(
            engine.generate,
            request.model,
            request.text.strip(),
            reference_path,
            output_path,
            request.language,
            request.exaggeration,
            request.cfg_weight,
            seed,
        )
    except Exception as error:
        output_path.unlink(missing_ok=True)
        raise HTTPException(500, str(error)) from error

    record = {
        "id": output_id,
        "voice_id": request.voice_id,
        "voice_name": voice_record["name"],
        "text": request.text.strip(),
        "model": request.model,
        "language": request.language,
        "seed": result["seed"],
        "created_at": now_iso(),
        "duration_seconds": result["duration_seconds"],
        "device": result["device"],
        "synthetic": True,
        "watermarked": True,
        "audio_url": f"/api/audio/{output_id}",
        "download_url": f"/api/audio/{output_id}?download=1",
    }
    write_json(OUTPUTS_DIR / f"{output_id}.json", record)
    return record


@app.get("/api/audio/{output_id}")
async def audio(output_id: str, download: bool = False) -> FileResponse:
    output_id = safe_name(output_id, "invalid")
    path = OUTPUTS_DIR / f"{output_id}.wav"
    metadata = read_json(OUTPUTS_DIR / f"{output_id}.json")
    if not path.exists() or path.parent != OUTPUTS_DIR:
        raise HTTPException(404, "Audio not found")

    filename = f"{safe_name(metadata.get('voice_name', 'voice'))}-{output_id[:8]}.wav"
    return FileResponse(path, media_type="audio/wav", filename=filename if download else None)


@app.delete("/api/history/{output_id}", status_code=204, response_class=Response)
async def delete_output(output_id: str) -> Response:
    output_id = safe_name(output_id, "invalid")
    audio_path = OUTPUTS_DIR / f"{output_id}.wav"
    metadata_path = OUTPUTS_DIR / f"{output_id}.json"
    if not audio_path.exists() and not metadata_path.exists():
        raise HTTPException(404, "Generation not found")
    audio_path.unlink(missing_ok=True)
    metadata_path.unlink(missing_ok=True)
    return Response(status_code=204)


app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")

