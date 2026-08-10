"""Exception types shared across LoudMaster."""


class LoudMasterError(Exception):
    """Base class for every error this tool raises on purpose."""


class FFmpegNotFound(LoudMasterError):
    """ffmpeg or ffprobe could not be located."""


class FFmpegFailed(LoudMasterError):
    """An ffmpeg/ffprobe invocation exited non-zero."""

    def __init__(self, message, command=None, stderr=""):
        super().__init__(message)
        self.command = command or []
        self.stderr = stderr


class NoAudioStream(LoudMasterError):
    """The source has no audio to work with."""


class SilentSource(LoudMasterError):
    """The source is digital silence, so loudness is undefined."""


class UnsupportedRequest(LoudMasterError):
    """The combination of options asked for cannot be honoured."""
