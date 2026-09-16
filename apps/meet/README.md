# Meet — video calls, with transcripts delivered to Docs

`office-meet`: La Suite Meet at the pinned git tag (chart `src/helm/meet`), plus our own
`meet-whisperx` Deployment for speech-to-text. LiveKit (`apps/livekit`) carries the media.

## Files

| File | What |
|---|---|
| `deps.yaml` | Postgres, Valkey cache, Garage bucket `meet`, OIDC client, SMTP, generated Django secrets |
| `tokens.yaml` | the five shared tokens read into the key names each process wants; the by-hand HF token |
| `release.yaml` | the upstream chart; secrets attached by `postRenderers` (the chart has no `envFrom`) |
| `whisperx.yaml` | the STT API: PVC for models, Deployment, Service |
| `surround.yaml` | routes and the (unenforced) egress policy |
| `default.conf` | the frontend nginx config, upstream's plus the switcher injection |
| `check-secrets.sh` | asserts which workloads get which Secrets; run after a chart bump |

The switcher script itself is `apps/switcher.js`, shared with Drive.

## The transcript pipeline

```
browser: "start transcript"
 └─ backend → LiveKit: RoomCompositeEgress, audio only, OGG → bucket meet/recordings/
     └─ LiveKit → backend webhook (egress_ended)          via the public URL (SECURE_SSL_REDIRECT 301s plain http), signed with the API key
         └─ backend → summary API  POST /api/v2/async-jobs/transcribe/   bearer: `summary` token
             └─ celery-transcribe: presigned download, ffmpeg, POST whisperx /v1/audio/transcriptions
                 ├─ → Docs  POST /api/v1.0/documents/create-for-owner/   bearer: `docs` token
                 └─ celery-summary-backend → backend  /api/v1.0/recordings/external-process-hook/   bearer: `webhook` token
```

- Every hop's token is drawn once in `platform/secrets/service-tokens.yaml` and read at both
  ends through `ClusterSecretStore office-data` (tokens.yaml here; `apps/docs/meet-token.yaml`;
  `apps/livekit/secrets.yaml`).
- The summary service's Celery runs on the Valkey **broker**; the backend's own Celery is
  off (`CELERY_ENABLED=false`) — nothing in this path uses it.
- Summaries (the LLM step) are off: `IS_SUMMARY_ENABLED=false`, `celerySummarize` at zero
  replicas, placeholder `LLM_*` because the settings class requires them. Transcripts land
  in Docs as-is, owned by whoever pressed the button.
- Screen recording is not enabled (`RECORDING_WORKER_CLASSES` lists `transcript` only).

## whisperx on CPU — what to expect

No GPU on this node. `lasuite/whisper-api:v1.2.0` (the last tag; 9 GB, CUDA base, falls
back to CPU) with `--model small`. The summary worker gives up on a transcription after
**ten minutes** (a hard-coded read timeout), and pyannote diarization on CPU is the slow
half — so a long meeting can fail transcription outright rather than slowly. If that is the
complaint: a GPU node, or `WHISPERX_BASE_URL` at an external WhisperX-compatible endpoint
(the summary service expects `response_format=diarized_json`, which plain OpenAI does not
return). `main` upstream made the model an env var (`TRANSCRIBE_MODEL`) — the first tag past
v1.2.0 changes `args` in whisperx.yaml.

First start downloads the models into the PVC (minutes); the startup probe allows 20.
`whisperx-sitecustomize.py` fixes the image's CPU start (it passes a torch dtype where CTranslate2 wants a string) and picks `int8`. `HF_TOKEN` is required and is the one by-hand credential — `docs/bootstrap.md` §4c.

## The gaufre

Meet ships no switcher and no hook for one. `default.conf` adds a `sub_filter` that appends
`<script src="/custom/switcher.js">` to every HTML response and serves the file from the same
ConfigMap (`meet-frontend`, mounted over the image's `default.conf` via
`frontend.extraVolumes`). On a chart bump, diff `default.conf` against upstream's
`src/frontend/default.conf`. The mount point in the page is `nav > div` (layout/Header.tsx);
in a call there is no header and the button falls back to a fixed position.

## Verifying

```sh
kubectl -n office-meet get pods                         # backend, frontend, summary, celery-transcribe-default, celery-summary-backend, whisperx Running; 4 at 0 replicas
./apps/meet/check-secrets.sh                            # after a chart bump
kubectl -n office-meet logs deploy/meet-whisperx | tail  # "Uvicorn running" after the model loads
```
End to end: sign in at `https://meet.${BASE_DOMAIN}`, start a meeting, start a transcript,
talk, stop it. Backend logs show the `egress_ended` webhook; `meet-celery-transcribe-default`
logs the whisperx call; a document titled with the room and date appears in Docs; the panel
in Meet says it was sent.
