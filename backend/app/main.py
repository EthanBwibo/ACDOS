from fastapi import FastAPI

app = FastAPI(title="ACDOS Backend")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}