# CLAUDE.md

This file gives coding-agent guidance for WaveShift TTS Engine.

## Project Overview

WaveShift TTS Engine is a production-derived Python service for the TTS/HLS stage
of a long-form video translation pipeline. It fetches translated transcript
segments and source media from Cloudflare D1/R2, generates speech with IndexTTS,
aligns audio duration to the source timing, mixes media with FFmpeg, and publishes
HLS output.

Public project documentation lives in `README.md`, `docs/architecture.md`, and
`docs/development.md`.

## Common Commands

Install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Configure local environment:

```bash
cp .env.example .env
```

Run the lightweight verification check:

```bash
python -m compileall api.py app.py config.py launcher.py orchestrator.py core utils
```

Start the service after Cloudflare credentials and IndexTTS checkpoints are ready:

```bash
python app.py
```

Health check:

```bash
curl http://localhost:8000/api/health
```

## Runtime Boundaries

The service assumes upstream systems already handled:

- upload
- source media separation
- transcription
- translation
- task row creation

This repository owns:

- Cloudflare D1/R2 fetches for TTS tasks
- speech reference clipping
- IndexTTS generation
- duration and timestamp alignment
- media mixing
- HLS output management
- task status updates for this stage

## Architecture Components

- `app.py`: application entry point.
- `api.py`: FastAPI routes and background task creation.
- `launcher.py`: constructs Cloudflare clients and service instances.
- `orchestrator.py`: coordinates the full TTS/HLS pipeline.
- `core/data_fetcher.py`: reads D1 rows and downloads R2 media.
- `core/audio_segmenter.py`: prepares voice reference clips.
- `core/my_index_tts.py`: wraps IndexTTS inference.
- `core/timeadjust/`: duration and timestamp adjustment.
- `core/media_mixer.py`: FFmpeg media composition.
- `core/hls_manager.py`: HLS playlist/segment publication.
- `core/cloudflare/`: D1 and R2 clients.

## Development Rules

- Do not commit `.env`, credentials, generated media, downloaded checkpoints, or
  production task payloads.
- Keep public docs in sync with any configuration or data-contract change.
- Prefer testable helpers around timestamp math, R2 path handling, and config
  validation.
- Preserve relative R2 object keys as the public data-contract shape unless a
  migration is explicitly documented.
- Debug endpoints must not expose sensitive user media or secrets when deployed
  beyond local development.

## Third-Party Code

`models/IndexTTS/` contains vendored IndexTTS inference code and retains its own
license/disclaimer files. Do not remove those notices. Large model weights should
not be committed.
