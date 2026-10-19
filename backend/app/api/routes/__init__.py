"""Route modules."""

from fastapi import APIRouter

from app.api.routes.aid import router as aid_router
from app.api.routes.bp import router as bp_router
from app.api.routes.chat import router as chat_router
from app.api.routes.corpus import router as corpus_router
from app.api.routes.fraud import router as fraud_router
from app.api.routes.health import router as health_router
from app.api.routes.search import router as search_router
from app.api.routes.legal import router as legal_router

api_router = APIRouter()
api_router.include_router(health_router, tags=["health"])
api_router.include_router(corpus_router, tags=["corpus"])
api_router.include_router(chat_router, tags=["chat"])
api_router.include_router(search_router, tags=["search"])
api_router.include_router(fraud_router, tags=["fraud"])
api_router.include_router(aid_router, tags=["aid"])
api_router.include_router(bp_router, tags=["business_plan"])
api_router.include_router(legal_router, tags=["legal"])
