# SevenLabs

SevenLabs is a private Windows voice studio for local voice design, voice cloning, long-form speech, and transcription. It recreates the useful workflow of the Freeelevenlabs/Creative Audio reference app with an embedded [VoxCPM2](https://huggingface.co/OpenBMB/VoxCPM2) engine, then adds automatic long-script splitting, one-file joining, local Whisper transcription, and a native desktop window.

Only clone a voice you own or have explicit permission to use.

## What it does

- **Voice Design** creates a new voice from a written description without a recording.
- **Clone** speaks a script using a saved reference voice and optional style direction.
- **Ultimate Clone** continues from a reference voice using the exact transcript of its sample.
- Long scripts are divided at natural sentence boundaries and joined into one WAV automatically. The submitted words are not rewritten.
- The transcriber converts audio to editable text with local faster-whisper models.
- Voice samples, model files, transcripts, and generated audio stay on the computer.

## Install on Windows

1. Download `SevenLabs-Setup.exe` from the project release or `dist` folder.
2. Open the installer and launch SevenLabs.
3. Keep the first setup window open. SevenLabs installs Python 3.11 if needed and creates its own private environment.
4. In the app, choose **Download model** once. VoxCPM2 is about 2.3 GB.
5. Add a 10–30 second clean voice sample, paste a script, confirm permission, and generate.

An NVIDIA GPU with at least 6 GB of VRAM is recommended. SevenLabs can fall back to CPU, but generation will be much slower. Allow several gigabytes of free disk space.

## Using the three modes

### Voice Design

Choose **Voice Design**, describe the voice (for example, “warm documentary narrator, clear diction, medium pace”), paste the script, and generate. No saved voice is required.

### Clone

Record or upload a voice sample, select it in the left column, choose **Clone**, optionally describe the style, then paste the full script and generate.

### Ultimate Clone

Select a saved voice, choose **Ultimate Clone**, and enter the exact words spoken in that voice sample under **Reference transcript**. Then paste the new script. This mode uses the sample as a continuation prompt.

## Long-form audio

Paste the entire script into the single Script box. SevenLabs previews how many safe parts it will use, generates them in order with one consistent seed, inserts a short pause between parts, and saves one finished WAV. You do not need to manage phases or remove completed text.

Generated files are stored in:

```text
%LOCALAPPDATA%\SevenLabs\data\outputs
```

Saved voice samples and downloaded models are under `%LOCALAPPDATA%\SevenLabs\data` as well.

## Run from source

Open PowerShell in the project folder:

```powershell
.\setup.ps1
.\start.ps1
```

To download the voice model ahead of time:

```powershell
.\.venv\Scripts\python.exe scripts\warm_models.py
```

## Build the distributable installer

```powershell
.\build-installer.ps1
```

The build appears in `dist\SevenLabs-Setup.exe`. The launcher contains the app and the Apache-2.0 VoxCPM source; recipients do not need Git. The first launch still needs internet access for Python packages and model weights.

## Troubleshooting

- **The first launch takes a while:** PyTorch and the speech dependencies are large. Keep the setup window open.
- **Generation is slow:** CPU generation is supported but much slower than a compatible NVIDIA GPU.
- **A model download stopped:** Open SevenLabs again and press **Download model**; the Hugging Face download resumes existing files.
- **The app will not open:** Check `%LOCALAPPDATA%\SevenLabs\data\sevenlabs-desktop.log`.
- **Port 8765 is busy:** Close an older SevenLabs process and reopen the app.

## Credits and licenses

The voice engine is based on OpenBMB's VoxCPM/VoxCPM2 source under the Apache License 2.0. Its source and license are included in `vendor/VoxCPM`. Transcription uses faster-whisper. SevenLabs is independently named and designed; it does not reuse the Creative Audio branding or artwork.
