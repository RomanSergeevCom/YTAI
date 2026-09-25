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


if __name__ == "__main__":
    unittest.main()
