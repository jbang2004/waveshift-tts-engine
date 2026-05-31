# WaveShift TTS Engine

Production-derived text-to-speech and HLS generation engine for long-form AI dubbing.

WaveShift TTS Engine is the standalone runtime component behind a video translation
pipeline. It takes translated, timestamped speech segments plus source media from
Cloudflare D1/R2, generates replacement speech with IndexTTS, aligns generated audio
back to the original timing, mixes it with the source media, and publishes HLS output.

This repository is early-stage OSS. The code is production-derived, but the public
interface is still stabilizing. The current goal is to make the engine reproducible,
auditable, and useful for developers building long-form dubbing, localization, and
AI audio workflows.

## What It Does

- Fetches task metadata and translated speech segments from Cloudflare D1.
- Downloads source audio/video assets from Cloudflare R2.
- Builds voice reference clips from the original speech.
- Generates translated speech with IndexTTS.
- Aligns generated speech duration to the original subtitle timing.
- Mixes vocals/background audio and video with FFmpeg.
- Publishes HLS playlists and segments for progressive playback.
- Exposes a small FastAPI surface for starting and observing TTS tasks.

## Architecture

```text
Cloudflare D1/R2
      |
      v
DataFetcher
      |
      v
AudioSegmenter -> IndexTTS -> DurationAligner -> TimestampAdjuster
      |                                  |
      +------------- MediaMixer <--------+
                       |
                       v
                  HLSManager -> Cloudflare R2
```

Main entry points:

- `app.py`: starts the FastAPI service and initializes runtime services.
- `api.py`: HTTP API for task start, task status, health, and debug inspection.
- `launcher.py`: constructs shared Cloudflare clients and pipeline services.
- `orchestrator.py`: coordinates the end-to-end TTS pipeline.
- `core/`: pipeline components for data fetch, TTS, alignment, mixing, HLS, and Cloudflare clients.
- `models/IndexTTS/`: vendored IndexTTS inference code under its upstream Apache-2.0 license.

## Current Status

| Area | Status |
| --- | --- |
| Public API | Experimental |
| Core pipeline | Working production extraction |
| CI | Syntax/compile smoke checks |
| Test coverage | In progress |
| Releases | `v0.1.0` planned |
| Supported storage | Cloudflare D1 and R2 |
| Supported TTS backend | IndexTTS |

## Requirements

- Python 3.10+
- FFmpeg available on `PATH`
- CUDA-capable GPU recommended for practical TTS throughput
- Cloudflare D1 database containing media task and transcript rows
- Cloudflare R2 bucket containing source media and receiving HLS outputs
- IndexTTS checkpoints downloaded separately

The repository includes IndexTTS inference code, but large model weights should be
downloaded from the upstream model providers according to their terms.

## Quick Start

```bash
git clone https://github.com/jbang2004/waveshift-tts-engine.git
cd waveshift-tts-engine

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edit .env with Cloudflare and model credentials

python app.py
```

The service defaults to `0.0.0.0:8000`.

Health check:

```bash
curl http://localhost:8000/api/health
```

Start a task already present in D1:

```bash
curl -X POST http://localhost:8000/api/start_tts \
  -H 'Content-Type: application/json' \
  -d '{"task_id":"YOUR_TASK_ID"}'
```

Check task status:

```bash
curl http://localhost:8000/api/task/YOUR_TASK_ID/status
```

## Configuration

Copy `.env.example` to `.env` and provide Cloudflare credentials plus any model
provider keys used for translation simplification.

Important groups:

- `SERVER_HOST`, `SERVER_PORT`, `LOG_LEVEL`
- `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_D1_DATABASE_ID`
- `CLOUDFLARE_R2_ACCESS_KEY_ID`, `CLOUDFLARE_R2_SECRET_ACCESS_KEY`, `CLOUDFLARE_R2_BUCKET_NAME`
- `TRANSLATION_MODEL` and its matching provider key
- `TTS_BATCH_SIZE`, `MAX_PARALLEL_SEGMENTS`, `BATCH_SIZE`
- `ENABLE_HLS_STORAGE`, `HLS_STORAGE_BUCKET`
- `ENABLE_VOCAL_SEPARATION`, `VOCAL_SEPARATION_MODEL`

Never commit `.env`, API keys, R2 credentials, task media, generated audio, or
downloaded model weights.

## Data Contract

The engine expects upstream workflow stages to have already created:

- a media task row containing source media paths and task status
- translated transcript segments ordered by sequence
- source audio/video objects in R2

Key fields expected by the current Cloudflare clients include:

```text
media_tasks.id
media_tasks.audio_path
media_tasks.video_path
media_tasks.status
media_tasks.target_language

transcription_segments.transcription_id
transcription_segments.sequence
transcription_segments.start_ms
transcription_segments.end_ms
transcription_segments.speaker
transcription_segments.original_text
transcription_segments.translated_text
```

R2 paths should be relative object keys, for example:

```text
users/{user_id}/{task_id}/audio.aac
users/{user_id}/{task_id}/video.mp4
```

## Development

Run the lightweight local check:

```bash
python -m compileall api.py app.py config.py launcher.py orchestrator.py core utils
```

The first public maintenance goals are:

- add focused unit tests for config validation and duration alignment
- document the D1 schema expected by `core/cloudflare/d1_client.py`
- split integration tests so they can run without live Cloudflare credentials
- publish a tagged `v0.1.0` release once the public setup path is reproducible

See [ROADMAP.md](ROADMAP.md) for the current backlog.

## Contributing

Contributions are welcome for documentation, tests, deployment guides, and small
pipeline fixes. Please read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a PR.

Good first areas:

- test coverage around path validation and timestamp math
- example D1 schema and seed data for local development
- clearer setup instructions for Linux GPU environments
- safer error messages and task status reporting

## Security

This project handles user media, generated speech, and cloud credentials. Report
security issues privately according to [SECURITY.md](SECURITY.md). Do not open
public issues containing secrets, private media URLs, raw task payloads, or
downloadable user content.

## License

The WaveShift TTS Engine code in this repository is licensed under Apache-2.0.

Vendored or third-party components keep their own notices and license terms. See
[NOTICE](NOTICE) and the license files under `models/IndexTTS/`.
