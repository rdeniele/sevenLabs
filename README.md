# Local Voice Studio

A private, local-first voice cloning studio powered by [Chatterbox](https://github.com/resemble-ai/chatterbox). Record or upload a short voice sample, type a script, and generate watermarked speech on your own computer. The engine is pinned to an exact official commit so Nano support and future package changes cannot silently break the app.

## What it does

- Records a voice sample in the browser or accepts WAV, MP3, M4A, FLAC, OGG, and WebM files.
- Keeps voice samples and generated audio in the local `data/` folder.
- Offers three local models:
  - **Nano**: English, lowest memory use, recommended for CPU and 4 GB GPUs.
  - **Turbo**: English, faster high-quality generation with speech tags such as `[laugh]`.
  - **Multilingual V3**: 23+ languages and stronger cross-language cloning.
- Adds Chatterbox's built-in PerTh watermark to generated audio.
- Includes consent confirmation, local history, playback, and WAV downloads.

## Windows quick start

After the initial setup, double-click **`Local Voice Studio.cmd`**. Keep its small terminal window open while using the app; closing that window stops the private local server.

For the initial setup, you can also double-click the launcher and let it run setup automatically. Or open PowerShell in this folder and run:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\setup.ps1
.\start.ps1
```

The app opens at `http://127.0.0.1:8765`.

The setup script installs Python 3.11 with `winget` if needed, creates an isolated `.venv`, installs a CUDA-enabled PyTorch build when an NVIDIA GPU is detected, then installs the app dependencies. Model weights are downloaded on the first use of each model.

## How to use the app

1. Double-click **`Local Voice Studio.cmd`** and wait for the browser to open.
2. Under **Voice source**, choose **Record sample** or **Upload audio**.
3. Give the voice a name and confirm that you own it or have permission to clone it.
4. Write your script, choose a model, and confirm the generation permission checkbox.
5. Select **Generate speech**. Play or download the resulting WAV under **Recent generations**.

The first generation with a new model takes longer because its weights must download and load into memory. Later generations reuse the local cache.

### Choosing a model

- Start with **Nano** for English and computers with limited GPU memory.
- Use **Turbo** for expressive English and speech tags such as `[laugh]`.
- Use **Multilingual V3** when the script is not English. Select the matching language in the app.

## Requirements

- Windows 10 or Windows 11
- About 8 GB of free disk space for the application, runtime, and Nano model
- 16 GB RAM recommended; 8 GB may work more slowly
- Internet access for the one-time setup and initial model download
- NVIDIA GPU optional. The app automatically falls back to CPU when GPU memory is insufficient.

## Troubleshooting

- **The browser did not open:** visit `http://127.0.0.1:8765` manually.
- **Generation ran out of GPU memory:** use Nano or set `$env:LOCAL_VOICE_DEVICE="cpu"` before running `start.ps1`.
- **Microphone recording does not start:** allow microphone access for the localhost page, or upload a voice sample instead.
- **The first generation looks stuck:** keep the launcher window open. Model downloads are several gigabytes and may take a few minutes.

## Offline use

Once setup and the first model download are complete, disconnect from the internet and run `start.ps1`. The server binds only to `127.0.0.1`, so it is not exposed to the network.

The app automatically uses CPU inference when the selected model would not safely fit in GPU memory. On this machine, Nano runs on the CPU because the RTX 3050 has 4 GB of VRAM, while the model remains fully local. Advanced users can set `LOCAL_VOICE_DEVICE=cpu` or `LOCAL_VOICE_DEVICE=cuda` before launching to override the automatic choice.

To pre-download a model before going offline:

```powershell
.\.venv\Scripts\python.exe scripts\warm_models.py nano
```

Replace `nano` with `turbo` or `multilingual` as needed.

## Good reference audio

- Use 10-30 seconds of one person speaking naturally.
- Record in a quiet room without music, echo, or background voices.
- Keep the microphone 15-25 cm away.
- Use the same language as the script for the most natural accent.
- You may store multiple samples as separate voices and compare results.

## Responsible use

Only clone your own voice or a voice you have explicit permission to use. Do not use generated audio to deceive, impersonate, defraud, or mislead. The app requires consent confirmation and labels every output as synthetic in its local metadata.

## Data and cleanup

All user data lives under `data/`:

- `data/voices/`: saved reference samples and voice metadata
- `data/outputs/`: generated WAV files and metadata

Use the delete controls in the app, or close the app and remove individual folders inside `data/`.

## Development

The frontend is dependency-free HTML, CSS, and JavaScript. The backend uses FastAPI and loads Chatterbox lazily so the app starts quickly.

```powershell
.\.venv\Scripts\python.exe -m pytest
```

