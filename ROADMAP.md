# Roadmap

This roadmap focuses on making WaveShift TTS Engine easier to run, review, and
maintain as a public OSS project.

## v0.1.0 - Public Baseline

- Add public README, license, security policy, contribution guide, and issue templates.
- Add lightweight CI for syntax/compile checks.
- Document the Cloudflare D1/R2 data contract.
- Document IndexTTS checkpoint setup and third-party license boundaries.
- Tag the first public release once the setup path is reproducible.

## v0.2.0 - Testable Core

- Add unit tests for config validation.
- Add unit tests for path handling and R2 key validation.
- Add unit tests for duration alignment and timestamp adjustment.
- Add fixtures for transcript segments without requiring live Cloudflare services.
- Add a mocked D1/R2 integration test path.

## v0.3.0 - Reproducible Local Demo

- Provide a minimal local task fixture.
- Add a local-only pipeline mode for generated sample media.
- Document Linux GPU setup and FFmpeg requirements.
- Publish a troubleshooting guide for common model and media failures.

## Later

- Evaluate plugin-style TTS backends beyond IndexTTS.
- Add release automation.
- Add benchmark scripts for TTS throughput and HLS generation latency.
- Improve observability around per-stage timing and task failure categories.
