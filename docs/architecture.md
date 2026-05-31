# Architecture

WaveShift TTS Engine is organized as a service dictionary rather than a heavy
framework. `launcher.py` creates shared clients and pipeline components, then
`api.py` exposes the service through FastAPI endpoints.

## Pipeline Stages

1. `DataFetcher` loads task metadata and transcript segments from Cloudflare D1.
2. `DataFetcher` downloads source audio/video from Cloudflare R2.
3. `AudioSegmenter` prepares speech reference clips for the target speaker.
4. `MyIndexTTSDeployment` generates translated speech.
5. `DurationAligner` adjusts generated speech to fit original timing windows.
6. `TimestampAdjuster` updates segment timing after generation.
7. `MediaMixer` combines generated speech, source media, and background audio.
8. `HLSManager` publishes playlist and segment output.
9. `MainOrchestrator` updates task status and cleans temporary resources.

## Runtime Shape

```text
app.py
  -> launcher.create_services()
      -> ClientManager
      -> DataFetcher
      -> AudioSegmenter
      -> Simplifier
      -> MyIndexTTSDeployment
      -> DurationAligner
      -> TimestampAdjuster
      -> MediaMixer
      -> HLSManager
      -> MainOrchestrator
  -> api.set_services()
  -> uvicorn.run()
```

## Cloudflare Boundary

The engine assumes upstream services own upload, transcription, translation, and
task creation. This service owns the TTS/HLS stage only.

External durable dependencies:

- Cloudflare D1 for task and transcript rows
- Cloudflare R2 for source media and HLS output

The current implementation expects relative R2 object keys rather than public
URLs. This avoids URL parsing and makes object access explicit.

## Failure Handling

The orchestrator updates task status to `processing`, `completed`, or `error`.
Individual stages log detailed errors, and top-level failures are written back
to D1 through the task status updater.

Future work should split recoverable segment-level failures from terminal
pipeline failures.
