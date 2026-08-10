"""Deciding what to do to the audio — the part a mastering engineer would do.

The whole design rests on one rule: **do the least possible to the signal.**

Nearly every automatic loudness tool reaches for a compressor. This one does not.
It works out how much plain gain is needed to hit the target, checks whether that
gain fits under the true-peak ceiling, and if it fits, that is the entire process
— a single multiplication, which is mathematically transparent. Tone, dynamics,
stereo image and transients come out identical, only louder.

A limiter is engaged only when the target genuinely cannot be reached with gain
alone, it is engaged only for the few dB that do not fit, and the amount is
reported so you can see exactly how much processing your master received.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Peak-handling strategies.
MODE_SAFE = "safe"      # never touch dynamics; stop at whatever the peaks allow
MODE_LIMIT = "limit"    # allow a true-peak limiter to buy the last few dB
PEAK_MODES = (MODE_SAFE, MODE_LIMIT)

# The true-peak meter oversamples 4x, which still slightly under-reads the real
# analogue peak, and lossy encoders push peaks up a little further. Aiming a
# fraction below the stated ceiling absorbs both.
DEFAULT_TP_SAFETY_DB = 0.2

# Beyond this much limiting the master stops sounding like the source, so we
# refuse to go further silently.
DEFAULT_MAX_LIMITING_DB = 6.0

# Gain differences smaller than this are inaudible and not worth a re-encode.
ON_TARGET_TOLERANCE_DB = 0.1

# Lookahead limiter voicing. Slow enough not to distort bass, fast enough to
# catch transients; ASC keeps the release musical instead of pumping.
LIMITER_ATTACK_MS = 5.0
LIMITER_RELEASE_MS = 50.0


@dataclass
class MasterPlan:
    """The decision: how much gain, and whether anything else touches the audio."""

    gain_db: float = 0.0
    mode: str = MODE_LIMIT
    use_limiter: bool = False
    ceiling_db: float = -1.0
    limiting_db: float = 0.0
    predicted_i: float | None = None
    predicted_tp: float | None = None
    shortfall_db: float = 0.0
    # How much plain gain the peaks allowed, and the agreed cap on how much
    # extra gain the limiter may absorb. Kept so a later refinement pass cannot
    # quietly exceed the amount of processing the user signed up for.
    headroom_db: float = 0.0
    max_limiting_db: float = 0.0
    notes: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    @property
    def gain_ceiling_db(self):
        """The most gain this plan is ever allowed to apply."""
        return self.headroom_db + self.max_limiting_db

    def shortfall_warning(self):
        """Explain a miss, using the best figure we currently have.

        Derived rather than stored, so that after the rehearsal pass revises
        ``shortfall_db`` the user is never shown a stale prediction alongside
        the confirmed number.
        """
        if self.shortfall_db <= 0.5:
            return None
        landing = (
            f"（約 {self.predicted_i:.1f} LUFS）" if self.predicted_i is not None else ""
        )
        if self.mode == MODE_SAFE:
            return (
                f"安全模式完全不使用限幅器，所以只能提升到峰值允許的程度，"
                f"成品{landing}會比目標小聲 {self.shortfall_db:.1f} dB。"
                "若希望完全達標，請改用限幅模式。"
            )
        return (
            f"素材的峰值遠高於它的平均響度，要完全達標所需的限幅超過了 "
            f"{self.max_limiting_db:.1f} dB 的上限。"
            f"成品{landing}會比目標小聲 {self.shortfall_db:.1f} dB。"
            "常見原因是素材裡有爆音、碰撞聲或突發雜訊——先修掉那幾個突波，"
            "整體就能推得更響；或者放寬限幅上限（聲音會被壓得比較扁）。"
        )

    @property
    def is_transparent(self):
        """True when nothing but a single gain change is applied."""
        return not self.use_limiter

    @property
    def is_noop(self):
        """True when the audio is already on target and needs no gain at all."""
        return (
            not self.use_limiter
            and abs(self.gain_db) < ON_TARGET_TOLERANCE_DB
        )

    def summary(self):
        if self.is_noop:
            return "音量已達標，不需要調整"
        direction = "提升" if self.gain_db >= 0 else "降低"
        text = f"{direction} {abs(self.gain_db):.2f} dB"
        if self.use_limiter:
            text += f"，其中超出峰值餘裕的 {self.limiting_db:.2f} dB 由真實峰值限幅器吸收"
        else:
            text += "（純增益，不改變音質）"
        return text


def plan_master(
    stats,
    preset,
    mode=MODE_LIMIT,
    max_limiting_db=DEFAULT_MAX_LIMITING_DB,
    allow_attenuation=True,
    tp_safety_db=DEFAULT_TP_SAFETY_DB,
):
    """Work out the gain (and whether a limiter is needed) for one master.

    ``stats`` is the measurement of the material as it will be delivered — if you
    are mixing in a music bed, measure the mix, not the pieces.
    """
    if mode not in PEAK_MODES:
        raise ValueError(f"未知的峰值處理模式：{mode}")

    plan = MasterPlan(ceiling_db=preset.target_tp, mode=mode)

    if stats.integrated is None:
        plan.warnings.append("無法量測響度，音量將維持原樣。")
        return plan

    # Where the peaks actually sit. Prefer the true-peak reading; fall back to
    # the sample peak (pessimistically, since true peak is never lower).
    measured_tp = stats.true_peak
    if measured_tp is None:
        measured_tp = stats.sample_peak if stats.sample_peak is not None else 0.0
        plan.notes.append("找不到真實峰值讀數，改用取樣峰值估算（較保守）。")

    effective_ceiling = preset.target_tp - tp_safety_db
    plan.ceiling_db = effective_ceiling

    desired_gain = preset.target_i - stats.integrated
    headroom = effective_ceiling - measured_tp
    plan.headroom_db = headroom
    plan.max_limiting_db = max_limiting_db if mode == MODE_LIMIT else 0.0

    if desired_gain < 0 and not allow_attenuation:
        plan.notes.append(
            f"來源比目標大聲 {abs(desired_gain):.1f} dB，但已指定不降低音量，維持原樣。"
        )
        desired_gain = 0.0

    if desired_gain <= headroom + 1e-9:
        # The happy path: plain gain, nothing else.
        plan.gain_db = desired_gain
        plan.use_limiter = False
        plan.predicted_i = stats.integrated + desired_gain
        plan.predicted_tp = measured_tp + desired_gain
        if desired_gain < 0:
            plan.notes.append(
                "來源比目標大聲，改以純衰減達標——這是完全無損的操作。"
            )
    elif mode == MODE_SAFE:
        # Peaks run out before the target does, and we were told not to limit.
        plan.gain_db = headroom
        plan.use_limiter = False
        plan.shortfall_db = desired_gain - headroom
        plan.predicted_i = stats.integrated + headroom
        plan.predicted_tp = effective_ceiling
        allowance = (
            f"只允許再提升 {headroom:.2f} dB"
            if headroom >= 0
            else f"反而必須先降低 {abs(headroom):.2f} dB"
        )
        plan.notes.append(f"安全模式：峰值{allowance}。")
    else:
        overshoot = desired_gain - headroom
        applied = min(overshoot, max_limiting_db)
        plan.gain_db = headroom + applied
        plan.use_limiter = True
        plan.limiting_db = applied
        plan.shortfall_db = max(0.0, overshoot - applied)
        plan.predicted_i = stats.integrated + plan.gain_db
        plan.predicted_tp = effective_ceiling
        allowance = (
            f"純增益只能提升 {headroom:.2f} dB"
            if headroom >= 0
            else f"純增益反而必須先降低 {abs(headroom):.2f} dB"
        )
        plan.notes.append(
            f"受峰值限制，{allowance}，"
            f"另外 {applied:.2f} dB 由真實峰值限幅器吸收。"
        )
        if plan.shortfall_db > 0:
            plan.notes.append(
                f"要完全達標需要 {overshoot:.2f} dB 的限幅，"
                f"已依設定上限 {max_limiting_db:.1f} dB 收斂。"
            )
        elif applied > 3.0:
            plan.warnings.append(
                f"這次用了 {applied:.2f} dB 的限幅。來源動態較大或峰值偏高，"
                "成品的瞬態會比原始素材略為收斂。"
            )

    _add_source_warnings(stats, plan)
    return plan


def _add_source_warnings(stats, plan):
    """Flag problems that came in with the source, not ones we created."""
    if stats.true_peak is not None and stats.true_peak > 0.0:
        plan.warnings.append(
            f"來源本身的真實峰值已達 {stats.true_peak:+.2f} dBTP（超過 0），"
            "代表它在送進來之前就已經被推爆過。本工具會把峰值拉回安全範圍，"
            "但無法還原已經失去的波形。"
        )
    if stats.clipped_samples and stats.clipped_samples > 100:
        plan.warnings.append(
            f"來源有 {stats.clipped_samples} 個取樣點卡在 0 dBFS，"
            "原始檔可能已經削波失真。"
        )
    if stats.lra is not None and stats.lra > 20:
        plan.notes.append(
            f"來源動態範圍很大（LRA {stats.lra:.1f} LU），"
            "整體響度達標後，安靜段落聽起來仍會偏小聲，這是正常的。"
        )


def refine_gain(plan, achieved_stats, preset, tp_safety_db=DEFAULT_TP_SAFETY_DB):
    """Correct the gain after a rehearsal measurement of the processed chain.

    A limiter removes peak energy, so a limited master lands somewhat below the
    naive ``measured + gain`` prediction. Measuring the processed signal tells us
    the real figure, and we close the gap here — before spending time on the
    actual encode.

    Two invariants make this safe to do automatically:

    * the correction may never push the gain past
      ``headroom + max_limiting``, so a refinement can never sneak in more
      processing than the user agreed to; and
    * the true-peak ceiling is enforced by the limiter itself, so raising the
      gain cannot raise the output peak.

    Only called when a limiter is in play. Plain gain needs no correction — it
    is exact by construction.
    """
    if achieved_stats.integrated is None:
        return plan

    error = preset.target_i - achieved_stats.integrated
    before = plan.gain_db

    if abs(error) >= ON_TARGET_TOLERANCE_DB:
        corrected = plan.gain_db + error
        if plan.use_limiter:
            # Never exceed the agreed amount of limiting, and never fall below
            # the gain the peaks would have allowed on their own.
            corrected = min(corrected, plan.gain_ceiling_db)
            corrected = max(corrected, plan.headroom_db)
        elif achieved_stats.true_peak is not None:
            # Without a limiter the peak is ours to police: only take as much
            # of the correction as the measured peak still has room for.
            peak_room = (preset.target_tp - tp_safety_db) - achieved_stats.true_peak
            corrected = plan.gain_db + min(error, peak_room)
        plan.gain_db = corrected

    applied = plan.gain_db - before
    plan.limiting_db = max(0.0, plan.gain_db - plan.headroom_db)

    # The rehearsal is the honest measurement, so the estimate of where we will
    # land — and therefore how far short we will be — comes from it, not from
    # the optimistic pre-processing arithmetic.
    plan.predicted_i = achieved_stats.integrated + applied
    plan.shortfall_db = max(0.0, preset.target_i - plan.predicted_i)

    if abs(applied) >= ON_TARGET_TOLERANCE_DB:
        plan.notes.append(f"依限幅實測結果微調增益 {applied:+.2f} dB。")
    return plan


__all__ = [
    "DEFAULT_MAX_LIMITING_DB",
    "DEFAULT_TP_SAFETY_DB",
    "LIMITER_ATTACK_MS",
    "LIMITER_RELEASE_MS",
    "MODE_LIMIT",
    "MODE_SAFE",
    "PEAK_MODES",
    "MasterPlan",
    "plan_master",
    "refine_gain",
]
