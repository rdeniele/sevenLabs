from __future__ import annotations

import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("HF_HOME", str(ROOT / "data" / "models" / "huggingface"))
os.environ.setdefault("HF_HUB_CACHE", str(ROOT / "data" / "models" / "huggingface" / "hub"))


def main() -> None:
    from huggingface_hub import snapshot_download

    destination = ROOT / "data" / "models" / "voxcpm2"
    snapshot_download(repo_id="OpenBMB/VoxCPM2", local_dir=str(destination))
    print("VoxCPM2 is downloaded and ready for offline use.")


if __name__ == "__main__":
    main()

