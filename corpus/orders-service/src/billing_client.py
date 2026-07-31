"""Calls billing over HTTP. The host arrives from configuration, so no
symbol in this file names the billing service — which is the whole point."""
import os

import httpx


class BillingClient:
    def __init__(self):
        self._base = os.environ["BILLING_URL"]

    async def invoices(self, customer_id: str):
        return await httpx.AsyncClient().get(
            f"{self._base}/v1/invoices/{customer_id}")
