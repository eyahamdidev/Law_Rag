"""Match a founder profile to local aid files."""

from fastapi import APIRouter, Header

from app.modules.aid.extractor import extract_profile
from app.modules.aid.matcher import match
from app.modules.aid.explainer import explain_match
from app.modules.orchestrator import profile as session_profile
from app.schemas.aid import AidMatchResponse, AidProfile

router = APIRouter()

_NEED_TO_INSTRUMENT = {"financing": "loan", "grant": "grant"}


@router.post("/aid/match", response_model=AidMatchResponse)
def match_aid(profile: AidProfile, x_session_id: str | None = Header(default=None)) -> AidMatchResponse:
    if profile.free_text and (
        profile.stage == "unspecified" or not profile.sector or profile.need == "unspecified"
    ):
        extracted, _, _ = extract_profile(profile.free_text, known_profile=profile)
        values = profile.model_dump()
        for field in ("stage", "sector", "need", "funding_need_tnd", "governorate",
                      "is_innovative", "has_startup_label", "is_graduate"):
            current = values[field]
            if current in (None, "", "unspecified"):
                values[field] = getattr(extracted, field)
        profile = AidProfile.model_validate(values)
    session_profile.merge(x_session_id, {
        "stage": profile.stage,
        "sector": profile.sector.strip(),
        "funding_instrument": _NEED_TO_INSTRUMENT.get(profile.need),
    })
    response = match(profile)
    answer, citations, claims, explanation_ref = explain_match(
        profile.free_text or response.summary, response
    )
    response.answer = answer
    response.citations = citations
    response.claims = claims
    response.explanation_ref = explanation_ref
    return response
