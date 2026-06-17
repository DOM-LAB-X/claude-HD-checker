import asyncio
import json
import urllib.parse
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright

from src.logging_setup import get_logger

log = get_logger()

PARSER_VERSION = "v2"
GRAPHQL_OPNAME = "productClientOnlyProduct"


@dataclass
class CheckResult:
    result_state: str
    online_price_cents: Optional[int] = None
    clearance_price_cents: Optional[int] = None
    savings_pct: Optional[float] = None
    store_verified: bool = False
    error_detail: Optional[str] = None
    # product metadata, populated on success
    product_label: Optional[str] = None
    brand_name: Optional[str] = None
    model_number: Optional[str] = None
    store_sku: Optional[str] = None


def build_localizer_cookie(store_id: str, zip_code: str) -> str:
    localizer = {
        "WORKFLOW": "LOC_HISTORY_BY_IP",
        "THD_FORCE_LOC": "1",
        "THD_LOCSTORE": f"{store_id}+Store - HI+",
        "THD_STRFINDERZIP": zip_code,
        "THD_INTERNAL": "0",
    }
    return urllib.parse.quote(json.dumps(localizer))


def _to_cents(value) -> Optional[int]:
    if value is None:
        return None
    return round(float(value) * 100)


@asynccontextmanager
async def store_session(store_id: str, zip_code: str):
    """Open one WebKit browser context pinned to a given store.

    Use this to check multiple products for the same store without
    relaunching the browser for each one.
    """
    async with async_playwright() as p:
        browser = await p.webkit.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1366, "height": 900})
        await context.add_cookies([{
            "name": "THD_LOCALIZER",
            "value": build_localizer_cookie(store_id, zip_code),
            "domain": ".homedepot.com",
            "path": "/",
        }])
        try:
            yield context
        finally:
            await browser.close()


async def check_product_in_context(context, product_url: str, store_id: str) -> CheckResult:
    """Load the product page in an already store-pinned context and extract pricing."""
    captured_body: Optional[str] = None
    captured_status: Optional[int] = None
    requested_store_id: Optional[str] = None

    page = await context.new_page()

    async def on_request(request):
        nonlocal requested_store_id
        if GRAPHQL_OPNAME in request.url and requested_store_id is None:
            try:
                body = json.loads(request.post_data)
                requested_store_id = body.get("variables", {}).get("storeId")
            except Exception:
                pass

    async def on_response(response):
        nonlocal captured_body, captured_status
        if GRAPHQL_OPNAME in response.url and captured_body is None:
            captured_status = response.status
            try:
                captured_body = await response.text()
            except Exception:
                captured_body = None

    page.on("request", on_request)
    page.on("response", on_response)

    try:
        try:
            resp = await page.goto(product_url, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            return CheckResult(result_state="temporary_error", error_detail=f"navigation error: {e}")

        if resp is None:
            return CheckResult(result_state="temporary_error", error_detail="no response object")

        if resp.status in (429, 403):
            return CheckResult(result_state="rate_limited_or_blocked", error_detail=f"http {resp.status}")

        if resp.status != 200:
            return CheckResult(result_state="product_unavailable", error_detail=f"http {resp.status}")

        for _ in range(20):
            if captured_body is not None:
                break
            await asyncio.sleep(0.5)
    finally:
        await page.close()

    if captured_body is None:
        return CheckResult(result_state="page_layout_changed", error_detail="productClientOnlyProduct call not observed")

    if captured_status in (429, 403):
        return CheckResult(result_state="rate_limited_or_blocked", error_detail=f"graphql http {captured_status}")

    try:
        data = json.loads(captured_body)
    except Exception as e:
        return CheckResult(result_state="page_layout_changed", error_detail=f"invalid json: {e}")

    product = data.get("data", {}).get("product")
    if product is None:
        return CheckResult(result_state="product_unavailable", error_detail=json.dumps(data)[:300])

    try:
        identifiers = product["identifiers"]
        pricing = product["pricing"]
        availability = product["availabilityType"]
    except KeyError as e:
        return CheckResult(result_state="page_layout_changed", error_detail=f"missing key: {e}")

    if availability.get("discontinued") or not availability.get("buyable", True):
        return CheckResult(
            result_state="product_unavailable",
            store_verified=False,
            error_detail="discontinued or not buyable",
        )

    # Verify store identity: confirm the page's own GraphQL request used the
    # storeId we set via the THD_LOCALIZER cookie. (The response itself may not
    # echo the storeId if the item has no BOPIS inventory at that store - that's
    # a valid "not carried here" outcome, not a verification failure.)
    store_verified = requested_store_id == store_id

    meta = dict(
        product_label=identifiers.get("productLabel"),
        brand_name=identifiers.get("brandName"),
        model_number=identifiers.get("modelNumber"),
        store_sku=identifiers.get("storeSkuNumber"),
    )

    if not store_verified:
        return CheckResult(result_state="store_mismatch", store_verified=False, error_detail="requested storeId mismatch", **meta)

    online_price_cents = _to_cents(pricing.get("value"))
    if online_price_cents is None:
        return CheckResult(result_state="price_not_exposed", store_verified=True, error_detail="pricing.value missing", **meta)

    # Log the full pricing block so we can diagnose clearance detection misses.
    log.info("pricing block: %s", json.dumps(pricing))

    clearance_value = None
    savings_pct = None

    # Primary path: pricing.clearance
    cl = pricing.get("clearance") or {}
    if cl.get("value") is not None:
        clearance_value = cl["value"]
        savings_pct = cl.get("percentageOff")

    # Fallback: some in-store clearance items use pricing.specialBuy
    if clearance_value is None:
        sb = pricing.get("specialBuy") or {}
        if sb.get("value") is not None:
            clearance_value = sb["value"]
            savings_pct = sb.get("percentageOff")

    # Fallback: pricing.original > pricing.value means a marked-down price
    if clearance_value is None:
        orig = pricing.get("original")
        if orig and orig > (pricing.get("value") or 0):
            # treat the current value as clearance vs original
            clearance_value = pricing.get("value")
            online_price_cents_orig = _to_cents(orig)
            if online_price_cents_orig:
                savings_pct = round((1 - clearance_value / orig) * 100, 1)
                online_price_cents = online_price_cents_orig

    if clearance_value is None:
        return CheckResult(
            result_state="not_currently_clearance",
            online_price_cents=online_price_cents,
            store_verified=True,
            **meta,
        )

    clearance_price_cents = _to_cents(clearance_value)
    return CheckResult(
        result_state="clearance_price_found",
        online_price_cents=online_price_cents,
        clearance_price_cents=clearance_price_cents,
        savings_pct=savings_pct,
        store_verified=True,
        **meta,
    )


async def check_product(product_url: str, store_id: str, zip_code: str) -> CheckResult:
    """Convenience wrapper: open a one-off store session for a single check."""
    async with store_session(store_id, zip_code) as context:
        return await check_product_in_context(context, product_url, store_id)
