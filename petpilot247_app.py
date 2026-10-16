from fastapi import FastAPI

app = FastAPI(title="PetPilot247 Cloud Preview")


@app.get("/health")
def health():
    return {
        "status": "running",
        "service": "PetPilot247",
        "mode": "preview_only",
        "live_booking": False,
        "appointment_sync_verified": False,
    }