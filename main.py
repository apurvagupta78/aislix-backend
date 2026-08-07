from fastapi import FastAPI, UploadFile, File

app = FastAPI(title="Aislix API")


@app.get("/")
def home():
    return {
        "message": "Aislix Backend is running"
    }


@app.post("/scan")
async def scan(file: UploadFile = File(...)):
    return {
        "success": True,
        "filename": file.filename,
        "content_type": file.content_type,
        "message": "Image received successfully"
    }