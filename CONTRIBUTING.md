# Contributing

Thanks for helping improve WaveShift TTS Engine.

This project is early-stage OSS extracted from a production media pipeline. The
highest-value contributions right now are tests, documentation, reproducible setup
instructions, and small reliability fixes.

## Development Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Fill `.env` with local or development credentials. Do not use production secrets
for local testing.

## Local Checks

Run this before opening a PR:

```bash
python -m compileall api.py app.py config.py launcher.py orchestrator.py core utils
```

If your change touches a specific function, include a focused manual test note or
automated test where practical.

## Pull Request Guidelines

- Keep PRs focused on one behavior, bug, or documentation area.
- Explain why the change is needed and how it was verified.
- Do not commit media files, generated audio, checkpoints, API keys, `.env`, or
  production task data.
- Prefer small, reviewable refactors over broad rewrites.
- Preserve the current Cloudflare D1/R2 data contract unless the PR explicitly
  updates docs and migration notes.

## Issue Guidelines

For bugs, include:

- Python version and OS
- GPU/CUDA details if relevant
- FFmpeg version
- sanitized config values
- sanitized logs
- expected behavior and actual behavior

Do not include secrets, private R2 URLs, downloadable user media, raw access
tokens, or complete production task payloads.

## Maintainer Workflow

Maintainers should:

- triage issues by reproducibility and data-contract impact
- keep README, ROADMAP, and SECURITY files current
- tag public releases once setup and migration notes are clear
- avoid merging changes that require private infrastructure to understand
