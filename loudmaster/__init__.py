"""LoudMaster — bring a video up to broadcast/streaming loudness, transparently.

The public surface is deliberately small::

    from loudmaster import discover, JobSpec, run_job, presets

    tools = discover()
    spec = JobSpec(input_path="clip.mp4", preset=presets.get("youtube"))
    result = run_job(tools, spec)
"""

from .errors import (
    FFmpegFailed,
    FFmpegNotFound,
    LoudMasterError,
    NoAudioStream,
    SilentSource,
    UnsupportedRequest,
)
from .ffmpeg import CancelToken, Cancelled, discover
from .graph import MUSIC_MODE_MIX, MUSIC_MODE_REPLACE, MusicOptions
from .mastering import MODE_LIMIT, MODE_SAFE, MasterPlan, plan_master
from .pipeline import JobResult, JobSpec, Reporter, default_output_path, run_job
from . import presets

__version__ = "1.0.0"
__all__ = [
    "CancelToken",
    "Cancelled",
    "FFmpegFailed",
    "FFmpegNotFound",
    "JobResult",
    "JobSpec",
    "LoudMasterError",
    "MODE_LIMIT",
    "MODE_SAFE",
    "MUSIC_MODE_MIX",
    "MUSIC_MODE_REPLACE",
    "MasterPlan",
    "MusicOptions",
    "NoAudioStream",
    "Reporter",
    "SilentSource",
    "UnsupportedRequest",
    "__version__",
    "default_output_path",
    "discover",
    "plan_master",
    "presets",
    "run_job",
]
