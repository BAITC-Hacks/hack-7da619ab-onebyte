"""Tests for optional diarization; no weights or pyannote imports required."""

import builtins
import json
import os
from pathlib import Path
from contextlib import nullcontext
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
import app
import diarization


SEGMENTS = [
    {"start": 0.5, "end": 4.2, "text": "Первый участник."},
    {"start": 5.0, "end": 8.0, "text": "Второй участник."},
]
TURNS = [
    {"start": 0.0, "end": 4.5, "speaker": "voice_A"},
    {"start": 4.5, "end": 8.0, "speaker": "voice_B"},
]


class AlignmentTests(unittest.TestCase):
    def test_two_speakers_and_preserved_text_timestamps(self):
        aligned = diarization.align_speakers(SEGMENTS, TURNS)
        self.assertEqual([s["speaker"] for s in aligned], ["SPEAKER_00", "SPEAKER_01"])
        for index, segment in enumerate(aligned):
            self.assertEqual(segment["id"], index)
            self.assertEqual({k: segment[k] for k in ("start", "end", "text")}, SEGMENTS[index])

    def test_total_overlap_not_largest_individual_turn(self):
        turns = [{"start": 0, "end": 2, "speaker": "A"},
                 {"start": 2, "end": 5, "speaker": "B"},
                 {"start": 5, "end": 7, "speaker": "A"}]
        result = diarization.align_speakers([{"start": 0, "end": 7, "text": "x"}], turns)
        self.assertEqual(result[0]["speaker"], "SPEAKER_00")

    def test_duplicate_intervals_not_double_counted(self):
        turns = [{"start": 0, "end": 2, "speaker": "A"},
                 {"start": 0, "end": 2, "speaker": "A"},
                 {"start": 2, "end": 5, "speaker": "B"}]
        result = diarization.align_speakers([{"start": 0, "end": 5, "text": "x"}], turns)
        self.assertEqual(result[0]["speaker"], "SPEAKER_01")

    def test_no_overlap_and_zero_duration_are_unknown(self):
        segments = [{"start": 10, "end": 12, "text": "x"}, {"start": 1, "end": 1, "text": "y"}]
        self.assertTrue(all(s["speaker"] is None for s in diarization.align_speakers(segments, TURNS)))
        self.assertTrue(all(s["speaker"] is None for s in diarization.align_speakers(SEGMENTS, [])))

    def test_tie_uses_first_appearance(self):
        self.assertEqual(diarization.align_speakers(
            [{"start": 4, "end": 5, "text": "x"}], TURNS,
        )[0]["speaker"], "SPEAKER_00")


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"DIARIZATION_ENABLED": "1", "DIARIZATION_TIMEOUT_SECONDS": "10"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_success_offline_environment_and_cleanup(self):
        paths = []
        def worker(command, **kwargs):
            self.assertEqual(kwargs["env"]["HF_HUB_OFFLINE"], "1")
            self.assertEqual(kwargs["env"]["PYANNOTE_METRICS_ENABLED"], "0")
            self.assertNotIn("HF_TOKEN", kwargs["env"])
            self.assertNotIn("HUGGING_FACE_HUB_TOKEN", kwargs["env"])
            output = Path(command[-1])
            paths.append(output)
            output.write_text(json.dumps({"status": "ok", "turns": TURNS}), encoding="utf-8")
            return SimpleNamespace(returncode=0)
        with patch.object(diarization.subprocess, "run", side_effect=worker), patch.dict(os.environ, {"HF_TOKEN": "test-only"}):
            result = diarization.diarize_audio(Path("audio.wav"), SEGMENTS)
        self.assertEqual(result["diarization"]["status"], "available")
        self.assertFalse(paths[0].parent.exists())

    def test_crash_timeout_launch_failure_and_bad_json(self):
        cases = [
            {"return_value": SimpleNamespace(returncode=-1073740791)},
            {"side_effect": subprocess.TimeoutExpired("worker", 1)},
            {"side_effect": OSError("Windows blocked native module")},
            {"return_value": SimpleNamespace(returncode=0)},
        ]
        for case in cases:
            with self.subTest(case=case), patch.object(diarization.subprocess, "run", **case):
                result = diarization.diarize_audio(Path("audio.wav"), SEGMENTS)
                self.assertEqual(result["diarization"]["status"], "unavailable")
                self.assertEqual(result["diarization"]["message"], diarization.UNAVAILABLE_MESSAGE)
                self.assertEqual([s["text"] for s in result["segments"]], [s["text"] for s in SEGMENTS])
                self.assertTrue(all(s["speaker"] is None for s in result["segments"]))

    def test_disabled_empty_and_busy_skip_worker(self):
        with patch.object(diarization.subprocess, "run") as worker:
            self.assertEqual(diarization.diarize_audio(Path("audio.wav"), [])["diarization"]["status"], "no_speech")
            with patch.dict(os.environ, {"DIARIZATION_ENABLED": "0"}):
                self.assertEqual(diarization.diarize_audio(Path("audio.wav"), SEGMENTS)["diarization"]["reason"], "disabled")
            with diarization._worker_lock:
                self.assertEqual(diarization.diarize_audio(Path("audio.wav"), SEGMENTS)["diarization"]["reason"], "busy")
            worker.assert_not_called()

    def test_missing_model_is_reported_without_importing_pyannote(self):
        with TemporaryDirectory() as directory:
            output = Path(directory) / "result.json"
            with patch.dict(os.environ, {}, clear=False), patch.object(diarization, "_local_model_path", side_effect=FileNotFoundError()):
                diarization._run_worker("unused.wav", str(output))
            self.assertEqual(json.loads(output.read_text())["reason"], "model_not_cached")

    def test_importerror_and_windows_oserror_are_reported(self):
        original_import = builtins.__import__
        for failure in (ImportError("missing"), OSError("blocked .pyd")):
            def blocked(name, *args, **kwargs):
                if name == "pyannote.audio":
                    raise failure
                return original_import(name, *args, **kwargs)
            with TemporaryDirectory() as directory:
                output = Path(directory) / "result.json"
                with patch.dict(os.environ, {}, clear=False), patch.object(diarization, "_local_model_path", return_value=directory), patch("builtins.__import__", side_effect=blocked):
                    diarization._run_worker("unused.wav", str(output))
                self.assertEqual(json.loads(output.read_text())["reason"], "import_unavailable")

    def test_worker_uses_local_cpu_pipeline_and_exclusive_output(self):
        pipeline = Mock()
        annotation = Mock()
        annotation.itertracks.return_value = [(SimpleNamespace(start=0.5, end=4.2), None, "SPEAKER_00")]
        pipeline.return_value = SimpleNamespace(exclusive_speaker_diarization=annotation)
        factory = Mock(return_value=pipeline)
        waveform = Mock()
        waveform.unsqueeze.return_value = "local waveform"
        torch = SimpleNamespace(from_numpy=Mock(return_value=waveform),
                                device=lambda value: value, inference_mode=nullcontext)
        with TemporaryDirectory() as directory:
            output = Path(directory) / "result.json"
            with patch.dict(os.environ, {}, clear=False), patch.object(diarization, "_local_model_path", return_value=directory), patch.dict(sys.modules, {
                "pyannote.audio": SimpleNamespace(Pipeline=SimpleNamespace(from_pretrained=factory)),
                "torch": torch,
            }), patch("faster_whisper.audio.decode_audio", return_value="decoded audio"):
                diarization._run_worker("sample.wav", str(output))
            factory.assert_called_once_with(directory, token=False)
            pipeline.to.assert_called_once_with("cpu")
            pipeline.assert_called_once_with({"waveform": "local waveform", "sample_rate": 16000})
            payload = json.loads(output.read_text())
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["turns"][0]["speaker"], "SPEAKER_00")

    def test_model_loading_or_access_failure_is_optional(self):
        with TemporaryDirectory() as directory:
            output = Path(directory) / "result.json"
            with patch.dict(os.environ, {}, clear=False), patch.object(diarization, "_local_model_path", return_value=directory), patch.dict(sys.modules, {
                "pyannote.audio": SimpleNamespace(Pipeline=SimpleNamespace(from_pretrained=Mock(side_effect=PermissionError("no access")))),
                "torch": SimpleNamespace(),
            }):
                diarization._run_worker("sample.wav", str(output))
            self.assertEqual(json.loads(output.read_text())["reason"], "model_unavailable")


class IntegrationTests(unittest.TestCase):
    def test_api_keeps_audio_alive_during_diarization_and_deletes_it_after(self):
        model = Mock()
        model.transcribe.return_value = (iter([SimpleNamespace(**segment) for segment in SEGMENTS]), None)
        paths = []
        def run(path, segments):
            paths.append(path)
            self.assertEqual(path.read_bytes(), b"audio")
            return {"segments": diarization.align_speakers(segments, TURNS),
                    "diarization": {"status": "available", "message": "ok"}}
        with patch.object(app, "model", model), patch.object(app, "diarize_audio", side_effect=run):
            response = TestClient(app.app).post("/api/transcribe", files={"file": ("sample.mp3", b"audio")})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["transcript"], "\n".join(s["text"] for s in SEGMENTS))
        self.assertEqual(response.json()["segments"][1]["speaker"], "SPEAKER_01")
        self.assertFalse(paths[0].parent.exists())

    def test_app_imports_with_pyannote_blocked(self):
        code = """
import importlib.abc
import sys
class BlockPyannote(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname.startswith('pyannote'):
            raise OSError('blocked .pyd')
sys.meta_path.insert(0, BlockPyannote())
import app
from fastapi.testclient import TestClient
assert TestClient(app.app).get('/').status_code == 200
assert not any(name.startswith('pyannote') for name in sys.modules)
print('App starts without pyannote')
"""
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
