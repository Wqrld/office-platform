"""Lengthen the summary worker's speech-to-text timeout.

summary/core/celery_worker.py calls whisperx with `timeout=(60, 10 * 60)` — a hard-coded
ten-minute read timeout, "mimicking OpenAI's". Against a GPU-backed API that is generous;
against whisperx on CPU (apps/meet/whisperx.yaml) it is shorter than a long meeting takes to
transcribe, so the worker gives up on exactly the transcripts that took longest to produce.

Python imports `sitecustomize` at interpreter start from anywhere on PYTHONPATH, so this
file, mounted into the transcribe worker with PYTHONPATH set (release.yaml), wraps
`requests.post` and raises the read timeout for that one URL. Nothing else changes: the
module does `import requests` and calls `requests.post`, so the wrapper is seen.

Remove when upstream makes the timeout a setting (the fix to propose: `whisperx_timeout`
in summary/core/config.py, one line at the call site).
"""
import os

import requests

_post = requests.post
_READ_TIMEOUT = int(os.environ.get("WHISPERX_READ_TIMEOUT", "3600"))


def post(url, *args, **kwargs):
    if str(url).endswith("/audio/transcriptions"):
        kwargs["timeout"] = (60, _READ_TIMEOUT)
    return _post(url, *args, **kwargs)


requests.post = post
