"""Authenticated Pavi recommendation endpoint. Add via app.include_router(router)."""
import os
import secrets
from datetime import datetime
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
from pavi_recommendation_pipeline import Request, recommend
from pavi_live_ghl_provider import LiveGHLProviders

router = APIRouter(prefix='/internal/pavi', tags=['Pavi Scheduling'])

class RecommendationInput(BaseModel):
    calendar_id: str = Field(min_length=1, max_length=150)
    customer_address: str = Field(min_length=5, max_length=500)
    preferred_start: datetime
    service_minutes: int = Field(ge=1, le=480)
    max_results: int = Field(default=5, ge=1, le=5)

@router.post('/recommendations')
async def internal_recommendations(payload: RecommendationInput,
                                   x_reconciliation_key: str | None = Header(default=None)):
    expected = os.getenv('PETPILOT_RECONCILIATION_API_KEY', '')
    if not expected or not x_reconciliation_key or not secrets.compare_digest(x_reconciliation_key, expected):
        raise HTTPException(status_code=401, detail='Unauthorized')
    if payload.preferred_start.tzinfo is None:
        raise HTTPException(status_code=422, detail='preferred_start must include timezone')
    result = await recommend(Request(
        calendar_id=payload.calendar_id,
        customer_address=payload.customer_address,
        preferred_start=payload.preferred_start,
        service_minutes=payload.service_minutes,
        max_results=payload.max_results,
    ), LiveGHLProviders())
    if 'reason' in result:
        raise HTTPException(status_code=503, detail=result['reason'])
    return result
