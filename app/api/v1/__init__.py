from fastapi import APIRouter
from app.api.v1 import auth, dashboard, rates, transactions

router = APIRouter(prefix="/api/v1")
router.include_router(auth.router)
router.include_router(dashboard.router)
router.include_router(rates.router)
router.include_router(transactions.router)
