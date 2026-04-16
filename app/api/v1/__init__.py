from fastapi import APIRouter
from app.api.v1 import auth, dashboard, rates, transactions, currencies, eod, positions, users, report, banks, rider, shifts, credits

router = APIRouter(prefix="/api/v1")
router.include_router(auth.router)
router.include_router(dashboard.router)
router.include_router(rates.router)
router.include_router(transactions.router)
router.include_router(currencies.router)
router.include_router(eod.router)
router.include_router(positions.router)
router.include_router(users.router)
router.include_router(report.router)
router.include_router(banks.router)
router.include_router(rider.router)
router.include_router(shifts.router)
router.include_router(credits.router)
