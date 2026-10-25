from __future__ import annotations

import asyncio
import io
import wave

import pytest
from fastapi import HTTPException, UploadFile

from app import main


def tiny_wav() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16_000)
        wav.writeframes(b"\x00\x00" * 16_000)
    return buffer.getvalue()


def test_health_reports_local_engine() -> None:
    body = asyncio.run(main.health())
    assert body["ok"] is True
    assert body["engine"]["installed"] is True
    assert body["engine"]["device"] in {"cpu", "cuda"}
    assert body["models"] == ["nano", "turbo", "multilingual"]


def test_voice_lifecycle() -> None:
    sample = UploadFile(filename="sample.wav", file=io.BytesIO(tiny_wav()))
    voice = asyncio.run(main.create_voice(name="API test voice", consent=True, sample=sample))
    try:
        assert voice["name"] == "API test voice"
        voices = asyncio.run(main.list_voices())
        assert any(item["id"] == voice["id"] for item in voices)

        response = asyncio.run(main.delete_voice(voice["id"]))
        assert response.status_code == 204
    finally:
        voice_dir = main.VOICES_DIR / voice["id"]
        if voice_dir.exists():
            import shutil

            shutil.rmtree(voice_dir)


def test_voice_requires_permission() -> None:
    sample = UploadFile(filename="sample.wav", file=io.BytesIO(tiny_wav()))
    with pytest.raises(HTTPException) as raised:
        asyncio.run(main.create_voice(name="No permission", consent=False, sample=sample))
    assert raised.value.status_code == 400


def test_generation_requires_permission_before_model_load() -> None:
    payload = main.GenerateRequest(
        voice_id="missing",
        text="Hello",
        model="nano",
        language="en",
        exaggeration=0.5,
        cfg_weight=0.5,
        seed=0,
        consent=False,
    )
    with pytest.raises(HTTPException) as raised:
        asyncio.run(main.generate(payload))
    assert raised.value.status_code == 400
