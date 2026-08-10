"""A small desktop front end, so the tool is usable without a terminal.

Built on Tkinter, which ships with Python on Windows and macOS, so there is
nothing to install beyond ffmpeg itself.

All the real work lives in :mod:`loudmaster.pipeline`; this module only collects
settings, runs jobs on a worker thread, and pumps progress back to the UI thread
through a queue (Tkinter is not thread-safe, so the worker never touches a
widget directly).
"""

from __future__ import annotations

import os
import queue
import threading

from . import __version__, presets
from .errors import LoudMasterError
from .ffmpeg import CancelToken, Cancelled, discover
from .graph import MUSIC_MODE_MIX, MUSIC_MODE_REPLACE, MusicOptions
from .mastering import DEFAULT_MAX_LIMITING_DB, MODE_LIMIT, MODE_SAFE
from .media import format_duration
from .pipeline import JobSpec, Reporter, analyse, default_output_path, run_job

MEDIA_FILETYPES = [
    ("影片與音訊", "*.mp4 *.mov *.mkv *.m4v *.avi *.webm *.wav *.flac *.mp3 *.m4a *.aac *.ogg"),
    ("影片", "*.mp4 *.mov *.mkv *.m4v *.avi *.webm"),
    ("音訊", "*.wav *.flac *.mp3 *.m4a *.aac *.ogg *.opus"),
    ("所有檔案", "*.*"),
]

AUDIO_FILETYPES = [
    ("音訊檔", "*.wav *.flac *.mp3 *.m4a *.aac *.ogg *.opus *.aiff"),
    ("所有檔案", "*.*"),
]

CODEC_CHOICES = [
    ("auto", "自動（容器允許時選無損）"),
    ("flac", "FLAC（無損）"),
    ("pcm", "PCM 24-bit（無損）"),
    ("alac", "ALAC（無損）"),
    ("aac", "AAC（有損，相容性最好）"),
]


class _Event:
    """Messages the worker thread posts back to the UI."""

    LOG = "log"
    STAGE = "stage"
    PROGRESS = "progress"
    FILE_DONE = "file_done"
    ALL_DONE = "all_done"
    FAILED = "failed"


class _QueueReporter(Reporter):
    def __init__(self, sink):
        self.sink = sink

    def log(self, message, level="info"):
        self.sink((_Event.LOG, (message, level)))

    def stage(self, name, index, total):
        self.sink((_Event.STAGE, (name, index, total)))

    def progress(self, fraction, position=None, speed=None):
        self.sink((_Event.PROGRESS, (fraction, speed)))


def launch():
    """Open the window. Returns a process exit code."""
    try:
        import tkinter as tk
        from tkinter import ttk  # noqa: F401  (imported for the availability check)
    except ImportError:
        print(
            "找不到 Tkinter，無法開啟圖形介面。\n"
            "  macOS / Windows：官方 python.org 的安裝檔內建 Tkinter\n"
            "  Ubuntu/Debian：sudo apt install python3-tk\n"
            "或改用指令列版本：python3 -m loudmaster 影片.mp4"
        )
        return 1

    root = tk.Tk()
    App(root)
    root.mainloop()
    return 0


class App:
    def __init__(self, root):
        import tkinter as tk
        from tkinter import ttk

        self.tk = tk
        self.ttk = ttk
        self.root = root
        self.queue = queue.Queue()
        self.worker = None
        self.cancel = None
        self.tools = None

        root.title(f"LoudMaster {__version__} — 影片響度母帶處理")
        root.minsize(760, 640)

        self._build_widgets()
        self._poll_queue()

        try:
            self.tools = discover()
            self._log(f"已找到 ffmpeg（{self.tools.version.split()[0]}）", "note")
        except LoudMasterError as exc:
            self._log(str(exc), "error")
            self.start_button.state(["disabled"])
            self.analyze_button.state(["disabled"])

    # ---- layout ------------------------------------------------------------

    def _build_widgets(self):
        tk, ttk = self.tk, self.ttk
        root = self.root

        outer = ttk.Frame(root, padding=12)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(4, weight=1)

        # --- files ---
        files = ttk.LabelFrame(outer, text="1. 要處理的影片／音訊", padding=8)
        files.grid(row=0, column=0, sticky="ew")
        files.columnconfigure(0, weight=1)

        self.file_list = tk.Listbox(files, height=4, selectmode="extended")
        self.file_list.grid(row=0, column=0, rowspan=3, sticky="ew", padx=(0, 8))
        ttk.Button(files, text="加入檔案…", command=self._add_files).grid(
            row=0, column=1, sticky="ew"
        )
        ttk.Button(files, text="移除選取", command=self._remove_files).grid(
            row=1, column=1, sticky="ew", pady=2
        )
        ttk.Button(files, text="全部清除", command=self._clear_files).grid(
            row=2, column=1, sticky="ew"
        )

        # --- target ---
        target = ttk.LabelFrame(outer, text="2. 響度目標", padding=8)
        target.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        target.columnconfigure(1, weight=1)

        ttk.Label(target, text="平台：").grid(row=0, column=0, sticky="w")
        self.preset_var = tk.StringVar()
        self.preset_box = ttk.Combobox(target, textvariable=self.preset_var, state="readonly")
        self.preset_box["values"] = [
            f"{label}　（{target_text}）" for _, label, target_text in presets.listing()
        ]
        self._preset_keys = [key for key, _, _ in presets.listing()]
        self.preset_box.current(self._preset_keys.index(presets.DEFAULT_PRESET))
        self.preset_box.grid(row=0, column=1, columnspan=3, sticky="ew", pady=2)
        self.preset_box.bind("<<ComboboxSelected>>", lambda _e: self._show_preset_note())

        self.preset_note = ttk.Label(target, text="", wraplength=680, foreground="#555")
        self.preset_note.grid(row=1, column=0, columnspan=4, sticky="w", pady=(2, 6))

        ttk.Label(target, text="峰值處理：").grid(row=2, column=0, sticky="w")
        self.mode_var = tk.StringVar(value=MODE_LIMIT)
        ttk.Radiobutton(
            target, text="必要時使用限幅器（完全達標）",
            variable=self.mode_var, value=MODE_LIMIT, command=self._sync_enabled,
        ).grid(row=2, column=1, sticky="w")
        ttk.Radiobutton(
            target, text="絕不動態處理（寧可小聲一點）",
            variable=self.mode_var, value=MODE_SAFE, command=self._sync_enabled,
        ).grid(row=2, column=2, sticky="w")

        ttk.Label(target, text="限幅上限：").grid(row=3, column=0, sticky="w")
        self.limit_var = tk.StringVar(value=str(DEFAULT_MAX_LIMITING_DB))
        self.limit_spin = ttk.Spinbox(
            target, from_=0, to=20, increment=0.5, width=6, textvariable=self.limit_var
        )
        self.limit_spin.grid(row=3, column=1, sticky="w")
        ttk.Label(target, text="dB（越大越響，但聲音越扁）", foreground="#555").grid(
            row=3, column=2, columnspan=2, sticky="w"
        )

        # --- music ---
        music = ttk.LabelFrame(outer, text="3. 匯入背景音樂（可略過）", padding=8)
        music.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        music.columnconfigure(1, weight=1)

        ttk.Label(music, text="音樂檔：").grid(row=0, column=0, sticky="w")
        self.music_var = tk.StringVar()
        ttk.Entry(music, textvariable=self.music_var).grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Button(music, text="選擇…", command=self._pick_music).grid(row=0, column=2)
        ttk.Button(music, text="清除", command=lambda: self.music_var.set("")).grid(
            row=0, column=3, padx=(4, 0)
        )

        options = ttk.Frame(music)
        options.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(6, 0))

        ttk.Label(options, text="音量：").pack(side="left")
        self.music_gain_var = tk.StringVar(value="-8")
        ttk.Spinbox(
            options, from_=-40, to=12, increment=1, width=5,
            textvariable=self.music_gain_var,
        ).pack(side="left")
        ttk.Label(options, text="dB").pack(side="left", padx=(2, 12))

        self.music_mode_var = tk.StringVar(value=MUSIC_MODE_MIX)
        ttk.Radiobutton(
            options, text="與原音混合", variable=self.music_mode_var, value=MUSIC_MODE_MIX
        ).pack(side="left")
        ttk.Radiobutton(
            options, text="取代原音", variable=self.music_mode_var, value=MUSIC_MODE_REPLACE
        ).pack(side="left", padx=(4, 12))

        self.loop_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(options, text="不夠長就循環", variable=self.loop_var).pack(side="left")
        self.duck_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            options, text="人聲出現時自動壓低音樂", variable=self.duck_var
        ).pack(side="left", padx=(8, 0))

        fades = ttk.Frame(music)
        fades.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(4, 0))
        ttk.Label(fades, text="淡入：").pack(side="left")
        self.fade_in_var = tk.StringVar(value="0")
        ttk.Spinbox(fades, from_=0, to=30, increment=0.5, width=5,
                    textvariable=self.fade_in_var).pack(side="left")
        ttk.Label(fades, text="秒　淡出：").pack(side="left")
        self.fade_out_var = tk.StringVar(value="2")
        ttk.Spinbox(fades, from_=0, to=30, increment=0.5, width=5,
                    textvariable=self.fade_out_var).pack(side="left")
        ttk.Label(fades, text="秒").pack(side="left")

        # --- output ---
        output = ttk.LabelFrame(outer, text="4. 輸出", padding=8)
        output.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        output.columnconfigure(1, weight=1)

        ttk.Label(output, text="資料夾：").grid(row=0, column=0, sticky="w")
        self.outdir_var = tk.StringVar()
        ttk.Entry(output, textvariable=self.outdir_var).grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Button(output, text="選擇…", command=self._pick_outdir).grid(row=0, column=2)
        ttk.Label(output, text="（留空＝存在原檔旁邊）", foreground="#555").grid(
            row=1, column=1, sticky="w", padx=4
        )

        row = ttk.Frame(output)
        row.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        ttk.Label(row, text="音訊格式：").pack(side="left")
        self.codec_var = tk.StringVar(value=CODEC_CHOICES[0][1])
        codec_box = ttk.Combobox(
            row, textvariable=self.codec_var, state="readonly", width=28,
            values=[label for _, label in CODEC_CHOICES],
        )
        codec_box.pack(side="left", padx=(0, 12))
        self.overwrite_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(row, text="覆蓋已存在的檔案", variable=self.overwrite_var).pack(side="left")

        # --- log ---
        log_frame = ttk.LabelFrame(outer, text="進度", padding=8)
        log_frame.grid(row=4, column=0, sticky="nsew", pady=(8, 0))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(2, weight=1)

        self.stage_label = ttk.Label(log_frame, text="準備就緒")
        self.stage_label.grid(row=0, column=0, sticky="w")
        self.progress = ttk.Progressbar(log_frame, mode="determinate", maximum=100)
        self.progress.grid(row=1, column=0, sticky="ew", pady=4)

        text_wrap = ttk.Frame(log_frame)
        text_wrap.grid(row=2, column=0, sticky="nsew")
        text_wrap.columnconfigure(0, weight=1)
        text_wrap.rowconfigure(0, weight=1)
        self.log_text = tk.Text(text_wrap, height=10, wrap="word", state="disabled")
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(text_wrap, command=self.log_text.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scroll.set)
        self.log_text.tag_configure("warning", foreground="#b06000")
        self.log_text.tag_configure("error", foreground="#c00000")
        self.log_text.tag_configure("note", foreground="#555555")
        self.log_text.tag_configure("good", foreground="#137333")

        # --- actions ---
        actions = ttk.Frame(outer)
        actions.grid(row=5, column=0, sticky="ew", pady=(8, 0))
        self.start_button = ttk.Button(actions, text="開始處理", command=self._start)
        self.start_button.pack(side="right")
        self.analyze_button = ttk.Button(
            actions, text="只分析響度", command=lambda: self._start(analyze_only=True)
        )
        self.analyze_button.pack(side="right", padx=(0, 6))
        self.cancel_button = ttk.Button(actions, text="取消", command=self._cancel)
        self.cancel_button.pack(side="right", padx=(0, 6))
        self.cancel_button.state(["disabled"])

        self._show_preset_note()
        self._sync_enabled()

    # ---- helpers -----------------------------------------------------------

    def _show_preset_note(self):
        preset = presets.get(self._selected_preset_key())
        self.preset_note.configure(text=preset.note or "")

    def _selected_preset_key(self):
        index = self.preset_box.current()
        return self._preset_keys[index if index >= 0 else 0]

    def _sync_enabled(self):
        state = "normal" if self.mode_var.get() == MODE_LIMIT else "disabled"
        self.limit_spin.configure(state=state)

    def _add_files(self):
        from tkinter import filedialog

        paths = filedialog.askopenfilenames(
            title="選擇要處理的影片或音訊", filetypes=MEDIA_FILETYPES
        )
        existing = set(self.file_list.get(0, "end"))
        for path in paths:
            if path not in existing:
                self.file_list.insert("end", path)

    def _remove_files(self):
        for index in reversed(self.file_list.curselection()):
            self.file_list.delete(index)

    def _clear_files(self):
        self.file_list.delete(0, "end")

    def _pick_music(self):
        from tkinter import filedialog

        path = filedialog.askopenfilename(title="選擇背景音樂", filetypes=AUDIO_FILETYPES)
        if path:
            self.music_var.set(path)

    def _pick_outdir(self):
        from tkinter import filedialog

        path = filedialog.askdirectory(title="選擇輸出資料夾")
        if path:
            self.outdir_var.set(path)

    def _log(self, message, level="info"):
        prefix = {"warning": "⚠ ", "error": "✗ ", "note": "· ", "good": "✓ "}.get(level, "")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", prefix + message + "\n", level)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _float(self, variable, default):
        try:
            return float(variable.get())
        except (ValueError, AttributeError):
            return default

    # ---- running -----------------------------------------------------------

    def _collect_specs(self, analyze_only):
        from tkinter import messagebox

        paths = list(self.file_list.get(0, "end"))
        if not paths:
            messagebox.showinfo("還沒有檔案", "請先加入至少一個影片或音訊檔。")
            return None

        music = None
        music_path = self.music_var.get().strip()
        if music_path:
            if not os.path.isfile(music_path):
                messagebox.showerror("找不到音樂檔", f"這個檔案不存在：\n{music_path}")
                return None
            music = MusicOptions(
                path=music_path,
                mode=self.music_mode_var.get(),
                gain_db=self._float(self.music_gain_var, -8.0),
                loop=self.loop_var.get(),
                fade_in=self._float(self.fade_in_var, 0.0),
                fade_out=self._float(self.fade_out_var, 0.0),
                duck=self.duck_var.get(),
            )

        codec = dict((label, key) for key, label in CODEC_CHOICES).get(
            self.codec_var.get(), "auto"
        )
        preset = presets.get(self._selected_preset_key())
        outdir = self.outdir_var.get().strip() or None

        specs = []
        for path in paths:
            specs.append(
                JobSpec(
                    input_path=path,
                    output_path=None if analyze_only else default_output_path(path, outdir),
                    music=music,
                    preset=preset,
                    peak_mode=self.mode_var.get(),
                    max_limiting_db=self._float(self.limit_var, DEFAULT_MAX_LIMITING_DB),
                    audio_codec=codec,
                    overwrite=self.overwrite_var.get(),
                )
            )
        return specs

    def _start(self, analyze_only=False):
        if self.worker is not None and self.worker.is_alive():
            return
        specs = self._collect_specs(analyze_only)
        if not specs:
            return

        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")
        self.progress["value"] = 0

        self.cancel = CancelToken()
        self.start_button.state(["disabled"])
        self.analyze_button.state(["disabled"])
        self.cancel_button.state(["!disabled"])

        self.worker = threading.Thread(
            target=self._run_all, args=(specs, analyze_only), daemon=True
        )
        self.worker.start()

    def _cancel(self):
        if self.cancel is not None:
            self.cancel.cancel()
            self._log("正在取消…", "note")

    def _run_all(self, specs, analyze_only):
        """Worker thread. Only ever talks to the UI through the queue."""
        sink = self.queue.put
        reporter = _QueueReporter(sink)
        succeeded = failed = 0
        for index, spec in enumerate(specs):
            if self.cancel.cancelled:
                break
            sink((_Event.LOG, (f"── [{index + 1}/{len(specs)}] "
                               f"{os.path.basename(spec.input_path)}", "note")))
            try:
                if analyze_only:
                    result = analyse(self.tools, spec, reporter, self.cancel)
                else:
                    result = run_job(self.tools, spec, reporter, self.cancel)
                sink((_Event.FILE_DONE, (result, analyze_only)))
                succeeded += 1
            except Cancelled:
                break
            except LoudMasterError as exc:
                failed += 1
                sink((_Event.FAILED, (spec.input_path, str(exc))))
            except Exception as exc:  # noqa: BLE001 - a crash must not kill the UI
                failed += 1
                sink((_Event.FAILED, (spec.input_path, f"未預期的錯誤：{exc}")))
        sink((_Event.ALL_DONE, (succeeded, failed, self.cancel.cancelled)))

    # ---- UI thread event pump ---------------------------------------------

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                self._handle(kind, payload)
        except queue.Empty:
            pass
        self.root.after(80, self._poll_queue)

    def _handle(self, kind, payload):
        if kind == _Event.LOG:
            message, level = payload
            self._log(message, level)
        elif kind == _Event.STAGE:
            name, index, total = payload
            self.stage_label.configure(text=f"[{index}/{total}] {name}")
            self.progress["value"] = 0
        elif kind == _Event.PROGRESS:
            fraction, _speed = payload
            if fraction is not None:
                self.progress["value"] = fraction * 100
        elif kind == _Event.FILE_DONE:
            self._report_result(*payload)
        elif kind == _Event.FAILED:
            path, message = payload
            self._log(f"{os.path.basename(path)}：{message}", "error")
        elif kind == _Event.ALL_DONE:
            self._finish(*payload)

    def _report_result(self, result, analyze_only):
        preset = result.spec.preset
        source = result.source_stats
        if source is not None and source.integrated is not None:
            self._log(
                f"原始：{source.integrated:+.1f} LUFS / {source.true_peak:+.1f} dBTP"
            )
        if analyze_only:
            self._log(f"若要輸出：{result.plan.summary()}", "note")
            return

        final = result.final_stats
        if final is not None and final.integrated is not None:
            self._log(
                f"成品：{final.integrated:+.1f} LUFS / {final.true_peak:+.1f} dBTP"
                f"（目標 {preset.target_i:g} / {preset.target_tp:g}）"
            )
        if result.plan is not None:
            self._log(f"處理：{result.plan.summary()}", "note")
        if result.source_info is not None and result.source_info.has_video:
            self._log("畫面：原封不動複製，未重新編碼", "note")
        for note in result.notes:
            self._log(note, "note")
        for warning in result.warnings:
            self._log(warning, "warning")
        self._log(
            f"已輸出：{result.output_path}（耗時 {format_duration(result.elapsed)}）",
            "good",
        )

    def _finish(self, succeeded, failed, cancelled):
        self.start_button.state(["!disabled"])
        self.analyze_button.state(["!disabled"])
        self.cancel_button.state(["disabled"])
        self.progress["value"] = 0
        if cancelled:
            self.stage_label.configure(text="已取消")
            self._log("已取消。", "note")
        elif failed:
            self.stage_label.configure(text=f"完成 {succeeded} 個，失敗 {failed} 個")
        else:
            self.stage_label.configure(text=f"全部完成（{succeeded} 個檔案）")


if __name__ == "__main__":
    raise SystemExit(launch())
