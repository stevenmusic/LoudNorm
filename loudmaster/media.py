"""Reading what is actually inside a media file, via ffprobe."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from .errors import FFmpegFailed, LoudMasterError
from .ffmpeg import run

# Audio codecs that carry the samples untouched. If the source is one of these,
# we can keep the master lossless end to end.
LOSSLESS_AUDIO_CODECS = {
    "pcm_s16le", "pcm_s16be", "pcm_s24le", "pcm_s24be", "pcm_s32le", "pcm_s32be",
    "pcm_f32le", "pcm_f32be", "pcm_f64le", "pcm_f64be", "pcm_s8", "pcm_u8",
    "flac", "alac", "wavpack", "tta", "truehd", "mlp", "ape",
}


@dataclass
class AudioStream:
    index: int
    codec: str = ""
    sample_rate: int = 48000
    channels: int = 2
    channel_layout: str = ""
    bit_rate: int = 0
    bits_per_raw_sample: int = 0
    language: str = ""
    title: str = ""

    @property
    def is_lossless(self):
        return self.codec in LOSSLESS_AUDIO_CODECS

    @property
    def effective_layout(self):
        """A layout string ffmpeg will accept, even when probing came up empty."""
        if self.channel_layout and "unknown" not in self.channel_layout:
            return self.channel_layout
        return {1: "mono", 2: "stereo", 6: "5.1", 8: "7.1"}.get(
            self.channels, f"{self.channels}c"
        )


@dataclass
class VideoStream:
    index: int
    codec: str = ""
    width: int = 0
    height: int = 0
    frame_rate: str = ""
    pix_fmt: str = ""
    bit_rate: int = 0
    is_attached_pic: bool = False

    @property
    def resolution(self):
        return f"{self.width}x{self.height}" if self.width else "?"


@dataclass
class MediaInfo:
    path: str
    duration: float = 0.0
    format_name: str = ""
    size: int = 0
    bit_rate: int = 0
    video_streams: list = field(default_factory=list)
    audio_streams: list = field(default_factory=list)
    subtitle_count: int = 0

    @property
    def has_video(self):
        return any(not stream.is_attached_pic for stream in self.video_streams)

    @property
    def has_audio(self):
        return bool(self.audio_streams)

    @property
    def primary_audio(self):
        return self.audio_streams[0] if self.audio_streams else None

    @property
    def primary_video(self):
        for stream in self.video_streams:
            if not stream.is_attached_pic:
                return stream
        return None

    def describe(self):
        """A one-or-two line human summary for logs and the GUI."""
        parts = []
        video = self.primary_video
        if video:
            rate = _pretty_rate(video.frame_rate)
            parts.append(
                f"影像 {video.codec} {video.resolution}"
                + (f" {rate}fps" if rate else "")
            )
        audio = self.primary_audio
        if audio:
            parts.append(
                f"音訊 {audio.codec} {audio.sample_rate}Hz "
                f"{audio.effective_layout}"
                + (f" {audio.bit_rate // 1000}kbps" if audio.bit_rate else "")
            )
        parts.append(f"長度 {format_duration(self.duration)}")
        return " ｜ ".join(parts)


def _pretty_rate(rate):
    """Turn ffprobe's '30000/1001' into '29.97'."""
    if not rate or "/" not in rate:
        return rate or ""
    numerator, _, denominator = rate.partition("/")
    try:
        numerator, denominator = float(numerator), float(denominator)
    except ValueError:
        return ""
    if denominator == 0:
        return ""
    value = numerator / denominator
    return f"{value:.0f}" if abs(value - round(value)) < 0.001 else f"{value:.2f}"


def format_duration(seconds):
    """Seconds to ``h:mm:ss`` / ``m:ss``."""
    if not seconds or seconds < 0:
        return "0:00"
    seconds = int(round(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _as_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def probe(tools, path):
    """Return a :class:`MediaInfo` for ``path``."""
    if not os.path.isfile(path):
        raise LoudMasterError(f"找不到檔案：{path}")

    command = [
        tools.ffprobe, "-hide_banner", "-v", "error",
        "-print_format", "json", "-show_format", "-show_streams", path,
    ]
    try:
        _, stdout, _ = run(command)
        payload = json.loads(stdout)
    except FFmpegFailed as exc:
        raise LoudMasterError(f"無法讀取檔案（格式可能不支援）：{path}\n{exc}") from exc
    except json.JSONDecodeError as exc:
        raise LoudMasterError(f"ffprobe 回傳的資料無法解析：{path}") from exc

    container = payload.get("format", {})
    info = MediaInfo(
        path=path,
        duration=_as_float(container.get("duration")),
        format_name=container.get("format_name", ""),
        size=_as_int(container.get("size")),
        bit_rate=_as_int(container.get("bit_rate")),
    )

    for stream in payload.get("streams", []):
        kind = stream.get("codec_type")
        index = _as_int(stream.get("index"))
        if kind == "video":
            info.video_streams.append(
                VideoStream(
                    index=index,
                    codec=stream.get("codec_name", ""),
                    width=_as_int(stream.get("width")),
                    height=_as_int(stream.get("height")),
                    frame_rate=stream.get("r_frame_rate", ""),
                    pix_fmt=stream.get("pix_fmt", ""),
                    bit_rate=_as_int(stream.get("bit_rate")),
                    is_attached_pic=bool(
                        stream.get("disposition", {}).get("attached_pic")
                    ),
                )
            )
        elif kind == "audio":
            tags = stream.get("tags", {}) or {}
            info.audio_streams.append(
                AudioStream(
                    index=index,
                    codec=stream.get("codec_name", ""),
                    sample_rate=_as_int(stream.get("sample_rate"), 48000),
                    channels=_as_int(stream.get("channels"), 2),
                    channel_layout=stream.get("channel_layout", ""),
                    bit_rate=_as_int(stream.get("bit_rate")),
                    bits_per_raw_sample=_as_int(stream.get("bits_per_raw_sample")),
                    language=tags.get("language", ""),
                    title=tags.get("title", ""),
                )
            )
        elif kind == "subtitle":
            info.subtitle_count += 1

    if info.duration <= 0:
        # Some containers only carry duration on the streams themselves.
        for stream in payload.get("streams", []):
            info.duration = max(info.duration, _as_float(stream.get("duration")))

    return info


__all__ = [
    "AudioStream",
    "MediaInfo",
    "VideoStream",
    "format_duration",
    "probe",
]
