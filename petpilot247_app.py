from fastapi.responses import FileResponse
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import os

from scheduling import evaluate_groomer_with_google_routes
from maps_service import MapsServiceError

app = FastAPI(title="PetPilot247 Cloud Preview")

DASHBOARD_FILE = Path(__file__).with_name(
    "technician_map_dashboard_dev.html"
)

class GroomerRecommendationRequest(BaseModel):
    groomer_id: str
    requested_start: str
    service_minutes: int
    new_customer_address: str
    appointments: list
    
@app.get("/health")
def health():
    return {
        "status": "running",
        "service": "PetPilot247",
        "mode": "preview_only",
        "live_booking": False,
        "appointment_sync_verified": False,
    }

@app.get("/technician-map")
def technician_map():
    return FileResponse(DASHBOARD_FILE)
    
@app.post("/recommend-groomer")
async def recommend_groomer(request: GroomerRecommendationRequest):
    api_key = os.getenv("GOOGLE_MAPS_API_KEY")

    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="Google Maps API key is not configured"
        )

    try:
        from datetime import datetime

        requested_start = datetime.fromisoformat(
            request.requested_start
        )

        result = await evaluate_groomer_with_google_routes(
            groomer_id=request.groomer_id,
            requested_start=requested_start,
            service_minutes=request.service_minutes,
            appointments=request.appointments,
            new_customer_address=request.new_customer_address,
            api_key=api_key,
            post_buffer_minutes=15,
        )

        return {
            "status": "OK",
            "recommendation": result,
        }

    except MapsServiceError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc)
        ) from exc

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc)
        ) from exc
