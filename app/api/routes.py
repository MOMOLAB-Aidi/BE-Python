from fastapi import APIRouter

from .routes_records import router as records_router
from .routes_consults import router as consults_router
from .routes_stats import router as stats_router

router = APIRouter()
router.include_router(records_router)
router.include_router(consults_router)
router.include_router(stats_router)