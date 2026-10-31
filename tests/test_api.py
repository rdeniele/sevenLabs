from __future__ import annotations

import asyncio
import io
import wave
from pathlib import Path

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
    assert isinstance(body["engine"]["installed"], bool)
    assert body["engine"]["device"] in {"unavailable", "cpu", "cuda"}
    assert body["models"] == ["voxcpm2"]
    assert body["modes"] == ["design", "clone", "ultimate"]
    assert "transcriber" in body


def test_long_script_is_split_at_sentence_boundaries_without_rewriting() -> None:
    sentences = [f"Sentence {index} has enough words to sound natural when spoken aloud." for index in range(1, 18)]
    script = " ".join(sentences)
    chunks = main.split_script(script, target_words=30, max_words=40, max_chars=300)
    assert len(chunks) > 1
    assert " ".join(chunks) == script
    assert all(len(chunk.split()) <= 40 for chunk in chunks)


def test_oversized_sentence_is_split_without_losing_words() -> None:
    script = " ".join(f"word{index}" for index in range(205))
    chunks = main.split_script(script, target_words=70, max_words=90, max_chars=560)
    assert len(chunks) >= 3
    assert " ".join(chunks) == script
    assert all(len(chunk.split()) <= 90 for chunk in chunks)


def test_oversized_clause_is_split_without_losing_words() -> None:
    first_clause = " ".join(f"first{index}" for index in range(120)) + ","
    second_clause = " ".join(f"second{index}" for index in range(20)) + "."
    script = f"{first_clause} {second_clause}"
    chunks = main.split_script(script, target_words=50, max_words=60, max_chars=420)
    assert " ".join(chunks) == script
    assert all(len(chunk.split()) <= 60 for chunk in chunks)


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
        mode="clone",
        seed=0,
        consent=False,
    )
    with pytest.raises(HTTPException) as raised:
        asyncio.run(main.generate(payload))
    assert raised.value.status_code == 400


def test_wav_chunks_are_joined_with_a_pause(tmp_path: Path) -> None:
    first = tmp_path / "first.wav"
    second = tmp_path / "second.wav"
    output = tmp_path / "combined.wav"
    for path in (first, second):
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(1_000)
            wav.writeframes(b"\x01\x00" * 1_000)
    duration = main.combine_wav_files([first, second], output, pause_seconds=0.25)
    assert duration == 2.25
    with wave.open(str(output), "rb") as combined:
        assert combined.getnframes() == 2_250


def test_voice_design_does_not_require_a_saved_voice() -> None:
    payload = main.GenerateRequest(text="Hello", mode="design", consent=True)
    voice, reference = main.resolve_generation_voice(payload)
    assert voice["name"] == "Designed voice"
    assert reference is None


def test_clone_requires_a_saved_voice() -> None:
    payload = main.GenerateRequest(text="Hello", mode="clone", consent=True)
    with pytest.raises(HTTPException) as raised:
        main.resolve_generation_voice(payload)
    assert raised.value.status_code == 400


def test_ultimate_clone_requires_reference_transcript() -> None:
    payload = main.GenerateRequest(voice_id="missing", text="Hello", mode="ultimate", consent=True)
    with pytest.raises(HTTPException) as raised:
        main.resolve_generation_voice(payload)
    assert raised.value.status_code in {400, 404}


def test_output_audio_path_uses_local_outputs_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    chosen_folder = tmp_path / "outputs"
    monkeypatch.setattr(main, "OUTPUTS_DIR", chosen_folder)
    path = main.output_audio_path("1234567890abcdef", "My Voice")
    assert path.parent == chosen_folder
    assert path.name.startswith("SevenLabs-My-Voice-")
    assert path.name.endswith("-12345678.wav")


def test_transcriber_exposes_supported_models() -> None:
    assert main.TRANSCRIPTION_MODELS == {"tiny", "base", "small"}
