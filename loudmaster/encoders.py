"""Choosing how to write the audio back out.

Changing the level means the audio must be re-encoded — there is no way around
that. What we *can* control is whether that re-encode costs any quality.

If the output container can hold lossless audio, ``auto`` writes lossless, and
the delivered signal is then bit-for-bit the decoded source with a gain applied.
If the container is MP4, we fall back to high-bitrate AAC and say so, because a
silently-lossy default would break the promise this tool makes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from .errors import UnsupportedRequest

AUTO = "auto"
COPY = "copy"

# Which encoders each container will actually accept.
CONTAINER_CODECS = {
    "mp4": {"aac", "alac", "ac3", "eac3", "mp3", "opus", "flac"},
    "m4v": {"aac", "alac", "ac3", "mp3"},
    "m4a": {"aac", "alac", "flac"},
    "mov": {"aac", "alac", "pcm_s16le", "pcm_s24le", "pcm_s32le", "ac3", "mp3"},
    "mkv": {
        "aac", "alac", "flac", "opus", "vorbis", "ac3", "eac3", "mp3",
        "pcm_s16le", "pcm_s24le", "pcm_s32le",
    },
    "webm": {"opus", "vorbis"},
    "wav": {"pcm_s16le", "pcm_s24le", "pcm_s32le", "pcm_f32le"},
    "flac": {"flac"},
    "aiff": {"pcm_s16be", "pcm_s24be"},
    "mp3": {"libmp3lame", "mp3"},
    "ogg": {"vorbis", "libvorbis", "opus", "libopus", "flac"},
    "opus": {"opus", "libopus"},
    "aac": {"aac"},
}

LOSSLESS_ENCODERS = {
    "flac", "alac",
    "pcm_s16le", "pcm_s24le", "pcm_s32le", "pcm_f32le", "pcm_s16be", "pcm_s24be",
}

# What ``auto`` reaches for first in each container.
AUTO_PREFERENCE = {
    "mkv": "flac",
    "mov": "pcm_s24le",
    "wav": "pcm_s24le",
    "flac": "flac",
    "aiff": "pcm_s24be",
    "m4a": "alac",
    "webm": "opus",
    "mp4": "aac",
    "m4v": "aac",
    "mp3": "libmp3lame",
    "ogg": "libopus",
    "opus": "libopus",
    "aac": "aac",
}

# Friendly aliases so users can say "pcm" or "wav" instead of "pcm_s24le".
CODEC_ALIASES = {
    "pcm": "pcm_s24le",
    "wav": "pcm_s24le",
    "pcm16": "pcm_s16le",
    "pcm24": "pcm_s24le",
    "pcm32": "pcm_s32le",
    "libopus": "opus",
    "aac-lc": "aac",
}


@dataclass
class AudioEncoding:
    codec: str
    args: list = field(default_factory=list)
    lossless: bool = False
    notes: list = field(default_factory=list)

    @property
    def label(self):
        for arg, value in zip(self.args, self.args[1:]):
            if arg == "-b:a":
                return f"{self.codec} {value}"
        return self.codec


def container_key(path):
    """Normalise an output path to a container key."""
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    return {"qt": "mov", "mpeg4": "mp4", "matroska": "mkv"}.get(ext, ext)


def _aac_bitrate(channels, source_bitrate):
    """Pick an AAC bitrate that is transparent for delivery.

    YouTube's own upload guidance is 384 kbps for stereo and 512 kbps for 5.1;
    we never go below that, and we go above it if the source was already richer.
    """
    per_channel = 192_000 if channels <= 2 else 96_000
    baseline = max(384_000 if channels <= 2 else 512_000, per_channel * channels)
    if source_bitrate:
        baseline = max(baseline, int(source_bitrate * 1.25))
    # The native AAC encoder gets no better past this, and some decoders baulk.
    return min(baseline, 640_000)


def choose_audio_encoding(
    output_path,
    source_audio=None,
    requested=AUTO,
    bitrate=None,
    channels=None,
    tools=None,
):
    """Decide the output audio encoder.

    ``requested`` may be ``auto``, an alias, or a concrete ffmpeg encoder name.
    """
    container = container_key(output_path)
    allowed = CONTAINER_CODECS.get(container)
    channels = channels or (source_audio.channels if source_audio else 2)
    source_bitrate = source_audio.bit_rate if source_audio else 0

    requested = (requested or AUTO).strip().lower()
    requested = CODEC_ALIASES.get(requested, requested)

    notes = []
    if requested == AUTO:
        codec = AUTO_PREFERENCE.get(container, "aac")
        if allowed and codec not in allowed:
            codec = "aac"
        if codec == "pcm_s24le" and source_audio is not None:
            # A float or >24-bit source deserves the wider word length.
            if source_audio.bits_per_raw_sample > 24 or source_audio.codec in (
                "pcm_f32le", "pcm_f64le", "pcm_s32le",
            ):
                codec = "pcm_s32le"
        if codec not in LOSSLESS_ENCODERS:
            notes.append(
                f"{container.upper()} 容器只能放有損音訊，因此音軌會重新編碼。"
                "若想完全避免二次壓縮，把輸出副檔名改成 .mov 或 .mkv 即可存成無損。"
            )
    else:
        codec = requested
        if allowed is not None and codec not in allowed and codec != COPY:
            options = ", ".join(sorted(allowed))
            raise UnsupportedRequest(
                f".{container} 容器不支援 {codec} 音訊編碼。"
                f"可用的有：{options}。"
            )

    if codec == COPY:
        return AudioEncoding(codec=COPY, lossless=True, notes=notes)

    # Prefer the well-tuned external encoders where they are compiled in; the
    # native ffmpeg equivalents are experimental or simply worse.
    if codec == "opus" and tools is not None and tools.has_encoder("libopus"):
        codec = "libopus"
    elif codec == "mp3":
        codec = "libmp3lame"

    if tools is not None and not tools.has_encoder(codec):
        # Fall back to something this build has *and* this container accepts —
        # substituting AAC into an Ogg file would only move the failure later.
        fallback = next(
            (
                candidate
                for candidate in ("aac", "libvorbis", "vorbis", "flac", "pcm_s24le")
                if (allowed is None or candidate in allowed)
                and tools.has_encoder(candidate)
            ),
            None,
        )
        if fallback is None:
            raise UnsupportedRequest(
                f"這個 ffmpeg 版本沒有 {codec} 編碼器，也找不到 .{container} 可用的替代編碼器。"
            )
        notes.append(f"這個 ffmpeg 版本沒有 {codec} 編碼器，改用 {fallback}。")
        codec = fallback

    args = []
    if codec == "aac":
        chosen = bitrate or _aac_bitrate(channels, source_bitrate)
        if isinstance(chosen, str):
            args += ["-b:a", chosen]
        else:
            args += ["-b:a", str(int(chosen))]
        # AAC is defined for a limited set of rates; let ffmpeg keep the source
        # rate when it is legal, which it is for every common video sample rate.
        args += ["-aac_coder", "twoloop"]
    elif codec in ("opus", "libopus"):
        args += ["-b:a", str(bitrate or 320_000)]
    elif codec == "flac":
        args += ["-compression_level", "8"]
    elif codec == "libmp3lame":
        args += ["-b:a", str(bitrate or 320_000)]
    elif bitrate:
        args += ["-b:a", str(bitrate)]

    return AudioEncoding(
        codec=codec,
        args=args,
        lossless=codec in LOSSLESS_ENCODERS,
        notes=notes,
    )


# Containers that hold audio only. Note that MP3 and M4A are absent: they carry
# embedded cover art as a video stream, and we want to keep it.
AUDIO_ONLY_CONTAINERS = {"wav", "flac", "aiff", "opus", "aac"}


def supports_video(container):
    """Whether this container can carry a video (or cover-art) stream at all."""
    return container not in AUDIO_ONLY_CONTAINERS


def supports_stream_copy_video(container, video_codec):
    """Whether the video bitstream can be carried into this container untouched."""
    if not video_codec:
        return True
    if not supports_video(container):
        return False
    compatible = {
        "mp4": {"h264", "hevc", "av1", "mpeg4", "vp9", "mjpeg", "prores"},
        "m4v": {"h264", "mpeg4"},
        "mov": {
            "h264", "hevc", "prores", "dnxhd", "mjpeg", "av1", "vp9", "mpeg4",
            "rawvideo", "qtrle",
        },
        "mkv": None,  # Matroska takes essentially anything.
        "webm": {"vp8", "vp9", "av1"},
    }.get(container, None)
    return compatible is None or video_codec in compatible


__all__ = [
    "AUTO",
    "COPY",
    "AudioEncoding",
    "choose_audio_encoding",
    "container_key",
    "supports_stream_copy_video",
    "supports_video",
]
