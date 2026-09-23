from faster_whisper import WhisperModel

print("Загружаю модель...")

model = WhisperModel(
    "small",
    device="cpu",
    compute_type="int8"
)

print("Модель загружена.")
print("Начинаю распознавание MP3...")

segments, info = model.transcribe(
    "Совещание №1.mp3",
    beam_size=5,
    vad_filter=True
)

print("\n--- ТРАНСКРИПТ ---")

for segment in segments:
    print(segment.text)

print("\nГотово!")