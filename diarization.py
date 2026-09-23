"""Optional, process-isolated Community-1 diarization. See DIARIZATION.md.

Only the standard library is imported in the FastAPI process. Pyannote/torch
imports and inference happen in a disposable worker, so blocked .pyd files,
native crashes, missing weights and timeouts cannot take down Whisper.
"""

from collections import defaultdict
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Lock


MODEL_ID = "pyannote/speaker-diarization-community-1"
UNAVAILABLE_MESSAGE = "Диаризация недоступна в текущей среде"
_worker_lock = Lock()


def align_speakers(segments: list[dict], turns: list[dict]) -> list[dict]:
    """Assign the speaker with maximum total overlap, not the nearest speaker.

    Same-speaker intervals are merged to avoid double counting. Ties use first
    appearance order. No positive overlap => null, never a fabricated speaker.
    IDs are local to this recording and can be referenced by future task sources.
    """
    intervals = defaultdict(list)
    for turn in sorted(turns, key=lambda turn: (turn["start"], turn["end"], turn["speaker"])):
        start, end = float(turn["start"]), float(turn["end"])
        if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
            raise ValueError("Invalid diarization interval")
        label = turn["speaker"]
        if not isinstance(label, str) or not label:
            raise ValueError("Invalid speaker label")
        spans = intervals[label]
        if spans and start <= spans[-1][1]:
            spans[-1] = (spans[-1][0], max(end, spans[-1][1]))
        else:
            spans.append((start, end))
    labels = {label: f"SPEAKER_{index:02d}" for index, label in enumerate(intervals)}
    aligned = []
    for index, segment in enumerate(segments):
        start, end = segment["start"], segment["end"]
        best_label, best_overlap = None, 0.0
        for label, spans in intervals.items():
            overlap = sum(max(0.0, min(end, right) - max(start, left)) for left, right in spans)
            if overlap > best_overlap:
                best_label, best_overlap = labels[label], overlap
        aligned.append({**segment, "id": index, "speaker": best_label})
    return aligned


def unavailable(segments: list[dict], reason: str) -> dict:
    return {
        "segments": [{**segment, "id": index, "speaker": None} for index, segment in enumerate(segments)],
        "diarization": {"status": "unavailable", "message": UNAVAILABLE_MESSAGE, "reason": reason},
    }


def diarize_audio(audio_path: Path, segments: list[dict]) -> dict:
    """Best-effort enhancement; callers always retain the original transcript."""
    if not segments:
        return {"segments": [], "diarization": {"status": "no_speech", "message": "Нет сегментов речи для диаризации."}}
    if os.environ.get("DIARIZATION_ENABLED", "1").lower() in {"0", "false", "no"}:
        return unavailable(segments, "disabled")
    if not _worker_lock.acquire(blocking=False):
        return unavailable(segments, "busy")
    try:
        try:
            timeout = float(os.environ.get("DIARIZATION_TIMEOUT_SECONDS", "180"))
            if not math.isfinite(timeout) or timeout <= 0:
                raise ValueError("Invalid timeout")
            env = os.environ.copy()
            env.update({
                "HF_HUB_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1",
                "PYANNOTE_METRICS_ENABLED": "0", "OTEL_SDK_DISABLED": "true",
            })
            # Runtime never needs a credential: only the explicit download command does.
            env.pop("HF_TOKEN", None)
            env.pop("HUGGING_FACE_HUB_TOKEN", None)
            with TemporaryDirectory(prefix="meeting-ai-diarization-") as directory:
                output_path = Path(directory) / "result.json"
                completed = subprocess.run(
                    [os.environ.get("DIARIZATION_PYTHON") or sys.executable,
                     str(Path(__file__).resolve()), "--worker", str(audio_path.resolve()), str(output_path)],
                    env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, timeout=timeout, check=False,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                if completed.returncode != 0:
                    return unavailable(segments, "worker_failed")
                payload = json.loads(output_path.read_text(encoding="utf-8"))
                if payload.get("status") != "ok":
                    return unavailable(segments, payload.get("reason", "worker_failed"))
                aligned = align_speakers(segments, payload["turns"])
                return {
                    "segments": aligned,
                    "diarization": {
                        "status": "available",
                        "message": "Говорящие определены локально. Метки обозначают голоса, а не имена участников.",
                    },
                }
        except subprocess.TimeoutExpired:
            # subprocess.run kills and waits for its child before raising.
            return unavailable(segments, "timeout")
        except Exception:
            # Do not expose paths, credentials or native exception details to clients.
            return unavailable(segments, "worker_failed")
    finally:
        _worker_lock.release()


def _local_model_path() -> str:
    configured = os.environ.get("DIARIZATION_MODEL_PATH")
    if configured:
        path = Path(configured).expanduser().resolve()
    else:
        from huggingface_hub import snapshot_download
        path = Path(snapshot_download(MODEL_ID, local_files_only=True, token=False))
    if not (path / "config.yaml").is_file():
        raise FileNotFoundError("Community-1 cache is missing")
    return str(path)


def _run_worker(audio_path: str, output_path: str) -> None:
    # Set before importing any library that might initialize networking/telemetry.
    os.environ.update({
        "HF_HUB_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1",
        "PYANNOTE_METRICS_ENABLED": "0", "OTEL_SDK_DISABLED": "true",
    })
    stage = "model_not_cached"
    try:
        model_path = _local_model_path()
        stage = "import_unavailable"
        from pyannote.audio import Pipeline
        import torch
        from faster_whisper.audio import decode_audio

        stage = "model_unavailable"
        pipeline = Pipeline.from_pretrained(model_path, token=False)
        if pipeline is None:
            raise RuntimeError("Pipeline unavailable")
        pipeline.to(torch.device("cpu"))
        stage = "inference_failed"
        # Reuse PyAV decoding: supports MP3/WAV/M4A without an external ffmpeg
        # executable. Passing a waveform avoids pyannote's audio file decoder.
        waveform = torch.from_numpy(decode_audio(audio_path, sampling_rate=16000)).unsqueeze(0)
        with torch.inference_mode():
            output = pipeline({"waveform": waveform, "sample_rate": 16000})
        # Community-1's exclusive result has one speaker at each speech instant.
        annotation = output.exclusive_speaker_diarization
        turns = [{"start": float(turn.start), "end": float(turn.end), "speaker": str(speaker)}
                 for turn, _, speaker in annotation.itertracks(yield_label=True)]
        payload = {"status": "ok", "turns": turns}
    except Exception:
        payload = {"status": "unavailable", "reason": stage}
    Path(output_path).write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False), encoding="utf-8")


def _download_model() -> int:
    """Explicit setup only. No audio argument; never run by the web application."""
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    try:
        from huggingface_hub import snapshot_download
        # HF_TOKEN or the user's HF login cache; never a token in source/arguments.
        path = snapshot_download(MODEL_ID)
        print("Community-1 cached at:", path)
        return 0
    except Exception:
        print("Model download failed. Accept model access conditions and set HF_TOKEN or use hf auth login.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    if sys.argv[1:] == ["--download-model"]:
        raise SystemExit(_download_model())
    if len(sys.argv) == 4 and sys.argv[1] == "--worker":
        _run_worker(sys.argv[2], sys.argv[3])
    else:
        raise SystemExit("Setup: python diarization.py --download-model. See DIARIZATION.md.")
