from fastapi import FastAPI

app = FastAPI()


@app.get("/")
def home():
    return {
        "name": "Meeting AI",
        "status": "working",
        "message": "Система автопротоколирования совещаний"
    }