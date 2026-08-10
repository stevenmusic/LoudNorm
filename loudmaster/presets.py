"""Delivery targets for the platforms people actually upload to.

Every streaming service runs its own loudness normalisation on playback. The
numbers below are the published (or well-measured) targets each one aims for,
expressed as EBU R128 integrated loudness plus a true-peak ceiling.

A note on why the peak ceiling is never 0 dBTP: platforms re-encode uploads to
a lossy codec, and lossy codecs reconstruct a waveform whose inter-sample peaks
sit slightly above the original samples. Leaving 1 dB of true-peak headroom is
what stops that reconstruction from clipping on the listener's device.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Preset:
    key: str
    label: str
    target_i: float
    target_tp: float
    note: str = ""


PRESETS = {
    "youtube": Preset(
        "youtube", "YouTube", -14.0, -1.0,
        "YouTube 播放時會把過響的影片轉小聲，但不會把小聲的轉大聲；"
        "做到 -14 LUFS 就是不被扣、也不吃虧的位置。",
    ),
    "youtube-music": Preset(
        "youtube-music", "YouTube Music", -14.0, -1.0,
        "與 YouTube 主站相同的正規化目標。",
    ),
    "spotify": Preset(
        "spotify", "Spotify", -14.0, -1.0,
        "Spotify 預設的 Normal 音量模式目標。",
    ),
    "apple": Preset(
        "apple", "Apple Music / Podcasts", -16.0, -1.0,
        "Apple 的 Sound Check 目標。",
    ),
    "tiktok": Preset(
        "tiktok", "TikTok / Instagram / Reels", -14.0, -1.0,
        "手機短影音平台實測的正規化目標。",
    ),
    "podcast": Preset(
        "podcast", "Podcast（語音為主）", -16.0, -1.0,
        "多數 Podcast 平台建議的語音節目目標。",
    ),
    "broadcast": Preset(
        "broadcast", "廣播電視 EBU R128", -23.0, -1.0,
        "歐洲廣播規範 EBU R128 / ITU-R BS.1770 的交件標準。",
    ),
    "atsc": Preset(
        "atsc", "美規電視 ATSC A/85", -24.0, -2.0,
        "北美電視播出標準。",
    ),
}

DEFAULT_PRESET = "youtube"


def get(key):
    """Look a preset up by key, case-insensitively."""
    try:
        return PRESETS[key.strip().lower()]
    except KeyError:
        known = ", ".join(sorted(PRESETS))
        raise KeyError(f"未知的平台預設「{key}」。可用的有：{known}") from None


def custom(target_i, target_tp, label="自訂"):
    """Build a one-off preset from explicit numbers."""
    return Preset("custom", label, float(target_i), float(target_tp), "")


def listing():
    """Rows of ``(key, label, target)`` for help text and the GUI dropdown."""
    return [
        (preset.key, preset.label, f"{preset.target_i:g} LUFS / {preset.target_tp:g} dBTP")
        for preset in PRESETS.values()
    ]


__all__ = ["DEFAULT_PRESET", "PRESETS", "Preset", "custom", "get", "listing"]
