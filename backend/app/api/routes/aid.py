"""Match a founder profile to local aid files."""

from fastapi import APIRouter, Header

from app.modules.aid.matcher import match
from app.modules.orchestrator import profile as session_profile
from app.schemas.aid import AidMatchResponse, AidProfile

router = APIRouter()

_NEED_TO_INSTRUMENT = {"financing": "loan", "grant": "grant"}


@router.post("/aid/match", response_model=AidMatchResponse)
def match_aid(profile: AidProfile, x_session_id: str | None = Header(default=None)) -> AidMatchResponse:
    session_profile.merge(x_session_id, {
        "stage": profile.stage,
        "sector": profile.sector.strip(),
        "funding_instrument": _NEED_TO_INSTRUMENT.get(profile.need),
    })
    return match(profile)
