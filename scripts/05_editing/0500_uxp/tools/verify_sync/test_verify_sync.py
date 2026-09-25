"""Unit tests for the Verify Sync verdict logic (no audio, no ffmpeg).

    python3 -m unittest tools/verify_sync/test_verify_sync.py
"""
import types
import unittest
from pathlib import Path
import importlib.util

spec = importlib.util.spec_from_file_location("verify_sync", Path(__file__).with_name("verify_sync.py"))
vs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vs)


def fake_arbiter(deltas):
    """deltas: {(name_a, name_b): (dt_sec, peak)} — what the arbiter would measure."""
    t = types.SimpleNamespace(MIN_OVERLAP=20.0, PROBE=90.0)
    t.audio_items = lambda seq: [{"track": f"A{i + 1}", **it} for i, it in enumerate(seq["items"])]
    t.pcm_window = lambda path, s, d: path
    t.envelope = lambda x: x
    t.delta = lambda ea, eb, max_shift_s=6.0: deltas[(ea, eb)]
    return t


def seq(*names):
    return {"name": "S", "items": [{"name": n, "path": n, "start_sec": 0, "end_sec": 100,
                                    "source_in_sec": 0} for n in names]}


class VerdictTest(unittest.TestCase):
    def run_case(self, deltas, *names):
        return vs.measure_sequence(fake_arbiter(deltas), seq(*names), 25, 0.5, 6.0, lambda m: None)

    def test_sync_when_every_camera_lav_pair_is_within_half_a_frame(self):
        r = self.run_case({("cam.MP4", "TX01.wav"): (0.012, 0.9)}, "cam.MP4", "TX01.wav")
        self.assertEqual(r["verdict"], "SYNC")
        self.assertAlmostEqual(r["worst_cam_lav_frames"], 0.3)

    def test_desync_over_half_a_frame(self):
        r = self.run_case({("cam.MP4", "TX01.wav"): (0.0576, 0.99)}, "cam.MP4", "TX01.wav")
        self.assertEqual(r["verdict"], "DESYNC")
        self.assertEqual(r["bad_cam_lav"], 1)

    def test_lav_lav_control_off_zero_means_the_instrument_is_broken(self):
        r = self.run_case({("cam.MP4", "TX01.wav"): (0.0, 0.9), ("cam.MP4", "TX02.wav"): (0.0, 0.9),
                           ("TX01.wav", "TX02.wav"): (0.08, 0.9)}, "cam.MP4", "TX01.wav", "TX02.wav")
        self.assertEqual(r["verdict"], "INSTRUMENT")

    def test_weak_correlation_is_not_judged(self):
        r = self.run_case({("cam.MP4", "TX01.wav"): (0.5, 0.1)}, "cam.MP4", "TX01.wav")
        self.assertEqual(r["verdict"], "NO_DATA")
        self.assertFalse(r["pairs"][0]["judged"])

    def test_camera_camera_pairs_do_not_gate(self):
        r = self.run_case({("a.MP4", "b.MP4"): (0.2, 0.9)}, "a.MP4", "b.MP4")
        self.assertEqual(r["verdict"], "NO_DATA")
        self.assertEqual(r["pairs"][0]["kind"], "cam-cam")


class RobustnessTest(unittest.TestCase):
    """Review of aaff5ba: the panel must always get a verdict it can trust."""

    def test_verdict_folder_is_created_when_missing(self):
        import tempfile, json
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "00_Setup" / "01_Ingest" / "X_sync_verdict.json"   # old project: no 01_Ingest
            written = vs.write_verdict(target, {"run_id": "r1", "verdict": "SYNC"})
            self.assertEqual(written, str(target))
            self.assertEqual(json.loads(target.read_text())["run_id"], "r1")

    def test_unwritable_target_falls_back_to_tmp(self):
        import json
        written = vs.write_verdict(Path("/dev/null/cannot/exist.json"), {"run_id": "r2", "verdict": "ERROR"})
        self.assertEqual(written, str(vs.FALLBACK_VERDICT))
        self.assertEqual(json.loads(vs.FALLBACK_VERDICT.read_text())["run_id"], "r2")

    def test_summary_describes_the_sequence_that_set_the_verdict(self):
        good = {"verdict": "SYNC", "worst_cam_lav": {"a": {"track": "A1"}, "b": {"track": "A4"}},
                "worst_cam_lav_frames": 0.1, "bad_cam_lav": 0}
        bad = {"verdict": "DESYNC", "worst_cam_lav": {"a": {"track": "A3"}, "b": {"track": "A4"}},
               "worst_cam_lav_frames": 1.44, "bad_cam_lav": 2}
        line = vs.summary_line({"sequences": [good, bad], "verdict": "DESYNC"}, 0.5)
        self.assertTrue(line.startswith("DESYNC ✗ worst camera↔lav 1.44 fr A3↔A4"), line)

    def test_duplicate_sequence_names_are_refused(self):
        import tempfile, json, sys, io, contextlib
        with tempfile.TemporaryDirectory() as d:
            dump = Path(d) / "dump.json"
            seq = {"name": "S", "audio": [], "video": []}
            dump.write_text(json.dumps({"sequences": [seq, dict(seq)]}))
            out = Path(d) / "v.json"
            argv = sys.argv
            sys.argv = ["verify_sync.py", "--dump", str(dump), "--fps", "25", "--seq", "S", "--json-out", str(out)]
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    rc = vs.main()
            finally:
                sys.argv = argv
            v = json.loads(out.read_text())
            self.assertEqual(rc, 2)
            self.assertEqual(v["verdict"], "ERROR")
            self.assertIn("2 sequences are named 'S'", v["error"])


if __name__ == "__main__":
    unittest.main()
