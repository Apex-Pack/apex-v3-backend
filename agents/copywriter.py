# ============================================
# APEX V3 — Copywriter Agent (Cody)
# The House of Packard
# ============================================
# Cody's job: Take Rico's playbook and Dennis's
# designs and write complete Etsy listing copy.
# 140-char title, full description, 13 tags.
# SEO-optimized and conversion-focused.
# ============================================

import os
import json
from anthropic import Anthropic
from datetime import datetime, timezone
from helpers import log_task_start, log_task_complete, log_task_failed, update_agent_status
from observability import report_error


async def write_listing_copy(client: Anthropic, opportunity: dict, playbook: dict, product: dict) -> dict:
    """
    Writes complete Etsy listing copy for one product.
    Title, description, and all 13 tags.
    """
    copy_playbook = playbook.get("copy_playbook", {})
    pricing_playbook = playbook.get("pricing_playbook", {})
    product_playbook = playbook.get("product_playbook", {})
    design_playbook = playbook.get("design_playbook", {})

    product_type = product.get("product_type", "shirt")
    entry_price = pricing_playbook.get("recommended_entry_price", 24.99)
    tone = copy_playbook.get("tone", "funny")

    prompt = f"""You are Cody, the Copywriter agent for APEX V3. Write complete Etsy listing copy that converts browsers into buyers.

OPPORTUNITY:
Title: {opportunity.get('title')}
Niche: {opportunity.get('niche')}
Specific Angle: {opportunity.get('specific_angle')}
Product Type: {product_type}
Entry Price: ${entry_price}

RICO'S COPY PLAYBOOK:
Title formula: {copy_playbook.get('title_formula')}
Title keywords: {', '.join(copy_playbook.get('title_keywords', []))}
Tone: {tone}
Tag themes: {', '.join(copy_playbook.get('tag_themes', []))}
Description structure: {copy_playbook.get('description_structure')}
Hook phrases: {', '.join(copy_playbook.get('hook_phrases', []))}

DESIGN INFO:
Aesthetic: {design_playbook.get('dominant_aesthetic')}
Design variant: {product.get('title', 'Variant 1')}

ETSY SEO RULES:
- Title must be EXACTLY 140 characters or less
- Use the most searched keywords first in the title
- All 13 tags must be used — each tag max 20 characters
- Tags should be multi-word phrases buyers actually search
- First 160 chars of description appear in search — make them count
- Description should be 400-600 words

CONVERSION RULES:
- Lead with the buyer's outcome, not product features
- Use the tone from the playbook — match what converts in this niche
- Include sizing/care info for apparel
- End with a shop invitation
- No fake urgency, no review solicitation (Etsy policy violation)

Write copy that matches the {tone} tone. Be specific to this niche — not generic.

Respond ONLY with valid JSON:
{{
  "title": "exactly 140 chars or less, keyword-rich, compelling",
  "tags": [
    "tag one", "tag two", "tag three", "tag four", "tag five",
    "tag six", "tag seven", "tag eight", "tag nine", "tag ten",
    "tag eleven", "tag twelve", "tag thirteen"
  ],
  "description": "full listing description 400-600 words",
  "alt_title_1": "alternative title option 1",
  "alt_title_2": "alternative title option 2",
  "seo_hook": "first 160 chars optimized for search and clicks",
  "recommended_price": {entry_price},
  "category_suggestion": "Etsy category this belongs in"
}}"""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )

    response_text = message.content[0].text
    tokens_used = message.usage.input_tokens + message.usage.output_tokens
    cost_usd = (message.usage.input_tokens * 0.000003) + (message.usage.output_tokens * 0.000015)

    try:
        clean = response_text.strip()
        if clean.startswith("```"):
            clean = clean.split("```")[1]
            if clean.startswith("json"):
                clean = clean[4:]
        result = json.loads(clean.strip())
        result["tokens_used"] = tokens_used
        result["cost_usd"] = cost_usd
        return result
    except json.JSONDecodeError as e:
        print(f"[CODY] JSON parse error: {e}")
        print(f"[CODY] Raw response: {response_text[:200]}")
        return None


async def run_copywriter(supabase):
    """
    Cody's full routine:
    1. Pull products in draft status with opportunity playbooks
    2. Write complete listing copy for each
    3. Save copy to listings table
    4. Mark listing as ready for Pam
    """
    task_id = await log_task_start(
        supabase, "copywriter", "forge",
        "listing_copy",
        {"mode": "live", "scheduled": True}
    )

    try:
        await update_agent_status(supabase, "copywriter", "running")
        print(f"\n[CODY] Starting copy generation at {datetime.now(timezone.utc)}")

        anthropic_key = os.getenv("ANTHROPIC_API_KEY")
        client = Anthropic(api_key=anthropic_key)

        # Pull draft products that need copy
        products_response = supabase.table("products")\
            .select("*")\
            .eq("status", "draft")\
            .order("created_at", desc=True)\
            .limit(10)\
            .execute()

        products = products_response.data
        print(f"[CODY] {len(products)} products need copy")

        if not products:
            print("[CODY] No products ready — check that Dennis has run first")
            result = {
                "products_processed": 0,
                "listings_written": 0,
                "total_cost_usd": 0,
                "total_tokens": 0,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            await log_task_complete(supabase, task_id, result)
            await update_agent_status(supabase, "copywriter", "idle")
            return result

        listings_written = 0
        total_cost = 0.0
        total_tokens = 0

        for product in products:
            opportunity_id = product.get("opportunity_id")
            if not opportunity_id:
                continue

            # Get the opportunity and its playbook
            opp_response = supabase.table("opportunities")\
                .select("*")\
                .eq("id", opportunity_id)\
                .single()\
                .execute()

            opportunity = opp_response.data
            if not opportunity:
                print(f"[CODY] No opportunity found for product {product['id']} — skipping")
                continue

            playbook = opportunity.get("playbook")
            if not playbook:
                print(f"[CODY] No playbook for '{opportunity.get('title')}' — skipping")
                continue

            print(f"[CODY] Writing copy for: '{opportunity.get('title')}' — {product.get('product_type')}")

            # Write the listing copy
            copy = await write_listing_copy(client, opportunity, playbook, product)

            if not copy:
                print(f"[CODY] Failed to generate copy for product {product['id']}")
                continue

            total_cost += copy.get("cost_usd", 0)
            total_tokens += copy.get("tokens_used", 0)

            # Validate title length
            title = copy.get("title", "")
            if len(title) > 140:
                title = title[:140]
                print(f"[CODY] Title trimmed to 140 chars")

            # Validate tags — ensure exactly 13, each under 20 chars
            tags = copy.get("tags", [])[:13]
            tags = [t[:20] for t in tags]
            while len(tags) < 13:
                tags.append(f"{opportunity.get('niche', 'gift')[:18]}")

            # Save to listings table
            listing_result = supabase.table("listings").insert({
                "product_id": product["id"],
                "title": title,
                "description": copy.get("description", ""),
                "tags": tags,
                "price": copy.get("recommended_price", 24.99),
                "status": "pending_review",
            }).execute()

            if listing_result.data:
                listing_id = listing_result.data[0]["id"]
                listings_written += 1

                # Update product status to ready
                supabase.table("products").update({
                    "status": "ready",
                    "sale_price": copy.get("recommended_price", 24.99),
                }).eq("id", product["id"]).execute()

                print(f"[CODY] ✓ Listing written: '{title[:60]}...'")
                print(f"[CODY]   Tags: {', '.join(tags[:5])}...")
                print(f"[CODY]   Price: ${copy.get('recommended_price')}")
                print(f"[CODY]   Listing ID: {listing_id}")
            else:
                print(f"[CODY] ✗ Failed to save listing for product {product['id']}")

            # Budget check
            if total_cost >= 3.0:
                print(f"[CODY] Budget limit approaching (${total_cost:.2f}) — stopping")
                break

        result = {
            "products_processed": len(products),
            "listings_written": listings_written,
            "total_cost_usd": round(total_cost, 4),
            "total_tokens": total_tokens,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        await log_task_complete(
            supabase, task_id, result,
            cost_tokens=total_tokens,
            cost_usd=total_cost
        )
        await update_agent_status(supabase, "copywriter", "idle")

        print(f"\n[CODY] Complete:")
        print(f"[CODY]   Listings written: {listings_written}")
        print(f"[CODY]   Cost: ${total_cost:.4f}")
        return result

    except Exception as e:
        await report_error(supabase, "copywriter", e, {"task_id": task_id})
        await log_task_failed(supabase, task_id, str(e))
        await update_agent_status(supabase, "copywriter", "error")
        print(f"[CODY] Failed: {str(e)}")
        raise
