# ─────────────────────────────────────────────
# ERPNext Bridge — placeholder for now
# Will connect to ERPNext REST API once instance is set up
# ─────────────────────────────────────────────

import httpx
from app.core.config import settings


class ERPNextClient:
    def __init__(self):
        self.base_url = settings.ERPNEXT_URL
        self.headers = {
            "Authorization": f"token {settings.ERPNEXT_API_KEY}:{settings.ERPNEXT_API_SECRET}",
            "Content-Type": "application/json",
        }

    async def get(self, endpoint: str) -> dict:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{self.base_url}/{endpoint}", headers=self.headers)
            r.raise_for_status()
            return r.json()

    async def post(self, endpoint: str, data: dict) -> dict:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{self.base_url}/{endpoint}", json=data, headers=self.headers
            )
            r.raise_for_status()
            return r.json()


# Singleton — import this in routes when needed
erpnext = ERPNextClient()
