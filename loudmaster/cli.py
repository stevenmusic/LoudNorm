"""Command line interface."""

from __future__ import annotations

import argparse
import json
import os
import sys
import unicodedata

from . import __version__, encoders, presets
from .errors import LoudMasterError
from .ffmpeg import CancelToken, Cancelled, discover, quote_command
from .graph import MUSIC_MODES, MUSIC_MODE_MIX, MusicOptions
from .mastering import (
    DEFAULT_MAX_LIMITING_DB,
    DEFAULT_TP_SAFETY_DB,
    MODE_LIMIT,
    PEAK_MODES,
)
from .media import format_duration
from .pipeline import JobSpec, Reporter, analyse, default_output_path, run_job

LEVEL_MARKS = {
    "info": "  ",
    "note": "· ",
    "warning": "⚠ ",
    "error": "✗ ",
    "debug": "  ",
}


class ConsoleReporter(Reporter):
    """Prints progress to the terminal, with a live bar when attached to a tty."""

    def __init__(self, quiet=False, stream=None):
        self.quiet = quiet
        self.stream = stream or sys.stderr
        self.interactive = hasattr(self.stream, "isatty") and self.stream.isatty()
        self._stage = ""
        self._bar_open = False

    def _clear_bar(self):
        if self._bar_open:
            self.stream.write("\r\033[K")
            self._bar_open = False

    def log(self, message, level="info"):
        if self.quiet and level in ("info", "note", "debug"):
            return
        self._clear_bar()
        self.stream.write(LEVEL_MARKS.get(level, "  ") + message + "\n")
        self.stream.flush()

    def stage(self, name, index, total):
        self._stage = name
        if self.quiet:
            return
        self._clear_bar()
        self.stream.write(f"▸ [{index}/{total}] {name}\n")
        self.stream.flush()

    def progress(self, fraction, position=None, speed=None):
        if self.quiet or not self.interactive or fraction is None:
            return
        width = 28
        filled = int(round(fraction * width))
        bar = "█" * filled + "░" * (width - filled)
        speed_text = f"  {speed:.1f}x" if speed else ""
        self.stream.write(f"\r  {bar} {fraction * 100:5.1f}%{speed_text}")
        self.stream.flush()
        self._bar_open = True

    def done(self):
        self._clear_bar()


def build_parser():
    parser = argparse.ArgumentParser(
        prog="loudmaster",
        description=(
            "把影片／音訊的音量提升到 YouTube 等平台的標準響度，"
            "不破音、不改變畫質。"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "範例：\n"
            "  loudmaster 影片.mp4\n"
            "      以 YouTube 標準（-14 LUFS / -1 dBTP）輸出 影片_loudnorm.mp4\n\n"
            "  loudmaster *.mp4 -d 輸出資料夾\n"
            "      批次處理\n\n"
            "  loudmaster 影片.mp4 --music 配樂.wav --music-gain -8 --duck\n"
            "      混入背景音樂，並在有人聲時自動把音樂壓低\n\n"
            "  loudmaster 影片.mp4 -o 成品.mkv\n"
            "      輸出成 MKV，音訊自動存成 FLAC 無損（完全不二次壓縮）\n\n"
            "  loudmaster 影片.mp4 --analyze\n"
            "      只量測、不輸出\n"
        ),
    )
    parser.add_argument("inputs", nargs="*", help="要處理的影片或音訊檔（可多個）")

    output = parser.add_argument_group("輸出")
    output.add_argument("-o", "--output", help="輸出檔名（只能搭配單一輸入檔）")
    output.add_argument("-d", "--output-dir", help="輸出資料夾")
    output.add_argument(
        "--overwrite", action="store_true", help="覆蓋已存在的輸出檔"
    )

    target = parser.add_argument_group("響度目標")
    target.add_argument(
        "-p", "--preset", default=presets.DEFAULT_PRESET,
        help="平台預設（預設：%(default)s）。用 --list-presets 看全部",
    )
    target.add_argument(
        "--target-lufs", type=float, help="自訂整合響度目標，例如 -14"
    )
    target.add_argument(
        "--target-tp", type=float, help="自訂真實峰值上限，例如 -1"
    )
    target.add_argument(
        "--list-presets", action="store_true", help="列出所有平台預設後結束"
    )

    processing = parser.add_argument_group("處理方式")
    processing.add_argument(
        "--mode", choices=PEAK_MODES, default=MODE_LIMIT,
        help=(
            "峰值處理：limit＝必要時用真實峰值限幅器完全達標（預設）；"
            "safe＝絕不做動態處理，寧可小聲一點"
        ),
    )
    processing.add_argument(
        "--max-limiting", type=float, default=DEFAULT_MAX_LIMITING_DB,
        metavar="DB",
        help="限幅器最多可吸收多少 dB（預設：%(default)s）。越大越響、也越扁",
    )
    processing.add_argument(
        "--no-attenuate", action="store_true",
        help="來源比目標大聲時不要調小（預設會調小）",
    )
    processing.add_argument(
        "--tp-safety", type=float, default=DEFAULT_TP_SAFETY_DB, metavar="DB",
        help="真實峰值的額外安全邊界（預設：%(default)s）",
    )
    processing.add_argument(
        "--no-refine", action="store_true",
        help="跳過限幅試算（比較快，但達標精度略差）",
    )
    processing.add_argument(
        "--no-verify", action="store_true", help="跳過成品驗證量測"
    )

    music = parser.add_argument_group("匯入音樂")
    music.add_argument("--music", help="要加入的音樂檔")
    music.add_argument(
        "--music-mode", choices=MUSIC_MODES, default=MUSIC_MODE_MIX,
        help="mix＝與原音混合（預設）；replace＝取代原本的聲音",
    )
    music.add_argument(
        "--music-gain", type=float, default=0.0, metavar="DB",
        help="音樂的相對音量，例如 -8（預設：0）",
    )
    music.add_argument(
        "--music-loop", action="store_true", help="音樂比影片短時自動重複"
    )
    music.add_argument(
        "--music-offset", type=float, default=0.0, metavar="SEC",
        help="音樂延後幾秒開始",
    )
    music.add_argument(
        "--music-fade-in", type=float, default=0.0, metavar="SEC", help="音樂淡入秒數"
    )
    music.add_argument(
        "--music-fade-out", type=float, default=0.0, metavar="SEC", help="音樂淡出秒數"
    )
    music.add_argument(
        "--duck", action="store_true",
        help="自動避讓：原音（人聲）出現時把音樂壓低",
    )

    audio = parser.add_argument_group("音訊編碼")
    audio.add_argument(
        "--audio-codec", default=encoders.AUTO,
        help="auto（預設）／aac／flac／alac／pcm／opus。auto 會在容器允許時選無損",
    )
    audio.add_argument(
        "--audio-bitrate", type=int, help="有損編碼的位元率（bps），例如 384000"
    )
    audio.add_argument(
        "--no-subtitles", action="store_true", help="不要保留字幕軌"
    )

    misc = parser.add_argument_group("其他")
    misc.add_argument(
        "--analyze", "--analyse", action="store_true", dest="analyze",
        help="只量測響度並顯示建議，不輸出檔案",
    )
    misc.add_argument("--json", action="store_true", help="以 JSON 輸出結果")
    misc.add_argument(
        "--dry-run", action="store_true", help="只印出將執行的 ffmpeg 指令"
    )
    misc.add_argument("--ffmpeg", help="ffmpeg 執行檔路徑")
    misc.add_argument("--ffprobe", help="ffprobe 執行檔路徑")
    misc.add_argument("--gui", action="store_true", help="開啟圖形介面")
    misc.add_argument("-q", "--quiet", action="store_true", help="只顯示警告與錯誤")
    misc.add_argument("--version", action="version", version=f"LoudMaster {__version__}")
    return parser


def resolve_preset(args):
    if args.target_lufs is not None or args.target_tp is not None:
        base = presets.get(args.preset)
        return presets.custom(
            args.target_lufs if args.target_lufs is not None else base.target_i,
            args.target_tp if args.target_tp is not None else base.target_tp,
        )
    return presets.get(args.preset)


def build_spec(args, input_path, preset):
    music = None
    if args.music:
        music = MusicOptions(
            path=args.music,
            mode=args.music_mode,
            gain_db=args.music_gain,
            loop=args.music_loop,
            offset=args.music_offset,
            fade_in=args.music_fade_in,
            fade_out=args.music_fade_out,
            duck=args.duck,
        )

    if args.output:
        output_path = args.output
    else:
        output_path = default_output_path(input_path, output_dir=args.output_dir)

    return JobSpec(
        input_path=input_path,
        output_path=output_path,
        music=music,
        preset=preset,
        peak_mode=args.mode,
        max_limiting_db=args.max_limiting,
        allow_attenuation=not args.no_attenuate,
        tp_safety_db=args.tp_safety,
        audio_codec=args.audio_codec,
        audio_bitrate=args.audio_bitrate,
        keep_subtitles=not args.no_subtitles,
        refine=not args.no_refine,
        verify=not args.no_verify,
        overwrite=args.overwrite,
        dry_run=args.dry_run,
    )


def _display_width(text):
    """Terminal columns a string occupies, counting CJK characters as two."""
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def _pad(text, width):
    """Left-align to a column width that CJK text does not overflow."""
    return text + " " * max(1, width - _display_width(text))


def _stat_line(label, stats):
    if stats is None or stats.integrated is None:
        return f"   {label}  （無資料）"
    peak = f"{stats.true_peak:+6.2f} dBTP" if stats.true_peak is not None else "   —   "
    lra = f"  動態 {stats.lra:4.1f} LU" if stats.lra is not None else ""
    return f"   {label}  {stats.integrated:+7.2f} LUFS   {peak}{lra}"


def print_summary(result, stream=sys.stdout):
    spec = result.spec
    preset = spec.preset
    write = stream.write

    write("\n")
    if spec.dry_run:
        write(f"◆ 試跑（未輸出）：{os.path.basename(spec.input_path)}\n")
    elif result.output_path:
        write(f"✓ 完成：{result.output_path}\n")
    else:
        write(f"◆ 分析：{os.path.basename(spec.input_path)}\n")

    write(f"   目標  {preset.target_i:+7.2f} LUFS   {preset.target_tp:+6.2f} dBTP"
          f"   （{preset.label}）\n")
    write(_stat_line("原始", result.source_stats) + "\n")
    if result.final_stats is not None:
        write(_stat_line("成品", result.final_stats) + "\n")

    if result.plan is not None:
        write(f"   處理  {result.plan.summary()}\n")
    # Only meaningful when a file was actually written; analysis mode skips them.
    if result.output_path:
        if result.source_info is not None and result.source_info.has_video:
            video = result.source_info.primary_video
            write(f"   影像  {video.codec} {video.resolution} 原封不動複製（未重新編碼）\n")
        if result.encoding is not None:
            kind = "無損" if result.encoding.lossless else "有損"
            write(f"   音訊  {result.encoding.label}（{kind}）\n")
    if result.elapsed:
        write(f"   耗時  {format_duration(result.elapsed)}\n")

    for note in result.notes:
        write(f"   · {note}\n")
    for warning in result.warnings:
        write(f"   ⚠ {warning}\n")
    stream.flush()


def result_to_dict(result):
    def stats_dict(stats):
        if stats is None:
            return None
        return {
            "integrated_lufs": stats.integrated,
            "true_peak_dbtp": stats.true_peak,
            "loudness_range_lu": stats.lra,
            "sample_peak_dbfs": stats.sample_peak,
            "clipped_samples": stats.clipped_samples,
        }

    plan = result.plan
    return {
        "input": result.spec.input_path,
        "output": result.output_path or None,
        "target": {
            "preset": result.spec.preset.key,
            "integrated_lufs": result.spec.preset.target_i,
            "true_peak_dbtp": result.spec.preset.target_tp,
        },
        "source": stats_dict(result.source_stats),
        "result": stats_dict(result.final_stats),
        "plan": None if plan is None else {
            "gain_db": plan.gain_db,
            "limiter_used": plan.use_limiter,
            "limiting_db": plan.limiting_db,
            "transparent": plan.is_transparent,
            "shortfall_db": plan.shortfall_db,
        },
        "audio_codec": None if result.encoding is None else result.encoding.codec,
        "audio_lossless": None if result.encoding is None else result.encoding.lossless,
        "video_copied": bool(
            result.source_info is not None and result.source_info.has_video
        ),
        "on_target": result.hit_target,
        "peak_safe": result.peak_is_safe,
        "elapsed_seconds": round(result.elapsed, 2),
        "notes": list(result.notes),
        "warnings": list(result.warnings),
    }


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.gui:
        from .gui import launch

        return launch()

    if args.list_presets:
        print("可用的平台預設：\n")
        for key, label, target in presets.listing():
            print(f"  {_pad(key, 15)}{_pad(label, 30)}{target}")
        print("\n也可以用 --target-lufs / --target-tp 自訂。")
        return 0

    if not args.inputs:
        parser.print_help()
        return 1

    if args.output and len(args.inputs) > 1:
        parser.error("-o/--output 只能搭配單一輸入檔；多檔請改用 -d/--output-dir。")

    try:
        preset = resolve_preset(args)
    except KeyError as exc:
        parser.error(str(exc))

    reporter = ConsoleReporter(quiet=args.quiet or args.json)
    cancel = CancelToken()

    try:
        tools = discover(args.ffmpeg, args.ffprobe)
    except LoudMasterError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    results = []
    failures = 0
    for index, input_path in enumerate(args.inputs):
        if len(args.inputs) > 1 and not args.quiet and not args.json:
            print(f"\n═══ [{index + 1}/{len(args.inputs)}] "
                  f"{os.path.basename(input_path)} ═══", file=sys.stderr)
        spec = build_spec(args, input_path, preset)
        try:
            if args.analyze:
                result = analyse(tools, spec, reporter, cancel)
            else:
                result = run_job(tools, spec, reporter, cancel)
            reporter.done()
            results.append(result)
            if args.json:
                continue
            print_summary(result)
            if args.dry_run:
                print("\n將執行的指令：")
                for command in result.commands:
                    print("  " + quote_command(command))
        except Cancelled:
            reporter.done()
            print("\n已取消。", file=sys.stderr)
            return 130
        except LoudMasterError as exc:
            reporter.done()
            failures += 1
            print(f"✗ {os.path.basename(input_path)}：{exc}", file=sys.stderr)
        except KeyboardInterrupt:
            reporter.done()
            cancel.cancel()
            print("\n已中斷。", file=sys.stderr)
            return 130

    if args.json:
        payload = [result_to_dict(result) for result in results]
        json.dump(
            payload[0] if len(payload) == 1 else payload,
            sys.stdout,
            ensure_ascii=False,
            indent=2,
        )
        sys.stdout.write("\n")

    if failures:
        print(f"\n{failures} 個檔案失敗。", file=sys.stderr)
        return 2 if results else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
