
import os

from dotenv import load_dotenv
from fastapi import FastAPI

load_dotenv()

from demo_scheduling import router as demo_router

app = FastAPI(
    title="PetPilot247 Smart Scheduling Demo",
    version="1.0.0",
)

# Register only the simulation scheduling routes.
for demo_route in demo_router.routes:
    app.router.routes.append(demo_route)


@app.get("/health")
def health():
    return {
        "status": "running",
        "service": "PetPilot247 Smart Scheduling Demo",
        "mode": "simulation_only",
        "live_booking": False,
        "appointment_sync_verified": False,
    }
