"""Running a mastering job end to end.

The sequence is the same one a mastering engineer follows:

1. **Listen to the whole thing before touching anything.** A measurement pass
   over the exact programme audio that will be delivered.
2. **Decide.** How much gain, and whether the peaks force a limiter.
3. **Rehearse.** When a limiter is involved the result is not perfectly
   predictable, so we re-measure the processed chain and correct the gain
   before committing. This costs a cheap audio-only pass, not a re-render.
4. **Print the master.** One encode, video copied through untouched.
5. **Check the print.** Measure the finished file and report what came out.
"""

from __future__ import annotations

import os
import shutil
import time
from dataclasses import dataclass, field

from . import analysis, encoders, graph, presets
from .errors import LoudMasterError, NoAudioStream, UnsupportedRequest
from .ffmpeg import Cancelled, quote_command, run_with_progress
from .mastering import MODE_LIMIT, plan_master, refine_gain
from .media import probe

OUTPUT_SUFFIX = "_loudnorm"


@dataclass
class JobSpec:
    """Everything the user chose for one job."""

    input_path: str
    output_path: str | None = None
    music: graph.MusicOptions | None = None
    preset: presets.Preset = field(default_factory=lambda: presets.get(presets.DEFAULT_PRESET))
    peak_mode: str = MODE_LIMIT
    max_limiting_db: float = 6.0
    allow_attenuation: bool = True
    tp_safety_db: float = 0.2
    audio_codec: str = encoders.AUTO
    audio_bitrate: int | None = None
    keep_subtitles: bool = True
    refine: bool = True
    verify: bool = True
    overwrite: bool = False
    dry_run: bool = False


@dataclass
class JobResult:
    spec: JobSpec
    source_info: object = None
    music_info: object = None
    source_stats: object = None
    final_stats: object = None
    plan: object = None
    encoding: object = None
    output_path: str = ""
    commands: list = field(default_factory=list)
    elapsed: float = 0.0
    notes: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    @property
    def hit_target(self):
        """Did the finished file land within half a LU of the target?"""
        if self.final_stats is None or self.final_stats.integrated is None:
            return None
        return abs(self.final_stats.integrated - self.spec.preset.target_i) <= 0.5

    @property
    def peak_is_safe(self):
        if self.final_stats is None or self.final_stats.true_peak is None:
            return None
        return self.final_stats.true_peak <= self.spec.preset.target_tp + 0.05


class Reporter:
    """Where progress and messages go. Subclass to drive a UI."""

    def log(self, message, level="info"):
        pass

    def stage(self, name, index, total):
        pass

    def progress(self, fraction, position=None, speed=None):
        pass


def default_output_path(input_path, output_dir=None, container=None):
    """``clip.mp4`` becomes ``clip_loudnorm.mp4`` next to the original."""
    directory, filename = os.path.split(os.path.abspath(input_path))
    stem, ext = os.path.splitext(filename)
    if container:
        ext = "." + container.lstrip(".")
    return os.path.join(output_dir or directory, f"{stem}{OUTPUT_SUFFIX}{ext}")


def _input_args(spec):
    """The ``-i`` block, including looping for a short music bed."""
    args = ["-i", spec.input_path]
    if spec.music is not None:
        if spec.music.loop:
            # -stream_loop is an input option: it must precede the -i it applies to.
            args += ["-stream_loop", "-1"]
        args += ["-i", spec.music.path]
    return args


def _programme_format(source_info, music_info, spec):
    """Pick the sample rate and channel layout the whole graph runs at.

    We follow the source rather than imposing a house format, because resampling
    or re-channelling would itself be a change to the audio.
    """
    primary = source_info.primary_audio
    replacing = spec.music is not None and spec.music.mode == graph.MUSIC_MODE_REPLACE
    if primary is None or replacing:
        if music_info is None or music_info.primary_audio is None:
            raise NoAudioStream("找不到可以處理的音訊。")
        primary = music_info.primary_audio

    sample_rate = primary.sample_rate
    layout = primary.effective_layout
    channels = primary.channels

    # When mixing, both branches are forced to the video's format; a mono music
    # bed under a stereo video would otherwise decide the whole master's layout.
    if spec.music is not None and not replacing and source_info.primary_audio:
        sample_rate = source_info.primary_audio.sample_rate
        layout = source_info.primary_audio.effective_layout
        channels = source_info.primary_audio.channels

    return sample_rate, layout, channels


def _measure_command(tools, spec, chains, meter_label, dual_mono):
    graph_chains = list(chains) + [
        f"[{meter_label}]{analysis.meter_filters(spec.preset, dual_mono)}[meter]"
    ]
    return (
        [tools.ffmpeg, "-hide_banner", "-y"]
        + _input_args(spec)
        + [
            "-filter_complex", graph.join(graph_chains),
            "-map", "[meter]",
            "-f", "null", "-",
        ]
    )


def _render_command(tools, spec, source_info, chains, encoding, target_path):
    container = encoders.container_key(target_path)
    # An audio-only container cannot take the picture — not even the cover art
    # an MP3 might have arrived with.
    carry_video = bool(source_info.video_streams) and encoders.supports_video(
        container
    )
    command = [tools.ffmpeg, "-hide_banner", "-y"] + _input_args(spec)
    command += ["-filter_complex", graph.join(chains)]

    if carry_video:
        command += ["-map", "0:v"]
    command += ["-map", "[out]"]

    keep_subs = (
        spec.keep_subtitles
        and source_info.subtitle_count > 0
        and container == encoders.container_key(spec.input_path)
    )
    if keep_subs:
        command += ["-map", "0:s?", "-c:s", "copy"]

    # The picture is copied bit for bit. It is never decoded, never re-encoded,
    # and therefore cannot lose a single pixel of quality.
    if carry_video:
        command += ["-c:v", "copy"]
    command += ["-c:a", encoding.codec] + encoding.args
    command += ["-map_metadata", "0", "-map_chapters", "0"]

    if container in ("mp4", "m4v", "mov", "m4a"):
        command += ["-movflags", "+faststart"]

    command += [target_path]
    return command


def _verify_command(tools, path, preset, dual_mono):
    return [
        tools.ffmpeg, "-hide_banner", "-y", "-i", path,
        "-map", "0:a:0",
        "-af", analysis.meter_filters(preset, dual_mono),
        "-f", "null", "-",
    ]


@dataclass
class _Prepared:
    """Everything derived from the inputs before any ffmpeg work starts."""

    source_info: object
    music_info: object
    sample_rate: int
    layout: str
    channels: int
    duration: float
    dual_mono: bool
    premix: list
    warnings: list = field(default_factory=list)


def _prepare(tools, spec, reporter):
    """Probe the inputs and build the programme-audio graph."""
    source_info = probe(tools, spec.input_path)
    reporter.log(f"來源：{os.path.basename(spec.input_path)}")
    reporter.log(f"　　　{source_info.describe()}")

    music_info = None
    if spec.music is not None:
        music_info = probe(tools, spec.music.path)
        if not music_info.has_audio:
            raise NoAudioStream(f"音樂檔沒有音訊：{spec.music.path}")
        reporter.log(f"音樂：{os.path.basename(spec.music.path)}")
        reporter.log(f"　　　{music_info.describe()}")

    if not source_info.has_audio and spec.music is None:
        raise NoAudioStream(
            "這個檔案沒有音軌。請匯入一個音樂檔，或改用有聲音的來源。"
        )

    sample_rate, layout, channels = _programme_format(source_info, music_info, spec)
    duration = source_info.duration or (music_info.duration if music_info else 0.0)

    prepared = _Prepared(
        source_info=source_info,
        music_info=music_info,
        sample_rate=sample_rate,
        layout=layout,
        channels=channels,
        duration=duration,
        dual_mono=channels == 1,
        premix=graph.build_premix(
            has_source_audio=source_info.has_audio,
            music=spec.music,
            sample_rate=sample_rate,
            layout=layout,
            duration=duration,
        ),
    )

    if (
        spec.music is not None
        and not spec.music.loop
        and music_info.duration < duration - 0.5
    ):
        prepared.warnings.append(
            f"音樂（{music_info.duration:.0f} 秒）比影片（{duration:.0f} 秒）短，"
            "不足的部分會是靜音。若要讓音樂重複播放，請開啟循環選項。"
        )
    return prepared


def analyse(tools, spec, reporter=None, cancel=None):
    """Measure the programme audio and report the plan without rendering."""
    reporter = reporter or Reporter()
    started = time.time()
    result = JobResult(spec=spec)

    prepared = _prepare(tools, spec, reporter)
    result.source_info = prepared.source_info
    result.music_info = prepared.music_info
    result.warnings.extend(prepared.warnings)

    reporter.stage("分析響度", 1, 1)
    command = _measure_command(tools, spec, prepared.premix, "pre", prepared.dual_mono)
    result.commands.append(command)
    stderr = run_with_progress(
        command, prepared.duration, on_progress=reporter.progress, cancel=cancel
    )
    result.source_stats = analysis.stats_from_stderr(stderr, prepared.dual_mono)
    analysis.check_measurable(result.source_stats)
    reporter.log(f"原始響度：{result.source_stats.describe()}")

    result.plan = plan_master(
        result.source_stats,
        spec.preset,
        mode=spec.peak_mode,
        max_limiting_db=spec.max_limiting_db,
        allow_attenuation=spec.allow_attenuation,
        tp_safety_db=spec.tp_safety_db,
    )
    reporter.log(f"若要輸出：{result.plan.summary()}")
    for note in result.plan.notes:
        reporter.log(note, level="note")
    for warning in result.plan.warnings:
        reporter.log(warning, level="warning")
    result.warnings.extend(result.plan.warnings)
    shortfall = result.plan.shortfall_warning()
    if shortfall:
        # An estimate here: analysis mode does not run the rehearsal pass, so a
        # limited master may land a little lower still.
        reporter.log(shortfall, level="warning")
        result.warnings.append(shortfall)

    result.elapsed = time.time() - started
    return result


def run_job(tools, spec, reporter=None, cancel=None):
    """Execute one mastering job and return a :class:`JobResult`."""
    reporter = reporter or Reporter()
    started = time.time()
    result = JobResult(spec=spec)

    # ---- Inspect the inputs -------------------------------------------------
    prepared = _prepare(tools, spec, reporter)
    source_info = prepared.source_info
    music_info = prepared.music_info
    sample_rate = prepared.sample_rate
    layout = prepared.layout
    channels = prepared.channels
    duration = prepared.duration
    dual_mono = prepared.dual_mono
    premix = prepared.premix

    result.source_info = source_info
    result.music_info = music_info
    result.warnings.extend(prepared.warnings)

    # ---- Work out where the output goes ------------------------------------
    output_path = spec.output_path or default_output_path(spec.input_path)
    output_path = os.path.abspath(output_path)
    if os.path.abspath(spec.input_path) == output_path:
        raise UnsupportedRequest("輸出檔和來源檔不能是同一個檔案。")
    if os.path.exists(output_path) and not spec.overwrite and not spec.dry_run:
        raise UnsupportedRequest(
            f"輸出檔已存在：{output_path}\n若要覆蓋請加上 --overwrite。"
        )
    parent = os.path.dirname(output_path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)
    result.output_path = output_path

    container = encoders.container_key(output_path)
    primary_video = source_info.primary_video
    if primary_video and encoders.supports_video(container) and not (
        encoders.supports_stream_copy_video(container, primary_video.codec)
    ):
        raise UnsupportedRequest(
            f"影像編碼 {primary_video.codec} 沒辦法直接放進 .{container}。"
            "改用 .mkv 輸出就能原封不動保留畫面。"
        )

    encoding = encoders.choose_audio_encoding(
        output_path,
        source_audio=source_info.primary_audio,
        requested=spec.audio_codec,
        bitrate=spec.audio_bitrate,
        channels=channels,
        tools=tools,
    )
    result.encoding = encoding
    result.notes.extend(encoding.notes)

    # Announced stages are the ones that actually cost time (an ffmpeg pass).
    # The gain calculation is instantaneous, so it does not get a number, and
    # the rehearsal only earns one once we know a limiter is involved.
    total_stages = 2 + (1 if spec.refine else 0) + (1 if spec.verify else 0)
    stage_index = 0

    # ---- 1. Measure ---------------------------------------------------------
    stage_index += 1
    reporter.stage("分析原始響度", stage_index, total_stages)
    # Measurement runs even for a dry run: without it the gain is unknown, and
    # the command we would print would not be the command we would actually run.
    command = _measure_command(tools, spec, premix, "pre", dual_mono)
    result.commands.append(command)
    stderr = run_with_progress(
        command, duration, on_progress=reporter.progress, cancel=cancel
    )
    source_stats = analysis.stats_from_stderr(stderr, dual_mono)
    analysis.check_measurable(source_stats)
    reporter.log(f"原始響度：{source_stats.describe()}")
    result.source_stats = source_stats

    # ---- 2. Decide ----------------------------------------------------------
    plan = plan_master(
        source_stats,
        spec.preset,
        mode=spec.peak_mode,
        max_limiting_db=spec.max_limiting_db,
        allow_attenuation=spec.allow_attenuation,
        tp_safety_db=spec.tp_safety_db,
    )
    result.plan = plan
    reporter.log(f"處理方式：{plan.summary()}")
    logged_notes = len(plan.notes)
    for note in plan.notes:
        reporter.log(note, level="note")
    for warning in plan.warnings:
        reporter.log(warning, level="warning")
    result.warnings.extend(plan.warnings)

    # ---- 3. Rehearse (only when a limiter is in the path) -------------------
    will_rehearse = spec.refine and plan.use_limiter
    will_verify = spec.verify and not spec.dry_run
    total_stages = (
        1
        + (1 if will_rehearse else 0)
        + (0 if spec.dry_run else 1)
        + (1 if will_verify else 0)
    )

    if will_rehearse:
        stage_index += 1
        reporter.stage("試算限幅結果", stage_index, total_stages)
        rehearsal_chains = list(premix) + [
            "[pre]"
            + graph.build_master_chain(
                plan.gain_db,
                use_limiter=True,
                ceiling_db=plan.ceiling_db,
                sample_rate=sample_rate,
                layout=layout,
                use_soxr=tools.has_soxr,
            )
            + "[processed]"
        ]
        command = _measure_command(
            tools, spec, rehearsal_chains, "processed", dual_mono
        )
        result.commands.append(command)
        stderr = run_with_progress(
            command, duration, on_progress=reporter.progress, cancel=cancel
        )
        rehearsed = analysis.stats_from_stderr(stderr, dual_mono)
        refine_gain(plan, rehearsed, spec.preset, spec.tp_safety_db)
        reporter.log(f"試算結果：{rehearsed.describe()}")
        for note in plan.notes[logged_notes:]:
            reporter.log(note, level="note")

    # Reported here, not at planning time: after the rehearsal this is a measured
    # fact rather than an estimate, and the user should only ever see one number.
    shortfall = plan.shortfall_warning()
    if shortfall:
        reporter.log(shortfall, level="warning")
        result.warnings.append(shortfall)

    # ---- 4. Print the master ------------------------------------------------
    if not spec.dry_run:
        stage_index += 1
        reporter.stage("輸出影片", stage_index, total_stages)
    master_chain = graph.build_master_chain(
        plan.gain_db,
        use_limiter=plan.use_limiter,
        ceiling_db=plan.ceiling_db,
        sample_rate=sample_rate,
        layout=layout,
        use_soxr=tools.has_soxr,
    )
    render_chains = list(premix) + [f"[pre]{master_chain}[out]"]
    temp_path = output_path + ".loudmaster-part" + os.path.splitext(output_path)[1]
    command = _render_command(
        tools,
        spec,
        source_info,
        render_chains,
        encoding,
        output_path if spec.dry_run else temp_path,
    )
    result.commands.append(command)

    if spec.dry_run:
        reporter.log(quote_command(command), level="debug")
        result.elapsed = time.time() - started
        return result

    try:
        run_with_progress(
            command, duration, on_progress=reporter.progress, cancel=cancel
        )
        shutil.move(temp_path, output_path)
    except (Cancelled, LoudMasterError):
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
        raise

    # ---- 5. Check the print -------------------------------------------------
    if will_verify:
        stage_index += 1
        reporter.stage("驗證成品", stage_index, total_stages)
        command = _verify_command(tools, output_path, spec.preset, dual_mono)
        result.commands.append(command)
        stderr = run_with_progress(
            command, duration, on_progress=reporter.progress, cancel=cancel
        )
        result.final_stats = analysis.stats_from_stderr(stderr, dual_mono)
        reporter.log(f"成品響度：{result.final_stats.describe()}")

        if result.peak_is_safe is False:
            result.warnings.append(
                f"成品真實峰值 {result.final_stats.true_peak:+.2f} dBTP "
                f"高於目標 {spec.preset.target_tp:g} dBTP。"
            )
        if result.hit_target is False and plan.shortfall_db <= 0.5:
            result.warnings.append(
                f"成品響度 {result.final_stats.integrated:.1f} LUFS "
                f"與目標 {spec.preset.target_i:g} LUFS 有落差。"
            )

    result.elapsed = time.time() - started
    return result


__all__ = [
    "JobResult",
    "JobSpec",
    "Reporter",
    "analyse",
    "default_output_path",
    "run_job",
]
