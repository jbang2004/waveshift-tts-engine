# Development Notes

## Local Environment

Use Python 3.10 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

FFmpeg must be available on `PATH`.

## Compile Check

```bash
python -m compileall api.py app.py config.py launcher.py orchestrator.py core utils
```

This check does not require Cloudflare credentials or model weights because it
only verifies Python syntax.

## Runtime Check

Runtime startup requires valid Cloudflare environment variables and IndexTTS
checkpoints.

```bash
python app.py
```

Then:

```bash
curl http://localhost:8000/api/health
```

## Testing Direction

The first test layer should avoid live Cloudflare dependencies. Prefer fixtures
and mocks for:

- transcript segment ordering
- relative R2 path validation
- timestamp adjustment
- duration-alignment boundaries
- task status update behavior

Integration tests that use live D1/R2 should be opt-in and clearly marked.
