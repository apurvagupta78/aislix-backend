from fastapi import FastAPI

app = FastAPI(title="Aislix API")


@app.get("/")
def home():
    return {
        "message": "Aislix Backend is running"
    }