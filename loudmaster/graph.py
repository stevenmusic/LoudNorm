"""Building the ffmpeg filter graph.

Two stages are assembled here and they are kept strictly apart:

``premix``
    Everything that decides *what* the programme audio is — the video's own
    track, an imported music bed, a mix of the two, optional ducking. This runs
    identically during measurement and during the final render, so the numbers
    we measure describe exactly the signal we deliver.

``master``
    The gain (and, only if unavoidable, the true-peak limiter). This is the one
    place level is changed.

Everything runs in 64-bit float, so no amount of intermediate gain can clip or
round inside the graph — only the final encode quantises, once.
"""

from __future__ import annotations

from dataclasses import dataclass

from .mastering import LIMITER_ATTACK_MS, LIMITER_RELEASE_MS

# Working format for the whole graph: 64-bit float, source sample rate, source
# channel layout. Nothing is resampled or re-channelled behind your back.
WORKING_SAMPLE_FMT = "dbl"

MUSIC_MODE_MIX = "mix"
MUSIC_MODE_REPLACE = "replace"
MUSIC_MODES = (MUSIC_MODE_MIX, MUSIC_MODE_REPLACE)


@dataclass
class MusicOptions:
    """How an imported music file should be laid against the video."""

    path: str
    mode: str = MUSIC_MODE_MIX
    gain_db: float = 0.0
    loop: bool = False
    offset: float = 0.0
    fade_in: float = 0.0
    fade_out: float = 0.0
    duck: bool = False
    duck_threshold: float = 0.05
    duck_ratio: float = 8.0
    duck_attack: float = 20.0
    duck_release: float = 400.0


def db_to_linear(db):
    return 10.0 ** (db / 20.0)


def _fmt(value):
    """Format a float for a filter argument without exponent notation."""
    return f"{value:.6f}".rstrip("0").rstrip(".") or "0"


def anchor(sample_rate, layout):
    """Force the working format, so later filters cannot silently renegotiate."""
    return (
        f"aformat=sample_fmts={WORKING_SAMPLE_FMT}"
        f":sample_rates={sample_rate}"
        f":channel_layouts={layout}"
    )


def _bounded(duration):
    """Trim to the programme length and pad if we came up short."""
    return f"atrim=0:{_fmt(duration)},asetpts=N/SR/TB,apad=whole_dur={_fmt(duration)}"


def build_music_chain(options, sample_rate, layout, duration):
    """Filters that turn the imported music file into a bed of the right shape."""
    chain = [anchor(sample_rate, layout)]

    if options.offset > 0:
        chain.append(f"adelay=delays={_fmt(options.offset * 1000)}:all=1")

    if abs(options.gain_db) > 1e-9:
        chain.append(f"volume={_fmt(options.gain_db)}dB:precision=double")

    chain.append(_bounded(duration))

    if options.fade_in > 0:
        chain.append(f"afade=t=in:st={_fmt(options.offset)}:d={_fmt(options.fade_in)}")
    if options.fade_out > 0:
        start = max(0.0, duration - options.fade_out)
        chain.append(f"afade=t=out:st={_fmt(start)}:d={_fmt(options.fade_out)}")

    return ",".join(chain)


def build_premix(
    has_source_audio,
    music=None,
    sample_rate=48000,
    layout="stereo",
    duration=0.0,
    source_label="0:a:0",
    music_label="1:a:0",
    out_label="pre",
):
    """Assemble the programme audio.

    Returns a list of ``filter_complex`` chains whose last output is
    ``[out_label]``.
    """
    chains = []

    if music is None:
        if not has_source_audio:
            raise ValueError("影片沒有音軌，也沒有匯入音樂檔，沒有東西可以處理。")
        chains.append(f"[{source_label}]{anchor(sample_rate, layout)}[{out_label}]")
        return chains

    music_chain = build_music_chain(music, sample_rate, layout, duration)

    if music.mode == MUSIC_MODE_REPLACE or not has_source_audio:
        chains.append(f"[{music_label}]{music_chain}[{out_label}]")
        return chains

    if music.mode != MUSIC_MODE_MIX:
        raise ValueError(f"未知的音樂混合模式：{music.mode}")

    source_chain = f"{anchor(sample_rate, layout)},{_bounded(duration)}"

    if music.duck:
        # Split the original audio: one copy is mixed, the other keys the
        # compressor so the music steps back whenever there is dialogue.
        chains.append(f"[{source_label}]{source_chain},asplit=2[src][key]")
        chains.append(f"[{music_label}]{music_chain}[bed]")
        chains.append(
            f"[bed][key]sidechaincompress="
            f"threshold={_fmt(music.duck_threshold)}"
            f":ratio={_fmt(music.duck_ratio)}"
            f":attack={_fmt(music.duck_attack)}"
            f":release={_fmt(music.duck_release)}[ducked]"
        )
        mix_inputs = "[src][ducked]"
    else:
        chains.append(f"[{source_label}]{source_chain}[src]")
        chains.append(f"[{music_label}]{music_chain}[bed]")
        mix_inputs = "[src][bed]"

    # normalize=0 is essential: amix otherwise divides every input by the number
    # of inputs, which would quietly halve the level before we ever measure it.
    chains.append(
        f"{mix_inputs}amix=inputs=2:duration=longest"
        f":dropout_transition=0:normalize=0[{out_label}]"
    )
    return chains


def build_master_chain(
    gain_db,
    use_limiter=False,
    ceiling_db=-1.0,
    sample_rate=48000,
    layout="stereo",
    use_soxr=True,
):
    """The level stage: gain, and a true-peak limiter only when needed."""
    chain = []

    if abs(gain_db) > 1e-9:
        # precision=double keeps the multiply exact rather than rounding to
        # 32-bit float on the way through.
        chain.append(f"volume={_fmt(gain_db)}dB:precision=double")

    if use_limiter:
        oversampled = min(sample_rate * 4, 192000)
        resampler = ":resampler=soxr:precision=28" if use_soxr else ""
        if oversampled > sample_rate:
            # Limiting at the source rate only controls sample peaks. Peaks
            # *between* samples are what clip a DAC or a lossy decoder, so we
            # oversample, limit there, and come back down.
            chain.append(f"aresample={oversampled}{resampler}")
        chain.append(
            f"alimiter=limit={_fmt(db_to_linear(ceiling_db))}"
            f":attack={_fmt(LIMITER_ATTACK_MS)}"
            f":release={_fmt(LIMITER_RELEASE_MS)}"
            # level=false stops alimiter from helpfully raising everything back
            # up to the ceiling; latency=1 compensates its lookahead delay so
            # the audio stays frame-aligned with the picture.
            ":asc=1:level=false:latency=1"
        )
        if oversampled > sample_rate:
            chain.append(f"aresample={sample_rate}{resampler}")

    chain.append(anchor(sample_rate, layout))
    return ",".join(chain)


def join(chains):
    """Render a list of chains as one ``-filter_complex`` argument."""
    return ";".join(chains)


__all__ = [
    "MUSIC_MODES",
    "MUSIC_MODE_MIX",
    "MUSIC_MODE_REPLACE",
    "MusicOptions",
    "anchor",
    "build_master_chain",
    "build_music_chain",
    "build_premix",
    "db_to_linear",
    "join",
]
