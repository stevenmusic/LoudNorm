"""Loudness metering.

This module only ever *measures*. It never processes audio that ends up in the
master — that separation is deliberate, and it is the reason the tool can promise
it does not change the sound beyond a gain change.

The measurements follow ITU-R BS.1770 / EBU R128, which is what every streaming
platform uses to decide how loud your upload is:

* **Integrated loudness (LUFS)** — one number for the whole programme, weighted
  the way human hearing responds, gated so silence between phrases does not drag
  the average down.
* **True peak (dBTP)** — the peak of the *reconstructed analogue* waveform, found
  by 4x oversampling. It is higher than the sample peak, and it is what actually
  clips a listener's DAC or a lossy decoder.
* **Loudness range (LRA)** — how much the loudness moves over time, i.e. how
  dynamic the material is. We report it so you can see we did not squash it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .errors import SilentSource

# Below this, loudnorm has nothing meaningful to report and the material is
# silence (or so close to it that a gain calculation would be nonsense).
SILENCE_FLOOR_LUFS = -70.0


@dataclass
class LoudnessStats:
    """What the meters said about one piece of audio."""

    integrated: float | None = None
    true_peak: float | None = None
    lra: float | None = None
    threshold: float | None = None
    sample_peak: float | None = None
    clipped_samples: int = 0
    dual_mono: bool = False

    @property
    def is_silent(self):
        return self.integrated is None or self.integrated <= SILENCE_FLOOR_LUFS

    @property
    def inter_sample_overshoot(self):
        """How far the true peak sits above the sample peak, in dB.

        A large gap means the file is full of inter-sample peaks — typically a
        sign it was already squashed against 0 dBFS by a previous master.
        """
        if self.true_peak is None or self.sample_peak is None:
            return None
        return self.true_peak - self.sample_peak

    def describe(self):
        parts = []
        if self.integrated is not None:
            parts.append(f"{self.integrated:+.1f} LUFS")
        if self.true_peak is not None:
            parts.append(f"真實峰值 {self.true_peak:+.1f} dBTP")
        if self.lra is not None:
            parts.append(f"動態範圍 {self.lra:.1f} LU")
        return " ｜ ".join(parts) if parts else "（無法量測）"


def _to_float(value):
    """loudnorm emits numbers as strings, and '-inf' for silence."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lstrip("-").startswith("inf") or text == "nan":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_loudnorm_json(stderr):
    """Pull the JSON block loudnorm prints at the end of a measurement pass."""
    # The block is the last balanced {...} in the log. Scanning from the last
    # closing brace backwards is more robust than a regex against ffmpeg's
    # line-prefixed output.
    end = stderr.rfind("}")
    start = stderr.rfind("{", 0, end)
    if start == -1 or end == -1:
        return {}
    try:
        return json.loads(stderr[start : end + 1])
    except json.JSONDecodeError:
        return {}


_VOLUMEDETECT_PATTERNS = {
    "sample_peak": re.compile(r"max_volume:\s*(-?\d+(?:\.\d+)?)\s*dB"),
    "mean_volume": re.compile(r"mean_volume:\s*(-?\d+(?:\.\d+)?)\s*dB"),
}
_HISTOGRAM_0DB = re.compile(r"histogram_0db:\s*(\d+)")


def parse_volumedetect(stderr):
    """Extract sample peak and the count of samples already sitting at 0 dBFS."""
    result = {}
    for key, pattern in _VOLUMEDETECT_PATTERNS.items():
        match = pattern.search(stderr)
        if match:
            result[key] = float(match.group(1))
    match = _HISTOGRAM_0DB.search(stderr)
    if match:
        result["clipped_samples"] = int(match.group(1))
    return result


def stats_from_stderr(stderr, dual_mono=False):
    """Build :class:`LoudnessStats` from one measurement pass's log output."""
    payload = parse_loudnorm_json(stderr)
    volume = parse_volumedetect(stderr)
    return LoudnessStats(
        integrated=_to_float(payload.get("input_i")),
        true_peak=_to_float(payload.get("input_tp")),
        lra=_to_float(payload.get("input_lra")),
        threshold=_to_float(payload.get("input_thresh")),
        sample_peak=volume.get("sample_peak"),
        clipped_samples=volume.get("clipped_samples", 0),
        dual_mono=dual_mono,
    )


def meter_filters(preset, dual_mono, include_sample_peak=True):
    """The filter chain that measures — and only measures.

    ``volumedetect`` comes first so it sees the untouched signal; loudnorm's own
    output is discarded by the null muxer.
    """
    chain = []
    if include_sample_peak:
        chain.append("volumedetect")
    loudnorm = [
        f"I={preset.target_i:g}",
        f"TP={preset.target_tp:g}",
        "print_format=json",
    ]
    if dual_mono:
        # BS.1770 measures a mono file 3 LU quieter than the same material played
        # through both speakers. Platforms play it as dual mono, so we must meter
        # it the way they will hear it.
        loudnorm.append("dual_mono=true")
    chain.append("loudnorm=" + ":".join(loudnorm))
    return ",".join(chain)


def check_measurable(stats, what="來源"):
    """Raise a clear error rather than dividing by silence."""
    if stats.is_silent:
        raise SilentSource(
            f"{what}的音訊是（接近）無聲，無法計算需要提升多少音量。"
            "請確認檔案裡真的有聲音。"
        )


__all__ = [
    "LoudnessStats",
    "SILENCE_FLOOR_LUFS",
    "check_measurable",
    "meter_filters",
    "parse_loudnorm_json",
    "parse_volumedetect",
    "stats_from_stderr",
]
