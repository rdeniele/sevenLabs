from __future__ import annotations

import asyncio
import io
import wave
from pathlib import Path

import pytest
import torch
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


def test_strict_reading_options_reduce_sampling_randomness() -> None:
    options = main.STRICT_READING_OPTIONS
    assert options["temperature"] < 0.8
    assert options["top_p"] == 0.95
    assert options["top_k"] == 1000
    assert options["repetition_penalty"] == 1.2


def test_long_trailing_silence_is_trimmed() -> None:
    spoken = torch.full((1, 2_000), 0.1)
    silence = torch.full((1, 3_000), 0.0001)
    trimmed = main.VoiceEngine._trim_trailing_silence(
        torch.cat((spoken, silence), dim=-1),
        sample_rate=1_000,
    )
    assert trimmed.shape[-1] == 2_350


def test_long_script_with_only_brief_speech_is_retried() -> None:
    brief_speech = torch.cat((torch.full((1, 2_000), 0.1), torch.zeros((1, 38_000))), dim=-1)
    long_script = " ".join(["word"] * 79)
    assert main.VoiceEngine._needs_silence_retry(brief_speech, 1_000, long_script) is True


def test_healthy_take_does_not_retry() -> None:
    healthy_speech = torch.full((1, 27_000), 0.1)
    long_script = " ".join(["word"] * 79)
    assert main.VoiceEngine._needs_silence_retry(healthy_speech, 1_000, long_script) is False


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


def test_output_folder_setting_is_created_and_saved(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings_file = tmp_path / "settings.json"
    chosen_folder = tmp_path / "exports" / "sevenlabs"
    monkeypatch.setattr(main, "SETTINGS_FILE", settings_file)
    result = asyncio.run(main.set_output_folder(main.OutputFolderRequest(path=str(chosen_folder))))
    assert chosen_folder.is_dir()
    assert result["path"] == str(chosen_folder)
    assert asyncio.run(main.get_output_folder())["path"] == str(chosen_folder)


def test_output_audio_path_uses_configured_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings_file = tmp_path / "settings.json"
    chosen_folder = tmp_path / "finished"
    settings_file.write_text('{"output_folder": "' + str(chosen_folder).replace("\\", "\\\\") + '"}', encoding="utf-8")
    monkeypatch.setattr(main, "SETTINGS_FILE", settings_file)
    path = main.output_audio_path("1234567890abcdef", "My Voice")
    assert path.parent == chosen_folder
    assert path.name.startswith("SevenLabs-My-Voice-")
    assert path.name.endswith("-12345678.wav")
