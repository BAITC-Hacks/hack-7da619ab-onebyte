from pathlib import Path
from shutil import copyfileobj
from tempfile import TemporaryDirectory
from threading import Lock

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from faster_whisper import WhisperModel
from pydantic import BaseModel, Field

from meeting_analysis import analyze_transcript
from protocol_export import build_docx
from diarization import diarize_audio, unavailable

BASE_DIR = Path(__file__).resolve().parent
app = FastAPI(title="Meeting AI", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
model = None
model_lock = Lock()


class TranscriptRequest(BaseModel):
    transcript: str = Field(max_length=1_000_000)


@app.post("/api/analyze")
def analyze(request: TranscriptRequest):
    try:
        return JSONResponse(
            analyze_transcript(request.transcript),
            headers={"Cache-Control": "no-store"},
        )
    except Exception as exc:
        raise HTTPException(500, "Не удалось проанализировать текст. Транскрипт сохранён в интерфейсе.") from exc


@app.post("/api/export/docx")
def export_docx(request: TranscriptRequest):
    try:
        content = build_docx(request.transcript, analyze_transcript(request.transcript))
        return Response(
            content,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={
                "Content-Disposition": 'attachment; filename="meeting-ai-protocol.docx"',
                "Cache-Control": "no-store",
            },
        )
    except ImportError as exc:
        raise HTTPException(503, "Для экспорта установите зависимости из requirements.txt и перезапустите сервер.") from exc
    except Exception as exc:
        raise HTTPException(500, "Не удалось создать DOCX. Повторите экспорт; транскрипт сохранён в интерфейсе.") from exc


@app.post("/api/transcribe")
def transcribe(file: UploadFile):
    # A synchronous route runs in FastAPI's thread pool, keeping the UI available.
    global model
    try:
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in {".mp3", ".wav", ".m4a"}:
            raise HTTPException(400, "Выберите файл в формате MP3, WAV или M4A.")
        with TemporaryDirectory(prefix="meeting-ai-") as directory:
            audio_path = Path(directory) / f"recording{suffix}"
            with audio_path.open("wb") as audio:
                copyfileobj(file.file, audio)
            if audio_path.stat().st_size == 0:
                raise HTTPException(400, "Файл пуст. Выберите запись с аудио.")
            # Serialize CPU inference and initialize the model only once.
            with model_lock:
                if model is None:
                    try:
                        model = WhisperModel(
                            "small", device="cpu", compute_type="int8",
                            local_files_only=True,
                        )
                    except Exception as exc:
                        raise HTTPException(
                            503,
                            "Не удалось загрузить локальную модель small. "
                            "Запустите приложение в окружении, где faster-whisper "
                            "уже работает и модель сохранена в кэше.",
                        ) from exc
                try:
                    segments, _ = model.transcribe(
                        str(audio_path), beam_size=5, vad_filter=True,
                    )
                    # Inference is lazy: consume all segments before deleting audio.
                    transcript_segments = [
                        {"start": float(segment.start), "end": float(segment.end),
                         "text": segment.text.strip()}
                        for segment in segments if segment.text.strip()
                    ]
                    transcript = "\n".join(segment["text"] for segment in transcript_segments)
                except Exception as exc:
                    raise HTTPException(
                        422,
                        "Не удалось распознать запись. Проверьте, что файл "
                        "не повреждён и содержит аудио, затем повторите попытку.",
                    ) from exc
            # Keep the original audio alive until the isolated worker exits.
            # Optional diarization must never turn a successful Whisper result into 500.
            try:
                speaker_result = diarize_audio(audio_path, transcript_segments)
            except Exception:
                speaker_result = unavailable(transcript_segments, "unexpected_failure")
        return JSONResponse(
            {"transcript": transcript, **speaker_result}, headers={"Cache-Control": "no-store"},
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            500, "Не удалось обработать файл на локальном сервере. Повторите попытку.",
        ) from exc
    finally:
        file.file.close()


@app.get("/", response_class=FileResponse)
def home():
    return FileResponse(
        BASE_DIR / "templates" / "index.html",
        media_type="text/html",
        headers={"Cache-Control": "no-store"},
    )


if __name__ == "__main__":
    import uvicorn

    # Resolve app:app from this project even when launched from another directory.
    uvicorn.run(
        "app:app",
        app_dir=str(BASE_DIR),
        host="127.0.0.1",
        port=8000,
        reload=True,
        reload_dirs=[str(BASE_DIR)],
    )
