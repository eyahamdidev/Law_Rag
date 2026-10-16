"""Match a founder profile to local aid files."""

from fastapi import APIRouter

from app.modules.aid.matcher import match
from app.schemas.aid import AidMatchResponse, AidProfile

router = APIRouter()


@router.post("/aid/match", response_model=AidMatchResponse)
def match_aid(profile: AidProfile) -> AidMatchResponse:
    return match(profile)
