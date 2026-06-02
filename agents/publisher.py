# ============================================
# APEX V3 — Publisher Agent (Pam)
# The House of Packard
# ============================================

import os
import json
import httpx
from datetime import datetime, timezone
from helpers import log_task_start, log_task_complete, log_task_failed, update_agent_status
from observability import report_error
from token_manager import get_etsy_headers

ETSY_API_BASE = "https://openapi.etsy.com/v3"
PRINTFUL_API_BASE = "https://api.printful.com"

SHOP_CONFIG = {
    "benoutside": {"name": "BenOutsideCo"},
    "packardmade": {"name": "PackardMade"},
}

PRODUCT_TYPE_MAP = {
    "shirt": ["t-shirt", "tee", "unisex"],
    "hoodie": ["hoodie", "sweatshirt", "pullover"],
    "beanie": ["beanie", "hat", "winter"],
    "tank": ["tank", "muscle"],
    "mug": ["mug", "cup"],
    "poster": ["poster", "print"],
    "digital": [],
}


async def get_printful_products() -> list:
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{PRINTFUL_API_BASE}/store/products",
                headers={
                    "Authorization": f"Bearer {os.getenv('PRINTFUL_API_KEY')}",
                    "Content-Type": "application/json"
                },
                timeout=30.0
            )
            if response.status_code == 200:
                return response.json().get("result", [])
            print(f"[PAM] Printful products error: {response.status_code}")
            return []
    except Exception as e:
        print(f"[PAM] Printful fetch error: {str(e)}")
        return []


async def get_printful_product_detail(product_id: int) -> dict:
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{PRINTFUL_API_BASE}/store/products/{product_id}",
                headers={
                    "Authorization": f"Bearer {os.getenv('PRINTFUL_API_KEY')}",
                    "Content-Type": "application/json"
                },
                timeout=30.0
            )
            if response.status_code == 200:
                return response.json().get("result", {})
            return {}
    except Exception as e:
        print(f"[PAM] Printful detail error: {str(e)}")
        return {}


def match_product_to_listing(printful_products: list, product_type: str) -> dict:
    keywords = PRODUCT_TYPE_MAP.get(product_type, ["t-shirt"])
    for product in printful_products:
        name = product.get("name", "").lower()
        if any(kw in name for kw in keywords):
            return product
    return printful_products[0] if printful_products else None


async def get_etsy_shop_id(supabase, shop_name: str) -> str:
    env_key = f"ETSY_SHOP_ID_{shop_name.upper().replace(' ', '_')}"
    cached = os.getenv(env_key)
    if cached:
        return cached
    try:
        headers = await get_etsy_headers(supabase)
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{ETSY_API_BASE}/application/shops",
                headers=headers,
                params={"shop_name": shop_name},
                timeout=30.0
            )
            if response.status_code == 200:
                results = response.json().get("results", [])
                if results:
                    shop_id = str(results[0].get("shop_id"))
                    print(f"[PAM] Found shop ID for {shop_name}: {shop_id}")
                    return shop_id
            print(f"[PAM] Could not fetch shop ID: {response.status_code}")
            return None
    except Exception as e:
        print(f"[PAM] Shop ID error: {str(e)}")
        return None


async def run_guardrails(supabase, listing: dict, product: dict, opportunity: dict) -> dict:
    checks_passed = []
    checks_failed = []

    today = datetime.now(timezone.utc).date().isoformat()
    today_response = supabase.table("financial_events")\
        .select("*").eq("category", "listing_fee").gte("timestamp", today).execute()
    listings_today = len(today_response.data)
    if listings_today >= 3:
        checks_failed.append(f"Daily limit reached: {listings_today}/3")
    else:
        checks_passed.append(f"Daily limit OK: {listings_today}/3")

    title = listing.get("title", "")
    if len(title) > 140:
        checks_failed.append(f"Title too long: {len(title)} chars")
    elif len(title) < 10:
        checks_failed.append(f"Title too short: {len(title)} chars")
    else:
        checks_passed.append(f"Title OK: {len(title)} chars")

    tags = listing.get("tags", [])
    if len(tags) < 13:
        checks_failed.append(f"Not enough tags: {len(tags)}/13")
    else:
        checks_passed.append(f"Tags OK: {len(tags)}")

    price = listing.get("price", 0)
    if price < 9.99:
        checks_failed.append(f"Price too low: ${price}")
    elif price > 149.99:
        checks_failed.append(f"Price too high: ${price}")
    else:
        checks_passed.append(f"Price OK: ${price}")

    product_type = product.get("product_type", "shirt")
    base_costs = {"shirt": 10.50, "hoodie": 22.00, "beanie": 14.00,
                  "tank": 11.00, "mug": 7.00, "poster": 9.00, "digital": 0.00}
    base_cost = base_costs.get(product_type, 10.50)
    etsy_fees = price * 0.065 + price * 0.03 + 0.25 + price * 0.018
    margin = (price - base_cost - etsy_fees) / price * 100 if price > 0 else 0
    if margin < 25:
        checks_failed.append(f"Margin too low: {margin:.1f}%")
    else:
        checks_passed.append(f"Margin OK: {margin:.1f}%")

    description = listing.get("description", "")
    if len(description) < 100:
        checks_failed.append(f"Description too short: {len(description)} chars")
    else:
        checks_passed.append(f"Description OK: {len(description)} chars")

    trademark_terms = [
        "nike", "adidas", "disney", "marvel", "nfl", "nba", "mlb", "nhl",
        "pokemon", "harry potter", "star wars", "coca cola", "apple",
        "google", "supreme", "gucci", "louis vuitton", "champion"
    ]
    title_lower = title.lower()
    desc_lower = description.lower()
    found = [t for t in trademark_terms if t in title_lower or t in desc_lower]
    if found:
        checks_failed.append(f"Trademark terms: {', '.join(found)}")
    else:
        checks_passed.append("Trademark scan clean")

    return {
        "allowed": len(checks_failed) == 0,
        "checks_passed": checks_passed,
        "checks_failed": checks_failed,
        "margin": round(margin, 1),
        "blocking_issue": checks_failed[0] if checks_failed else None
    }


async def create_printful_product(listing: dict, product: dict, printful_products: list) -> dict:
    product_type = product.get("product_type", "shirt")
    if product_type == "digital":
        return {"success": True, "printful_id": None, "is_digital": True}

    matched = match_product_to_listing(printful_products, product_type)
    if not matched:
        return {"success": False, "error": "No matching Printful product found"}

    printful_product_id = matched.get("id")
    print(f"[PAM] Matched Printful product: {matched.get('name')} (ID: {printful_product_id})")

    detail = await get_printful_product_detail(printful_product_id)
    sync_variants = detail.get("sync_variants", [])
    if not sync_variants:
        return {"success": False, "error": "No variants found"}

    first_variant = sync_variants[0]

    try:
        price = listing.get("price", 24.99)
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{PRINTFUL_API_BASE}/store/products",
                headers={
                    "Authorization": f"Bearer {os.getenv('PRINTFUL_API_KEY')}",
                    "Content-Type": "application/json"
                },
                json={
                    "sync_product": {
                        "name": listing.get("title", "")[:100],
                    },
                    "sync_variants": [
                        {
                            "retail_price": str(price),
                            "variant_id": first_variant.get("variant_id"),
                            "files": []
                        }
                    ]
                },
                timeout=30.0
            )
            if response.status_code in [200, 201]:
                printful_id = response.json().get("result", {}).get("id")
                return {"success": True, "printful_id": printful_id}
            print(f"[PAM] Printful create error: {response.status_code} — {response.text[:200]}")
            return {"success": False, "error": f"Printful error {response.status_code}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def publish_to_etsy(supabase, listing: dict, shop_id: str) -> dict:
    """Creates an active listing on Etsy with shipping profile."""
    try:
        headers = await get_etsy_headers(supabase)
        tags = listing.get("tags", [])[:13]
        price = float(listing.get("price", 24.99))
        shipping_profile_id = int(os.getenv("ETSY_SHIPPING_PROFILE_ID", "0"))

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{ETSY_API_BASE}/application/shops/{shop_id}/listings",
                headers=headers,
                json={
                    "quantity": 999,
                    "title": listing.get("title", "")[:140],
                    "description": listing.get("description", ""),
                    "price": price,
                    "who_made": "i_did",
                    "when_made": "made_to_order",
                    "taxonomy_id": 1,
                    "tags": tags,
                    "state": "active",
                    "type": "physical",
                    "shipping_profile_id": shipping_profile_id,
                },
                timeout=30.0
            )

            if response.status_code not in [200, 201]:
                return {
                    "success": False,
                    "error": f"Etsy error: {response.status_code} — {response.text[:300]}"
                }

            data = response.json()
            etsy_listing_id = data.get("listing_id")
            return {
                "success": True,
                "etsy_listing_id": str(etsy_listing_id),
                "url": f"https://www.etsy.com/listing/{etsy_listing_id}"
            }

    except Exception as e:
        return {"success": False, "error": str(e)}


async def run_publisher(supabase):
    task_id = await log_task_start(
        supabase, "publisher", "forge",
        "listing_publish",
        {"mode": "live", "scheduled": True}
    )

    try:
        await update_agent_status(supabase, "publisher", "running")
        print(f"\n[PAM] Starting publishing run at {datetime.now(timezone.utc)}")

        today = datetime.now(timezone.utc).date().isoformat()
        today_response = supabase.table("financial_events")\
            .select("*").eq("category", "listing_fee").gte("timestamp", today).execute()
        listings_today = len(today_response.data)

        if listings_today >= 3:
            print(f"[PAM] Daily limit reached ({listings_today}/3) — standing down")
            result = {"listings_published": 0, "blocked_reason": "Daily limit reached",
                      "timestamp": datetime.now(timezone.utc).isoformat()}
            await log_task_complete(supabase, task_id, result)
            await update_agent_status(supabase, "publisher", "idle")
            return result

        slots_remaining = 3 - listings_today
        print(f"[PAM] {slots_remaining} publishing slots available")

        printful_products = await get_printful_products()
        print(f"[PAM] Found {len(printful_products)} Printful products in store")

        listings_response = supabase.table("listings")\
            .select("*, products(*, opportunities(*))")\
            .eq("status", "pending_review")\
            .eq("shop", "benoutside")\
            .limit(slots_remaining)\
            .execute()

        listings = listings_response.data
        print(f"[PAM] {len(listings)} BenOutside listings pending review")

        if not listings:
            print("[PAM] No listings pending")
            result = {"listings_published": 0, "message": "No listings pending",
                      "timestamp": datetime.now(timezone.utc).isoformat()}
            await log_task_complete(supabase, task_id, result)
            await update_agent_status(supabase, "publisher", "idle")
            return result

        published = 0
        blocked = 0
        total_fees = 0.0

        for listing in listings:
            product = listing.get("products", {}) or {}
            opportunity = product.get("opportunities", {}) or {}

            print(f"\n[PAM] Processing: '{listing.get('title', '')[:60]}...'")

            guardrail_result = await run_guardrails(supabase, listing, product, opportunity)

            if not guardrail_result["allowed"]:
                blocked += 1
                print(f"[PAM] ✗ BLOCKED: {guardrail_result['blocking_issue']}")
                supabase.table("guardrail_events").insert({
                    "agent": "publisher",
                    "action_attempted": "publish_listing",
                    "rule_violated": guardrail_result["blocking_issue"],
                    "details": guardrail_result,
                    "listing_id": listing["id"],
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }).execute()
                supabase.table("listings").update({"status": "draft"}).eq("id", listing["id"]).execute()
                continue

            print(f"[PAM] ✓ Guardrails passed — margin: {guardrail_result['margin']}%")

            shop_id = "50046147"

            product_type = product.get("product_type", "shirt")
            if product_type != "digital" and printful_products:
                print(f"[PAM] Creating Printful product...")
                printful_result = await create_printful_product(listing, product, printful_products)
                if printful_result.get("success"):
                    printful_id = printful_result.get("printful_id")
                    print(f"[PAM] ✓ Printful product: {printful_id}")
                else:
                    print(f"[PAM] Printful failed: {printful_result.get('error')} — continuing")
                    printful_id = None
            else:
                printful_id = None

            print(f"[PAM] Publishing to Etsy — BenOutsideCo...")
            etsy_result = await publish_to_etsy(supabase, listing, shop_id)

            if not etsy_result.get("success"):
                print(f"[PAM] ✗ Etsy failed: {etsy_result.get('error')}")
                blocked += 1
                continue

            published += 1
            etsy_listing_id = etsy_result.get("etsy_listing_id")
            listing_url = etsy_result.get("url")
            print(f"[PAM] ✓ LIVE: {listing_url}")

            supabase.table("listings").update({
                "status": "published",
                "etsy_listing_id": etsy_listing_id,
            }).eq("id", listing["id"]).execute()

            if printful_id:
                supabase.table("products").update({
                    "printify_id": printful_id,
                    "status": "live"
                }).eq("id", product.get("id")).execute()

            supabase.table("financial_events").insert({
                "type": "cost",
                "category": "listing_fee",
                "amount": 0.20,
                "listing_id": listing["id"],
                "description": f"Etsy listing fee — {listing.get('title', '')[:50]}",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }).execute()
            total_fees += 0.20

            supabase.table("audit_log").insert({
                "agent": "publisher",
                "action": "listing_published",
                "success": True,
                "details": {
                    "etsy_listing_id": etsy_listing_id,
                    "url": listing_url,
                    "shop": "benoutside",
                    "price": listing.get("price"),
                    "margin": guardrail_result["margin"],
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
            }).execute()

        result = {
            "listings_published": published,
            "listings_blocked": blocked,
            "listing_fees_paid": total_fees,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        await log_task_complete(supabase, task_id, result)
        await update_agent_status(supabase, "publisher", "idle")

        print(f"\n[PAM] Complete:")
        print(f"[PAM]   Published: {published}")
        print(f"[PAM]   Blocked: {blocked}")
        print(f"[PAM]   Fees: ${total_fees:.2f}")
        return result

    except Exception as e:
        await report_error(supabase, "publisher", e, {"task_id": task_id})
        await log_task_failed(supabase, task_id, str(e))
        await update_agent_status(supabase, "publisher", "error")
        print(f"[PAM] Failed: {str(e)}")
        raise
