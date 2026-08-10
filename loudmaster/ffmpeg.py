"""Locating and driving the ffmpeg / ffprobe binaries.

Everything this tool does is ultimately an ffmpeg invocation, so this module
keeps the process handling in one place: finding the binaries, running them,
draining their pipes without deadlocking, and turning ``-progress`` output into
a percentage we can show the user.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import threading
from dataclasses import dataclass, field

from .errors import FFmpegFailed, FFmpegNotFound

# Places ffmpeg commonly lands when it was not installed through a package
# manager that puts it on PATH.
_EXTRA_LOOKUP_DIRS = [
    "/usr/local/bin",
    "/usr/bin",
    "/opt/homebrew/bin",
    "/opt/local/bin",
    "/snap/bin",
    r"C:\ffmpeg\bin",
    r"C:\Program Files\ffmpeg\bin",
]


def _candidate_names(name):
    if os.name == "nt":
        return [name + ".exe", name]
    return [name]


def _find_binary(name, override=None):
    if override:
        if os.path.isdir(override):
            for candidate in _candidate_names(name):
                path = os.path.join(override, candidate)
                if os.path.isfile(path) and os.access(path, os.X_OK):
                    return path
        elif os.path.isfile(override) and os.access(override, os.X_OK):
            return override
        raise FFmpegNotFound(f"指定的路徑找不到可執行的 {name}：{override}")

    found = shutil.which(name)
    if found:
        return found

    for directory in _EXTRA_LOOKUP_DIRS:
        for candidate in _candidate_names(name):
            path = os.path.join(directory, candidate)
            if os.path.isfile(path) and os.access(path, os.X_OK):
                return path
    return None


@dataclass
class FFmpegTools:
    """Resolved paths to the binaries plus the capabilities we care about."""

    ffmpeg: str
    ffprobe: str
    version: str = "unknown"
    filters: frozenset = field(default_factory=frozenset)
    resamplers: frozenset = field(default_factory=frozenset)
    encoders: frozenset = field(default_factory=frozenset)

    def has_filter(self, name):
        return name in self.filters

    def has_encoder(self, name):
        return name in self.encoders

    @property
    def has_soxr(self):
        return "soxr" in self.resamplers


_INSTALL_HINT = """找不到 ffmpeg / ffprobe。LoudMaster 需要它們才能運作。

安裝方式：
  macOS    brew install ffmpeg
  Windows  winget install Gyan.FFmpeg   （或到 https://ffmpeg.org/download.html 下載）
  Ubuntu   sudo apt install ffmpeg

安裝後若仍找不到，可用 --ffmpeg /路徑/到/ffmpeg 指定。"""


def discover(ffmpeg_override=None, ffprobe_override=None):
    """Locate the binaries and probe what this build can do."""
    ffmpeg_path = _find_binary("ffmpeg", ffmpeg_override)
    ffprobe_path = _find_binary("ffprobe", ffprobe_override)
    if not ffmpeg_path or not ffprobe_path:
        raise FFmpegNotFound(_INSTALL_HINT)

    tools = FFmpegTools(ffmpeg=ffmpeg_path, ffprobe=ffprobe_path)

    banner = _capture([ffmpeg_path, "-hide_banner", "-version"])
    if banner:
        tools.version = banner.splitlines()[0].replace("ffmpeg version ", "").strip()

    filters = set()
    for line in _capture([ffmpeg_path, "-hide_banner", "-filters"]).splitlines():
        parts = line.split()
        # Rows look like: " T.C alimiter  A->A  Audio lookahead limiter."
        if len(parts) >= 3 and len(parts[0]) == 3:
            filters.add(parts[1])
    tools.filters = frozenset(filters)

    encoders = set()
    for line in _capture([ffmpeg_path, "-hide_banner", "-encoders"]).splitlines():
        parts = line.split()
        if len(parts) >= 2 and len(parts[0]) == 6:
            encoders.add(parts[1])
    tools.encoders = frozenset(encoders)

    resamplers = set()
    help_text = _capture([ffmpeg_path, "-hide_banner", "-h", "filter=aresample"])
    if "soxr" in help_text:
        resamplers.add("soxr")
    resamplers.add("swr")
    tools.resamplers = frozenset(resamplers)

    return tools


def _no_window_kwargs():
    """Stop console windows flashing up when the GUI spawns ffmpeg on Windows."""
    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return {
        "startupinfo": startupinfo,
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
    }


def _capture(command):
    """Run a short-lived query command, returning stdout+stderr as text."""
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            **_no_window_kwargs(),
        )
    except OSError:
        return ""
    return result.stdout.decode("utf-8", "replace")


def run(command, check=True):
    """Run a command to completion, returning ``(returncode, stdout, stderr)``."""
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            **_no_window_kwargs(),
        )
    except OSError as exc:
        raise FFmpegFailed(f"無法執行 {command[0]}：{exc}", command) from exc

    stdout = result.stdout.decode("utf-8", "replace")
    stderr = result.stderr.decode("utf-8", "replace")
    if check and result.returncode != 0:
        raise FFmpegFailed(
            _summarise_failure(stderr, result.returncode), command, stderr
        )
    return result.returncode, stdout, stderr


# ffmpeg's final line is usually the useless "Conversion failed!"; the line that
# says what went wrong is further up.
_USELESS_TAILS = ("Conversion failed!", "Error opening output files.")
_ERROR_MARKERS = (
    "Error", "error", "Invalid", "invalid", "not supported", "Unsupported",
    "Unable to", "could not", "Could not", "No such file", "does not contain",
    "Unknown", "denied", "Permission",
)


def _summarise_failure(stderr, returncode):
    """Pull the most useful-looking line out of an ffmpeg error dump."""
    lines = [
        line.strip()
        for line in stderr.strip().splitlines()
        if line.strip()
        and not line.startswith(("  ", "Input #", "Output #", "Stream mapping"))
    ]
    # Prefer a line that names the actual problem over ffmpeg's generic sign-off.
    diagnostic = next(
        (
            line
            for line in reversed(lines)
            if line not in _USELESS_TAILS and any(m in line for m in _ERROR_MARKERS)
        ),
        None,
    )
    if diagnostic is None:
        candidates = [line for line in lines if line not in _USELESS_TAILS]
        diagnostic = (
            candidates[-1] if candidates
            else (lines[-1] if lines else f"結束代碼 {returncode}")
        )
    return f"ffmpeg 執行失敗：{diagnostic}"


class Cancelled(Exception):
    """Raised inside a job when the caller asked it to stop."""


class CancelToken:
    """A thread-safe 'please stop' flag the GUI can flip."""

    def __init__(self):
        self._event = threading.Event()

    def cancel(self):
        self._event.set()

    @property
    def cancelled(self):
        return self._event.is_set()

    def raise_if_cancelled(self):
        if self._event.is_set():
            raise Cancelled()


def _parse_progress_line(line, state):
    """Fold one ``key=value`` progress line into ``state``; return True if done."""
    key, _, value = line.partition("=")
    key = key.strip()
    value = value.strip()
    if key == "out_time_us" or key == "out_time_ms":
        # out_time_ms is misnamed upstream: it is also microseconds.
        try:
            state["position"] = max(0.0, int(value) / 1_000_000.0)
        except ValueError:
            pass
    elif key == "speed" and value.endswith("x"):
        try:
            state["speed"] = float(value[:-1])
        except ValueError:
            pass
    elif key == "progress":
        return value == "end"
    return False


def run_with_progress(command, duration=None, on_progress=None, cancel=None):
    """Run ffmpeg, reporting progress as a 0..1 fraction.

    ``command`` should not already contain ``-progress``; we add it. Returns the
    full stderr text, which is where ffmpeg writes its filter reports.
    """
    full_command = list(command)
    # -progress writes machine-readable status to stdout; -nostats silences the
    # human-readable duplicate on stderr so our parsing stays clean.
    full_command[1:1] = ["-nostdin", "-nostats", "-progress", "pipe:1"]

    try:
        process = subprocess.Popen(
            full_command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **_no_window_kwargs(),
        )
    except OSError as exc:
        raise FFmpegFailed(f"無法執行 {full_command[0]}：{exc}", full_command) from exc

    stderr_chunks = []
    stderr_done = threading.Event()

    def drain_stderr():
        try:
            for chunk in iter(lambda: process.stderr.read(8192), b""):
                stderr_chunks.append(chunk)
        finally:
            stderr_done.set()

    reader = threading.Thread(target=drain_stderr, daemon=True)
    reader.start()

    state = {"position": 0.0, "speed": None}
    cancelled = False
    try:
        for raw in iter(process.stdout.readline, b""):
            if cancel is not None and cancel.cancelled:
                cancelled = True
                break
            finished = _parse_progress_line(
                raw.decode("utf-8", "replace").strip(), state
            )
            if on_progress is not None:
                fraction = None
                if duration and duration > 0:
                    fraction = min(1.0, state["position"] / duration)
                on_progress(fraction, state["position"], state["speed"])
            if finished:
                break
    finally:
        if cancelled:
            _terminate(process)
        try:
            process.stdout.close()
        except OSError:
            pass
        process.wait()
        stderr_done.wait(timeout=5)
        try:
            process.stderr.close()
        except OSError:
            pass

    stderr = b"".join(stderr_chunks).decode("utf-8", "replace")

    if cancelled:
        raise Cancelled()
    if process.returncode != 0:
        raise FFmpegFailed(
            _summarise_failure(stderr, process.returncode), full_command, stderr
        )
    if on_progress is not None:
        on_progress(1.0, state["position"], state["speed"])
    return stderr


def _terminate(process):
    """Ask ffmpeg to stop, then insist."""
    try:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
    except OSError:
        pass


def quote_command(command):
    """Render a command list the way a user could paste it back into a shell."""
    if os.name == "nt":
        return subprocess.list2cmdline(command)
    return " ".join(shlex.quote(part) for part in command)


__all__ = [
    "CancelToken",
    "Cancelled",
    "FFmpegTools",
    "discover",
    "quote_command",
    "run",
    "run_with_progress",
]
