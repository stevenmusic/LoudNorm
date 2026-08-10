"""Tests for LoudMaster.

The unit tests cover the decision-making and command building, and need nothing
installed. The integration tests at the bottom render real files and are skipped
automatically when ffmpeg is not on the machine.

Run with:  python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loudmaster import analysis, encoders, graph, mastering, presets  # noqa: E402
from loudmaster.analysis import LoudnessStats  # noqa: E402
from loudmaster.errors import SilentSource, UnsupportedRequest  # noqa: E402
from loudmaster.media import format_duration  # noqa: E402

YOUTUBE = presets.get("youtube")


def stats(integrated, true_peak, lra=8.0, sample_peak=None, clipped=0):
    return LoudnessStats(
        integrated=integrated,
        true_peak=true_peak,
        lra=lra,
        sample_peak=sample_peak,
        clipped_samples=clipped,
    )


class PlannerTests(unittest.TestCase):
    """The gain/limiter decision — the part that must never surprise a user."""

    def test_quiet_source_with_headroom_uses_pure_gain(self):
        # -30 LUFS, peaks at -20 dBTP: 16 dB of gain needed, 18.8 dB available.
        plan = mastering.plan_master(stats(-30.0, -20.0), YOUTUBE)
        self.assertFalse(plan.use_limiter)
        self.assertTrue(plan.is_transparent)
        self.assertAlmostEqual(plan.gain_db, 16.0, places=6)
        self.assertAlmostEqual(plan.predicted_i, -14.0, places=6)
        self.assertEqual(plan.shortfall_db, 0.0)

    def test_loud_source_is_attenuated_transparently(self):
        plan = mastering.plan_master(stats(-9.0, -3.0), YOUTUBE)
        self.assertFalse(plan.use_limiter)
        self.assertAlmostEqual(plan.gain_db, -5.0, places=6)
        self.assertAlmostEqual(plan.predicted_i, -14.0, places=6)

    def test_attenuation_can_be_refused(self):
        plan = mastering.plan_master(
            stats(-9.0, -3.0), YOUTUBE, allow_attenuation=False
        )
        self.assertEqual(plan.gain_db, 0.0)
        self.assertFalse(plan.use_limiter)

    def test_peaky_source_engages_limiter_for_the_overshoot_only(self):
        # Needs 16 dB; peaks only allow 5.8 dB, so 10.2 dB must be limited.
        plan = mastering.plan_master(
            stats(-30.0, -7.0), YOUTUBE, max_limiting_db=12.0
        )
        self.assertTrue(plan.use_limiter)
        self.assertAlmostEqual(plan.headroom_db, 5.8, places=6)
        self.assertAlmostEqual(plan.limiting_db, 10.2, places=6)
        self.assertAlmostEqual(plan.gain_db, 16.0, places=6)
        self.assertEqual(plan.shortfall_db, 0.0)

    def test_limiting_is_capped_and_shortfall_reported(self):
        plan = mastering.plan_master(
            stats(-30.0, -7.0), YOUTUBE, max_limiting_db=4.0
        )
        self.assertTrue(plan.use_limiter)
        self.assertAlmostEqual(plan.limiting_db, 4.0, places=6)
        self.assertAlmostEqual(plan.gain_db, 9.8, places=6)
        self.assertAlmostEqual(plan.shortfall_db, 6.2, places=6)
        self.assertIsNotNone(plan.shortfall_warning())

    def test_safe_mode_never_limits(self):
        plan = mastering.plan_master(
            stats(-30.0, -7.0), YOUTUBE, mode=mastering.MODE_SAFE
        )
        self.assertFalse(plan.use_limiter)
        self.assertTrue(plan.is_transparent)
        self.assertAlmostEqual(plan.gain_db, 5.8, places=6)
        self.assertAlmostEqual(plan.shortfall_db, 10.2, places=6)
        self.assertIn("安全模式", plan.shortfall_warning())

    def test_predicted_peak_never_exceeds_the_ceiling(self):
        for integrated, peak in [(-30, -20), (-30, -7), (-9, -3), (-40, -0.5)]:
            plan = mastering.plan_master(stats(integrated, peak), YOUTUBE)
            self.assertLessEqual(
                plan.predicted_tp,
                YOUTUBE.target_tp + 1e-9,
                f"peak escaped for I={integrated} TP={peak}",
            )

    def test_already_clipped_source_is_flagged(self):
        plan = mastering.plan_master(stats(-20.0, 0.8, clipped=5000), YOUTUBE)
        joined = " ".join(plan.warnings)
        self.assertIn("推爆", joined)
        self.assertIn("削波", joined)

    def test_silence_is_not_normalised(self):
        plan = mastering.plan_master(LoudnessStats(), YOUTUBE)
        self.assertEqual(plan.gain_db, 0.0)
        self.assertTrue(plan.warnings)

    def test_check_measurable_rejects_silence(self):
        with self.assertRaises(SilentSource):
            analysis.check_measurable(stats(-90.0, -80.0))

    def test_true_peak_falls_back_to_sample_peak(self):
        plan = mastering.plan_master(
            LoudnessStats(integrated=-30.0, true_peak=None, sample_peak=-10.0),
            YOUTUBE,
        )
        self.assertAlmostEqual(plan.headroom_db, 8.8, places=6)


class RefinementTests(unittest.TestCase):
    """Regression tests for the rehearsal correction."""

    def test_refinement_never_exceeds_the_limiting_cap(self):
        # The bug this guards against: a limited master measures low, and the
        # correction chases the target far past the agreed amount of limiting.
        plan = mastering.plan_master(
            stats(-26.1, 0.36), YOUTUBE, max_limiting_db=6.0
        )
        self.assertAlmostEqual(plan.limiting_db, 6.0, places=6)
        ceiling = plan.gain_ceiling_db

        mastering.refine_gain(plan, stats(-24.9, -1.2), YOUTUBE)

        self.assertLessEqual(plan.gain_db, ceiling + 1e-9)
        self.assertLessEqual(plan.limiting_db, 6.0 + 1e-9)

    def test_refinement_closes_a_small_gap(self):
        plan = mastering.plan_master(
            stats(-30.0, -7.0), YOUTUBE, max_limiting_db=12.0
        )
        before = plan.gain_db
        # The rehearsal came out 0.8 dB under target: take all of it.
        mastering.refine_gain(plan, stats(-14.8, -1.2), YOUTUBE)
        self.assertAlmostEqual(plan.gain_db, before + 0.8, places=6)
        self.assertAlmostEqual(plan.predicted_i, -14.0, places=6)

    def test_refinement_pulls_back_when_overshooting(self):
        plan = mastering.plan_master(
            stats(-30.0, -7.0), YOUTUBE, max_limiting_db=12.0
        )
        before = plan.gain_db
        mastering.refine_gain(plan, stats(-13.0, -1.2), YOUTUBE)
        self.assertAlmostEqual(plan.gain_db, before - 1.0, places=6)

    def test_refinement_reports_the_measured_shortfall(self):
        plan = mastering.plan_master(
            stats(-26.1, 0.36), YOUTUBE, max_limiting_db=6.0
        )
        mastering.refine_gain(plan, stats(-24.9, -1.2), YOUTUBE)
        # Gain cannot move, so the honest landing point is the rehearsal figure.
        self.assertAlmostEqual(plan.predicted_i, -24.9, places=6)
        self.assertAlmostEqual(plan.shortfall_db, 10.9, places=6)


class GraphTests(unittest.TestCase):
    def test_simple_premix_only_anchors_the_format(self):
        chains = graph.build_premix(True, sample_rate=48000, layout="stereo")
        self.assertEqual(len(chains), 1)
        self.assertIn("aformat=sample_fmts=dbl:sample_rates=48000", chains[0])
        self.assertIn("[pre]", chains[0])
        # Nothing that could alter the signal belongs in the measurement path.
        for filter_name in ("volume", "alimiter", "compand", "loudnorm"):
            self.assertNotIn(filter_name, chains[0])

    def test_mixing_disables_amix_auto_normalisation(self):
        music = graph.MusicOptions(path="m.wav", mode=graph.MUSIC_MODE_MIX)
        joined = graph.join(graph.build_premix(True, music, 48000, "stereo", 60.0))
        self.assertIn("amix=inputs=2", joined)
        # Without normalize=0 amix halves the level before we ever measure it.
        self.assertIn("normalize=0", joined)

    def test_replace_mode_ignores_the_original_track(self):
        music = graph.MusicOptions(path="m.wav", mode=graph.MUSIC_MODE_REPLACE)
        joined = graph.join(graph.build_premix(True, music, 48000, "stereo", 60.0))
        self.assertIn("[1:a:0]", joined)
        self.assertNotIn("[0:a:0]", joined)
        self.assertNotIn("amix", joined)

    def test_ducking_keys_the_compressor_off_the_original_audio(self):
        music = graph.MusicOptions(path="m.wav", mode=graph.MUSIC_MODE_MIX, duck=True)
        joined = graph.join(graph.build_premix(True, music, 48000, "stereo", 60.0))
        self.assertIn("asplit=2", joined)
        self.assertIn("sidechaincompress", joined)
        self.assertIn("[bed][key]", joined)

    def test_music_is_trimmed_and_padded_to_the_programme_length(self):
        music = graph.MusicOptions(path="m.wav", fade_out=3.0)
        chain = graph.build_music_chain(music, 48000, "stereo", 60.0)
        self.assertIn("atrim=0:60", chain)
        self.assertIn("apad=whole_dur=60", chain)
        self.assertIn("afade=t=out:st=57", chain)

    def test_no_source_audio_and_no_music_is_an_error(self):
        with self.assertRaises(ValueError):
            graph.build_premix(False)

    def test_master_chain_without_limiter_is_a_single_gain(self):
        chain = graph.build_master_chain(6.0, use_limiter=False, sample_rate=48000)
        self.assertIn("volume=6dB:precision=double", chain)
        self.assertNotIn("alimiter", chain)
        self.assertNotIn("aresample=192000", chain)

    def test_zero_gain_emits_no_volume_filter(self):
        chain = graph.build_master_chain(0.0, use_limiter=False, sample_rate=48000)
        self.assertNotIn("volume=", chain)

    def test_limiter_oversamples_and_compensates_its_own_latency(self):
        chain = graph.build_master_chain(
            10.0, use_limiter=True, ceiling_db=-1.2, sample_rate=48000
        )
        self.assertIn("aresample=192000", chain)   # 4x oversampling for true peak
        self.assertIn("alimiter=", chain)
        self.assertIn("level=false", chain)        # must not auto-raise the level
        self.assertIn("latency=1", chain)          # keeps audio aligned to picture
        self.assertIn("aresample=48000", chain)    # and back to the source rate
        self.assertLess(chain.index("volume="), chain.index("alimiter="))

    def test_limiter_ceiling_is_converted_to_linear_amplitude(self):
        chain = graph.build_master_chain(
            10.0, use_limiter=True, ceiling_db=-6.0206, sample_rate=48000
        )
        self.assertIn("limit=0.5", chain)

    def test_oversampling_is_capped_for_high_rate_sources(self):
        chain = graph.build_master_chain(10.0, use_limiter=True, sample_rate=96000)
        self.assertIn("aresample=192000", chain)
        self.assertIn("aresample=96000", chain)

    def test_db_to_linear(self):
        self.assertAlmostEqual(graph.db_to_linear(0.0), 1.0)
        self.assertAlmostEqual(graph.db_to_linear(-6.0206), 0.5, places=5)
        self.assertAlmostEqual(graph.db_to_linear(-20.0), 0.1, places=9)


class MeterTests(unittest.TestCase):
    def test_meter_measures_before_it_normalises(self):
        chain = analysis.meter_filters(YOUTUBE, dual_mono=False)
        # volumedetect must see the raw signal, not loudnorm's output.
        self.assertLess(chain.index("volumedetect"), chain.index("loudnorm"))
        self.assertIn("print_format=json", chain)

    def test_mono_is_metered_as_dual_mono(self):
        self.assertIn("dual_mono=true", analysis.meter_filters(YOUTUBE, True))
        self.assertNotIn("dual_mono", analysis.meter_filters(YOUTUBE, False))

    def test_parses_a_real_loudnorm_report(self):
        stderr = """
[Parsed_volumedetect_0 @ 0x1] n_samples: 1058400
[Parsed_volumedetect_0 @ 0x1] mean_volume: -31.4 dB
[Parsed_volumedetect_0 @ 0x1] max_volume: -3.5 dB
[Parsed_volumedetect_0 @ 0x1] histogram_0db: 12
[Parsed_loudnorm_1 @ 0x2]
{
	"input_i" : "-26.14",
	"input_tp" : "0.36",
	"input_lra" : "1.00",
	"input_thresh" : "-36.20",
	"output_i" : "-14.01",
	"normalization_type" : "dynamic",
	"target_offset" : "0.01"
}
"""
        parsed = analysis.stats_from_stderr(stderr)
        self.assertAlmostEqual(parsed.integrated, -26.14)
        self.assertAlmostEqual(parsed.true_peak, 0.36)
        self.assertAlmostEqual(parsed.lra, 1.00)
        self.assertAlmostEqual(parsed.sample_peak, -3.5)
        self.assertEqual(parsed.clipped_samples, 12)
        self.assertFalse(parsed.is_silent)
        self.assertAlmostEqual(parsed.inter_sample_overshoot, 3.86, places=6)

    def test_silence_reports_as_silent_not_as_a_number(self):
        parsed = analysis.stats_from_stderr('{"input_i" : "-inf", "input_tp" : "-inf"}')
        self.assertIsNone(parsed.integrated)
        self.assertTrue(parsed.is_silent)

    def test_garbage_output_does_not_crash(self):
        parsed = analysis.stats_from_stderr("ffmpeg exploded")
        self.assertIsNone(parsed.integrated)
        self.assertTrue(parsed.is_silent)


class EncoderTests(unittest.TestCase):
    def test_auto_picks_lossless_where_the_container_allows_it(self):
        self.assertEqual(encoders.choose_audio_encoding("o.mkv").codec, "flac")
        self.assertEqual(encoders.choose_audio_encoding("o.mov").codec, "pcm_s24le")
        self.assertTrue(encoders.choose_audio_encoding("o.mkv").lossless)

    def test_auto_falls_back_to_aac_for_mp4_and_says_so(self):
        encoding = encoders.choose_audio_encoding("o.mp4")
        self.assertEqual(encoding.codec, "aac")
        self.assertFalse(encoding.lossless)
        self.assertTrue(any("無損" in note for note in encoding.notes))

    def test_stereo_aac_defaults_to_youtube_recommended_bitrate(self):
        encoding = encoders.choose_audio_encoding("o.mp4", channels=2)
        self.assertIn("384000", encoding.args)

    def test_surround_aac_gets_more_bitrate(self):
        encoding = encoders.choose_audio_encoding("o.mp4", channels=6)
        self.assertIn("576000", encoding.args)

    def test_aliases_resolve(self):
        self.assertEqual(
            encoders.choose_audio_encoding("o.mov", requested="pcm").codec, "pcm_s24le"
        )

    def test_impossible_container_and_codec_is_rejected_clearly(self):
        with self.assertRaises(UnsupportedRequest) as caught:
            encoders.choose_audio_encoding("o.webm", requested="flac")
        self.assertIn("webm", str(caught.exception))

    def test_video_copy_compatibility(self):
        self.assertTrue(encoders.supports_stream_copy_video("mp4", "h264"))
        self.assertTrue(encoders.supports_stream_copy_video("mkv", "prores"))
        self.assertFalse(encoders.supports_stream_copy_video("webm", "h264"))

    def test_audio_only_containers_reject_a_picture(self):
        # An MP3 may arrive carrying cover art as a video stream; a WAV cannot
        # hold it, and must drop it rather than fail the render.
        self.assertFalse(encoders.supports_video("wav"))
        self.assertFalse(encoders.supports_video("flac"))
        self.assertTrue(encoders.supports_video("mp3"))
        self.assertTrue(encoders.supports_video("m4a"))
        self.assertTrue(encoders.supports_video("mp4"))
        self.assertFalse(encoders.supports_stream_copy_video("wav", "png"))

    def test_lossy_containers_all_explain_themselves(self):
        for name in ("o.mp3", "o.mp4", "o.webm"):
            encoding = encoders.choose_audio_encoding(name)
            self.assertFalse(encoding.lossless, name)
            self.assertTrue(encoding.notes, f"{name} should warn about re-encoding")

    def test_container_key_from_extension(self):
        self.assertEqual(encoders.container_key("/a/b/Clip.MP4"), "mp4")
        self.assertEqual(encoders.container_key("x.mkv"), "mkv")


class MiscTests(unittest.TestCase):
    def test_format_duration(self):
        self.assertEqual(format_duration(0), "0:00")
        self.assertEqual(format_duration(75), "1:15")
        self.assertEqual(format_duration(3725), "1:02:05")

    def test_presets_are_sane(self):
        for key in presets.PRESETS:
            preset = presets.get(key)
            self.assertLess(preset.target_i, 0)
            self.assertLessEqual(preset.target_tp, 0)

    def test_unknown_preset_lists_the_valid_ones(self):
        with self.assertRaises(KeyError) as caught:
            presets.get("myspace")
        self.assertIn("youtube", str(caught.exception))


# --------------------------------------------------------------------------
# Integration: these render real files.
# --------------------------------------------------------------------------

HAVE_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


@unittest.skipUnless(HAVE_FFMPEG, "需要 ffmpeg 才能執行整合測試")
class IntegrationTests(unittest.TestCase):
    """End-to-end renders, checked against the meters."""

    @classmethod
    def setUpClass(cls):
        from loudmaster import discover

        cls.tools = discover()
        cls.tmp = tempfile.mkdtemp(prefix="loudmaster-test-")

        cls.quiet = os.path.join(cls.tmp, "quiet.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
             "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=25:duration=8",
             "-f", "lavfi", "-i",
             "sine=frequency=440:duration=8:sample_rate=48000,volume=-28dB",
             "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30",
             "-c:a", "aac", "-shortest", cls.quiet],
            check=True,
        )

        cls.music = os.path.join(cls.tmp, "music.wav")
        subprocess.run(
            ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
             "-f", "lavfi", "-i", "anoisesrc=d=4:c=pink:a=0.3:r=48000",
             "-c:a", "pcm_s16le", cls.music],
            check=True,
        )

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _run(self, name, **kwargs):
        from loudmaster import JobSpec, run_job

        kwargs.setdefault("input_path", self.quiet)
        kwargs.setdefault("preset", YOUTUBE)
        spec = JobSpec(
            output_path=os.path.join(self.tmp, name), overwrite=True, **kwargs
        )
        return run_job(self.tools, spec)

    def _video_md5(self, path):
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", path,
             "-map", "0:v", "-c", "copy", "-f", "md5", "-"],
            stdout=subprocess.PIPE, check=True,
        )
        return result.stdout.decode().strip()

    def test_hits_the_youtube_target_without_clipping(self):
        result = self._run("out.mp4")
        self.assertTrue(result.hit_target, f"landed at {result.final_stats.integrated}")
        self.assertTrue(result.peak_is_safe)
        self.assertLessEqual(result.final_stats.true_peak, YOUTUBE.target_tp + 0.05)

    def test_video_bitstream_is_untouched(self):
        result = self._run("copy.mp4")
        self.assertEqual(self._video_md5(self.quiet), self._video_md5(result.output_path))

    def test_quiet_source_needs_no_limiter(self):
        result = self._run("transparent.mp4")
        self.assertTrue(result.plan.is_transparent)
        self.assertFalse(result.plan.use_limiter)

    def test_mkv_output_is_lossless(self):
        result = self._run("lossless.mkv")
        self.assertEqual(result.encoding.codec, "flac")
        self.assertTrue(result.encoding.lossless)
        self.assertTrue(result.hit_target)

    def test_mixing_music_still_hits_the_target(self):
        result = self._run(
            "mixed.mp4",
            music=graph.MusicOptions(
                path=self.music, mode=graph.MUSIC_MODE_MIX,
                gain_db=-6.0, loop=True, fade_out=1.0,
            ),
        )
        self.assertTrue(result.hit_target, f"landed at {result.final_stats.integrated}")
        self.assertTrue(result.peak_is_safe)

    def test_analysis_mode_writes_nothing(self):
        from loudmaster import JobSpec
        from loudmaster.pipeline import analyse

        target = os.path.join(self.tmp, "never-written.mp4")
        result = analyse(self.tools, JobSpec(input_path=self.quiet, output_path=target))
        self.assertFalse(os.path.exists(target))
        self.assertIsNotNone(result.source_stats.integrated)
        self.assertIsNotNone(result.plan)

    def test_refusing_to_overwrite_the_source(self):
        from loudmaster import JobSpec, run_job

        with self.assertRaises(UnsupportedRequest):
            run_job(self.tools, JobSpec(input_path=self.quiet, output_path=self.quiet))

    def test_impossible_container_is_rejected_before_writing_anything(self):
        from loudmaster import JobSpec, run_job
        from loudmaster.errors import LoudMasterError

        target = os.path.join(self.tmp, "broken.webm")
        # h264 cannot be copied into WebM, and we should say so rather than
        # discovering it halfway through an encode.
        with self.assertRaises(LoudMasterError) as caught:
            run_job(self.tools, JobSpec(input_path=self.quiet, output_path=target))
        self.assertIn("mkv", str(caught.exception))
        self.assertFalse(os.path.exists(target))

    def test_a_failed_render_leaves_no_partial_file(self):
        """A render that dies partway must not leave a half-written master."""
        from loudmaster import JobSpec, pipeline, run_job
        from loudmaster.errors import FFmpegFailed

        target = os.path.join(self.tmp, "aborted.mkv")
        real = pipeline.run_with_progress

        def die_during_render(command, *args, **kwargs):
            written = command[-1]
            if "loudmaster-part" in written:
                # Simulate ffmpeg having created the file, then falling over.
                with open(written, "wb") as handle:
                    handle.write(b"partial")
                raise FFmpegFailed("boom", command, "boom")
            return real(command, *args, **kwargs)

        pipeline.run_with_progress = die_during_render
        try:
            with self.assertRaises(FFmpegFailed):
                run_job(self.tools, JobSpec(input_path=self.quiet, output_path=target))
        finally:
            pipeline.run_with_progress = real

        self.assertFalse(os.path.exists(target))
        leftovers = [n for n in os.listdir(self.tmp) if "loudmaster-part" in n]
        self.assertEqual(leftovers, [], "temporary file was left behind")

    def test_dry_run_measures_but_writes_nothing(self):
        from loudmaster import JobSpec, run_job

        target = os.path.join(self.tmp, "dry.mkv")
        result = run_job(
            self.tools, JobSpec(input_path=self.quiet, output_path=target, dry_run=True)
        )
        self.assertFalse(os.path.exists(target))
        # The printed command must be the real one, so the gain has to be known.
        self.assertIsNotNone(result.source_stats.integrated)
        rendered = " ".join(result.commands[-1])
        self.assertIn("volume=", rendered)
        self.assertNotIn("loudmaster-part", rendered)


if __name__ == "__main__":
    unittest.main(verbosity=2)
