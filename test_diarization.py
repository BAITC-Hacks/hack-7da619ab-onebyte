from pyannote.audio import Pipeline

print("Загружаю модель диаризации...")

pipeline = Pipeline.from_pretrained(
    "pyannote/speaker-diarization-community-1"
)

print("Модель загружена!")
print("Определяю говорящих...")

output = pipeline("Совещание №1.mp3")

print("\n--- ГОВОРЯЩИЕ ---")

for turn, speaker in output.speaker_diarization:
    print(
        f"{turn.start:.1f}s - {turn.end:.1f}s: {speaker}"
    )

print("\nГотово!")