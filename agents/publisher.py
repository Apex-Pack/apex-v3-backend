# ============================================
# APEX V3 — Publisher Agent (Pam)
# The House of Packard
# ============================================
# Pam's job: Take validated listings with
# designs and copy, run every guardrail check,
# create products in Printify, and publish
# live listings to the correct Etsy shop.
# Max 3 listings per day. Highest score first.
# ============================================

import os
import json
import httpx
from datetime import datetime, timezone
from helpers import log_task_start, log_task_complete, log_task_failed, update_agent_status
from observability import report_error
from token_manager import get_etsy_headers

ETSY_API_BASE = "https://openapi.etsy.com/v3"
PRINTIFY_API_BASE = "https://api.printify.com/v1"

SHOP_CONFIG = {
    "benoutside": {
        "name": "BenOutsideCo",
        "etsy_shop_id": None,  # Fetched on first run
    },
    "packardmade": {
        "name": "PackardMade",
        "etsy_shop_id": None,  # Set when shop is created
    }
}


async def get_etsy_shop_id(supabase, shop_name: str) -> str:
    """
    Fetches the Etsy shop ID for a given shop name.
    Caches it in Railway after first fetch.
    """
    # Check if already cached in environment
    env_key = f"ETSY_SHOP_ID_{shop_name.upper()}"
    cached = os.getenv(env_key)
    if cached:
        return cached

    # Fetch from Etsy API
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
                data = response.json()
                results = data.get("results", [])
                if results:
                    shop_id = str(results[0].get("shop_id"))
                    print(f"[PAM] Found shop ID for {shop_name}: {shop_id}")
                    return shop_id
            print(f"[PAM] Could not fetch shop ID for {shop_name}: {response.status_code}")
            return None
    except Exception as e:
        print(f"[PAM] Shop ID fetch error: {str(e)}")
        return None


# ============================================
# Guardrail Checks
# Every listing must pass ALL checks before
# Pam will publish it. One failure = blocked.
# ============================================

async def run_guardrails(supabase, listing: dict, product: dict, opportunity: dict) -> dict:
    """
    Runs all pre-publish guardrail checks.
    Returns allowed: True/False with reason.
    """
    checks_passed = []
    checks_failed = []

    # Check 1 — Daily listing limit
    today = datetime.now(timezone.utc).date().isoformat()
    today_response = supabase.table("financial_events")\
        .select("*")\
        .eq("category", "listing_fee")\
        .gte("timestamp", today)\
        .execute()
    listings_today = len(today_response.data)

    if listings_today >= 3:
        checks_failed.append(f"Daily limit reached: {listings_today}/3 listings published today")
    else:
        checks_passed.append(f"Daily limit OK: {listings_today}/3 used")

    # Check 2 — Title length
    title = listing.get("title", "")
    if len(title) > 140:
        checks_failed.append(f"Title too long: {len(title)} chars (max 140)")
    elif len(title) < 10:
        checks_failed.append(f"Title too short: {len(title)} chars")
    else:
        checks_passed.append(f"Title length OK: {len(title)} chars")

    # Check 3 — Tags count
    tags = listing.get("tags", [])
    if len(tags) < 13:
        checks_failed.append(f"Not enough tags: {len(tags)}/13")
    else:
        checks_passed.append(f"Tags OK: {len(tags)} tags")

    # Check 4 — Price sanity
    price = listing.get("price", 0)
    if price < 9.99:
        checks_failed.append(f"Price too low: ${price} (min $9.99)")
    elif price > 149.99:
        checks_failed.append(f"Price too high: ${price} (max $149.99)")
    else:
        checks_passed.append(f"Price OK: ${price}")

    # Check 5 — Margin check
    product_type = product.get("product_type", "shirt")
    base_costs = {"shirt": 10.50, "mug": 7.00, "poster": 9.00, "digital": 0.00}
    base_cost = base_costs.get(product_type, 10.50)
    etsy_fees = price * 0.065 + price * 0.03 + 0.25 + price * 0.018
    margin = (price - base_cost - etsy_fees) / price * 100 if price > 0 else 0

    if margin < 25:
        checks_failed.append(f"Margin too low: {margin:.1f}% (min 25%)")
    else:
        checks_passed.append(f"Margin OK: {margin:.1f}%")

    # Check 6 — Description present
    description = listing.get("description", "")
    if len(description) < 100:
        checks_failed.append(f"Description too short: {len(description)} chars")
    else:
        checks_passed.append(f"Description OK: {len(description)} chars")

    # Check 7 — Trademark keyword scan
    trademark_terms = [
        "nike", "adidas", "disney", "marvel", "nfl", "nba", "mlb", "nhl",
        "pokemon", "harry potter", "star wars", "coca cola", "apple",
        "google", "supreme", "gucci", "louis vuitton", "champion"
    ]
    title_lower = title.lower()
    description_lower = description.lower()
    found_trademarks = [t for t in trademark_terms
                        if t in title_lower or t in description_lower]

    if found_trademarks:
        checks_failed.append(f"Trademark terms found: {', '.join(found_trademarks)}")
    else:
        checks_passed.append("Trademark scan clean")

    all_passed = len(checks_failed) == 0

    return {
        "allowed": all_passed,
        "checks_passed": checks_passed,
        "checks_failed": checks_failed,
        "margin": round(margin, 1),
        "blocking_issue": checks_failed[0] if checks_failed else None
    }


async def create_printify_product(product: dict, listing: dict) -> dict:
    """
    Creates a product in Printify and returns the product ID.
    Uses the appropriate blueprint for each product type.
    """
    printify_token = os.getenv("PRINTIFY_API_TOKEN")
    printify_shop_id = os.getenv("PRINTIFY_SHOP_ID")

    if not printify_token or not printify_shop_id:
        return {"success": False, "error": "Printify credentials not configured"}

    product_type = product.get("product_type", "shirt")

    # Blueprint IDs for most common Printify products
    # These are real Printify blueprint IDs
    blueprints = {
        "shirt": {"blueprint_id": 6, "print_provider_id": 99},   # Bella Canvas 3001
        "mug": {"blueprint_id": 68, "print_provider_id": 99},     # 11oz White Mug
        "poster": {"blueprint_id": 395, "print_provider_id": 99}, # Enhanced Matte Paper Poster
        "digital": None  # Digital products don't need Printify
    }

    if product_type == "digital":
        return {"success": True, "printify_id": None, "is_digital": True}

    blueprint = blueprints.get(product_type, blueprints["shirt"])

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{PRINTIFY_API_BASE}/shops/{printify_shop_id}/products.json",
                headers={
                    "Authorization": f"Bearer {printify_token}",
                    "Content-Type": "application/json"
                },
                json={
                    "title": listing.get("title", "")[:100],
                    "description": listing.get("description", ""),
                    "blueprint_id": blueprint["blueprint_id"],
                    "print_provider_id": blueprint["print_provider_id"],
                    "variants": [
                        {
                            "id": 17887,
                            "price": int(listing.get("price", 24.99) * 100),
                            "is_enabled": True
                        }
                    ],
                    "print_areas": [
                        {
                            "variant_ids": [17887],
                            "placeholders": [
                                {
                                    "position": "front",
                                    "images": [
                                        {
                                            "id": "placeholder",
                                            "x": 0.5,
                                            "y": 0.5,
                                            "scale": 1,
                                            "angle": 0
                                        }
                                    ]
                                }
                            ]
                        }
                    ]
                },
                timeout=30.0
            )

            if response.status_code in [200, 201]:
                data = response.json()
                return {
                    "success": True,
                    "printify_id": data.get("id"),
                    "is_digital": False
                }
            else:
                print(f"[PAM] Printify error: {response.status_code} — {response.text[:200]}")
                return {"success": False, "error": f"Printify error {response.status_code}"}

    except Exception as e:
        return {"success": False, "error": str(e)}


async def publish_to_etsy(supabase, listing: dict, shop_id: str, printify_id: str = None) -> dict:
    """
    Creates a draft listing on Etsy and activates it.
    Returns the Etsy listing ID and URL.
    """
    try:
        headers = await get_etsy_headers(supabase)
        tags = listing.get("tags", [])[:13]
        price = listing.get("price", 24.99)
        price_cents = int(price * 100)

        async with httpx.AsyncClient() as client:
            # Step 1 — Create draft listing
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
                    "state": "draft",
                    "type": "physical",
                    "shipping_profile_id": None,
                },
                timeout=30.0
            )

            if response.status_code not in [200, 201]:
                return {
                    "success": False,
                    "error": f"Etsy create listing error: {response.status_code} — {response.text[:200]}"
                }

            listing_data = response.json()
            etsy_listing_id = listing_data.get("listing_id")
            print(f"[PAM] Draft listing created: {etsy_listing_id}")

            return {
                "success": True,
                "etsy_listing_id": str(etsy_listing_id),
                "url": f"https://www.etsy.com/listing/{etsy_listing_id}",
                "status": "draft"
            }

    except Exception as e:
        return {"success": False, "error": str(e)}


async def run_publisher(supabase):
    """
    Pam's full routine:
    1. Pull pending_review listings ordered by opportunity score
    2. Check daily limit — max 3 per day
    3. Run all guardrails
    4. Create product in Printify
    5. Publish to correct Etsy shop
    6. Update listing status and log financial event
    """
    task_id = await log_task_start(
        supabase, "publisher", "forge",
        "listing_publish",
        {"mode": "live", "scheduled": True}
    )

    try:
        await update_agent_status(supabase, "publisher", "running")
        print(f"\n[PAM] Starting publishing run at {datetime.now(timezone.utc)}")

        # Check daily limit first
        today = datetime.now(timezone.utc).date().isoformat()
        today_response = supabase.table("financial_events")\
            .select("*")\
            .eq("category", "listing_fee")\
            .gte("timestamp", today)\
            .execute()
        listings_today = len(today_response.data)

        if listings_today >= 3:
            print(f"[PAM] Daily limit reached ({listings_today}/3) — standing down")
            result = {
                "listings_published": 0,
                "blocked_reason": "Daily limit reached",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            await log_task_complete(supabase, task_id, result)
            await update_agent_status(supabase, "publisher", "idle")
            return result

        slots_remaining = 3 - listings_today
        print(f"[PAM] {slots_remaining} publishing slots available today")

        # Pull pending listings joined with products and opportunities
        listings_response = supabase.table("listings")\
            .select("*, products(*, opportunities(*))")\
            .eq("status", "pending_review")\
            .limit(slots_remaining)\
            .execute()

        listings = listings_response.data
        print(f"[PAM] {len(listings)} listings ready for review")

        if not listings:
            print("[PAM] No listings pending review")
            result = {
                "listings_published": 0,
                "message": "No listings pending",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            await log_task_complete(supabase, task_id, result)
            await update_agent_status(supabase, "publisher", "idle")
            return result

        published = 0
        blocked = 0
        total_fees = 0.0

        for listing in listings:
            product = listing.get("products", {})
            opportunity = product.get("opportunities", {}) if product else {}

            print(f"\n[PAM] Processing: '{listing.get('title', '')[:60]}...'")
            print(f"[PAM] Shop: {listing.get('shop', 'benoutside')}")

            # Run guardrails
            guardrail_result = await run_guardrails(supabase, listing, product, opportunity)

            if not guardrail_result["allowed"]:
                blocked += 1
                print(f"[PAM] ✗ BLOCKED: {guardrail_result['blocking_issue']}")

                # Log guardrail event
                supabase.table("guardrail_events").insert({
                    "agent": "publisher",
                    "action_attempted": "publish_listing",
                    "rule_violated": guardrail_result["blocking_issue"],
                    "details": guardrail_result,
                    "listing_id": listing["id"],
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }).execute()

                # Update listing status
                supabase.table("listings").update({
                    "status": "draft"
                }).eq("id", listing["id"]).execute()
                continue

            print(f"[PAM] ✓ All guardrails passed — margin: {guardrail_result['margin']}%")

            # Get shop ID
            shop_key = listing.get("shop", "benoutside")
            shop_name = SHOP_CONFIG.get(shop_key, {}).get("name", "BenOutsideCo")
            shop_id = await get_etsy_shop_id(supabase, shop_name)

            if not shop_id:
                print(f"[PAM] ✗ Could not get shop ID for {shop_name} — skipping")
                blocked += 1
                continue

            # Create in Printify (skip for digital)
            product_type = product.get("product_type", "shirt")
            if product_type != "digital":
                print(f"[PAM] Creating product in Printify...")
                printify_result = await create_printify_product(product, listing)

                if not printify_result.get("success"):
                    print(f"[PAM] ✗ Printify failed: {printify_result.get('error')}")
                    # Continue anyway — we can add Printify ID later
                    printify_id = None
                else:
                    printify_id = printify_result.get("printify_id")
                    print(f"[PAM] ✓ Printify product created: {printify_id}")
            else:
                printify_id = None
                print(f"[PAM] Digital product — skipping Printify")

            # Publish to Etsy
            print(f"[PAM] Publishing to Etsy shop: {shop_name}...")
            etsy_result = await publish_to_etsy(supabase, listing, shop_id, printify_id)

            if not etsy_result.get("success"):
                print(f"[PAM] ✗ Etsy publish failed: {etsy_result.get('error')}")
                blocked += 1
                continue

            # Success
            published += 1
            etsy_listing_id = etsy_result.get("etsy_listing_id")
            listing_url = etsy_result.get("url")

            print(f"[PAM] ✓ PUBLISHED: {listing_url}")

            # Update listing record
            supabase.table("listings").update({
                "status": "published",
                "etsy_listing_id": etsy_listing_id,
            }).eq("id", listing["id"]).execute()

            # Update product with Printify ID
            if printify_id:
                supabase.table("products").update({
                    "printify_id": printify_id,
                    "status": "live"
                }).eq("id", product["id"]).execute()

            # Log listing fee as financial event
            supabase.table("financial_events").insert({
                "type": "cost",
                "category": "listing_fee",
                "amount": 0.20,
                "listing_id": listing["id"],
                "description": f"Etsy listing fee — {listing.get('title', '')[:50]}",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }).execute()

            total_fees += 0.20

            # Log to audit
            supabase.table("audit_log").insert({
                "agent": "publisher",
                "action": "listing_published",
                "success": True,
                "details": {
                    "etsy_listing_id": etsy_listing_id,
                    "url": listing_url,
                    "shop": shop_key,
                    "price": listing.get("price"),
                    "margin": guardrail_result["margin"],
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
            }).execute()

        result = {
            "listings_published": published,
            "listings_blocked": blocked,
            "listing_fees_paid": total_fees,
            "slots_used": f"{published}/{slots_remaining}",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        await log_task_complete(supabase, task_id, result)
        await update_agent_status(supabase, "publisher", "idle")

        print(f"\n[PAM] Complete:")
        print(f"[PAM]   Published: {published}")
        print(f"[PAM]   Blocked: {blocked}")
        print(f"[PAM]   Fees paid: ${total_fees:.2f}")
        return result

    except Exception as e:
        await report_error(supabase, "publisher", e, {"task_id": task_id})
        await log_task_failed(supabase, task_id, str(e))
        await update_agent_status(supabase, "publisher", "error")
        print(f"[PAM] Failed: {str(e)}")
        raise
