"""Make whisper-api v1.2.0 start on CPU.

utils/config.py's `get_dtype()` returns the torch object `torch.float32` when there is no
CUDA, and passes it to whisperx.load_model as `compute_type` — which CTranslate2 wants as a
string, so the CPU path has never started ("incompatible constructor arguments"). This
wraps load_model to hand it "int8" instead: the string form, and the quantisation that
makes faster-whisper usable on CPU at all. Mounted like summary-sitecustomize.py; remove
when upstream returns a string from get_dtype().
"""
import whisperx

_load_model = whisperx.load_model


def load_model(*args, **kwargs):
    if not isinstance(kwargs.get("compute_type"), str):
        kwargs["compute_type"] = "int8"
    return _load_model(*args, **kwargs)


whisperx.load_model = load_model
