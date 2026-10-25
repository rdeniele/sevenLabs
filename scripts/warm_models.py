from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("HF_HOME", str(ROOT / "data" / "models" / "huggingface"))
os.environ.setdefault("HF_HUB_CACHE", str(ROOT / "data" / "models" / "huggingface" / "hub"))


def main() -> None:
    model_name = sys.argv[1].lower() if len(sys.argv) > 1 else "nano"
    if model_name == "nano":
        from chatterbox.tts_turbo import ChatterboxTurboTTS

        ChatterboxTurboTTS.from_pretrained(device="cpu", nano=True)
    elif model_name == "turbo":
        from chatterbox.tts_turbo import ChatterboxTurboTTS

        ChatterboxTurboTTS.from_pretrained(device="cpu")
    elif model_name == "multilingual":
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS

        ChatterboxMultilingualTTS.from_pretrained(device="cpu", t3_model="v3")
    else:
        raise SystemExit("Use nano, turbo, or multilingual")

    print(f"{model_name} is downloaded and ready for offline use.")


if __name__ == "__main__":
    main()

