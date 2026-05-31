# ============================================
# APEX V3 — Recon Agent (Rico)
# The House of Packard
# ============================================
# Rico's job: Study the top 3-5 winning shops
# in each validated niche. Document their exact
# playbook so Dennis and Cody know exactly
# what to build and write.
# ============================================

import os
import json
import httpx
from anthropic import Anthropic
from datetime import datetime, timezone
from helpers import log_task_start, log_task_complete, log_task_failed, update_agent_status
from observability import report_error
from token_manager import get_etsy_headers

ETSY_API_BASE = "https://openapi.etsy.com/v3"

async def get_top_listings(supabase, query: str, limit: int = 10) -> list:
    """
    Pulls the top listings for a given search query.
    Rico uses these to study what's winning.
    """
    try:
        headers = await get_etsy_headers(supabase)
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{ETSY_API_BASE}/application/listings/active",
                headers=headers,
                params={
                    "keywords": query,
                    "limit": limit,
                    "sort_on": "score",
                    "sort_order": "desc",
                    "includes": ["Shop", "Images"],
                },
                timeout=30.0
            )
            if response.status_code == 200:
                return response.json().get("results", [])
            else:
                print(f"[RICO] Etsy API error: {response.status_code}")
                return []
    except Exception as e:
        print(f"[RICO] Search error: {str(e)}")
        return []


async def build_playbook(client: Anthropic, opportunity: dict, listings: list) -> dict:
    """
    Sends top listing data to Claude and asks it
    to reverse engineer the winning playbook.
    Rico produces a blueprint Dennis and Cody
    follow exactly.
    """
    listing_data = []
    for l in listings[:8]:
        listing_data.append({
            "title": l.get("title", "")[:120],
            "price": l.get("price", {}).get("amount", 0) / max(l.get("price", {}).get("divisor", 100), 1),
            "views": l.get("views", 0),
            "num_favorers": l.get("num_favorers", 0),
            "tags": l.get("tags", []),
            "description_preview": (l.get("description", "") or "")[:200],
        })

    prompt = f"""You are Rico, the Recon agent for APEX V3. You study winning Etsy listings and extract the exact playbook that makes them successful.

VALIDATED OPPORTUNITY:
Title: {opportunity.get('title')}
Niche: {opportunity.get('niche')}
Specific Angle: {opportunity.get('specific_angle')}
Validated Score: {opportunity.get('final_score')}/100
Entry Strategy: {opportunity.get('evidence', {}).get('validation', {}).get('recommended_entry_strategy', 'Not specified')}

TOP LISTINGS DATA:
{json.dumps(listing_data, indent=2)}

Your job is to reverse engineer exactly what's working. Be specific and actionable — Dennis and Cody will follow this blueprint exactly.

Analyze the listings and produce a complete playbook covering:

1. DESIGN PLAYBOOK
   - What aesthetic dominates? (minimalist, bold, vintage, typography, illustrated)
   - What colors appear most in winning listings?
   - What font style? (serif, sans-serif, script, hand-lettered)
   - What makes the thumbnail pop in search results?
   - Specific design dos and don'ts for this niche

2. COPY PLAYBOOK  
   - What title formula do winners use? (Extract the pattern, not specific text)
   - What keywords appear across multiple winning titles?
   - What tone converts? (funny, heartfelt, professional, insider)
   - What tags appear most frequently?
   - Description structure that winners use

3. PRICING PLAYBOOK
   - What price range do winners cluster at?
   - What's the recommended entry price for us?
   - Do winners use sales/discounts?

4. PRODUCT PLAYBOOK
   - Which product types dominate? (shirt, mug, poster, digital, etc.)
   - What variations do winners offer?
   - How many listings do top shops have in this niche?

Respond ONLY with valid JSON:
{{
  "playbook_ready": true,
  "niche": "{opportunity.get('niche')}",
  "analyzed_listing_count": 0,

  "design_playbook": {{
    "dominant_aesthetic": "describe the visual style",
    "color_palette": ["color1", "color2", "color3"],
    "typography_style": "describe font approach",
    "thumbnail_formula": "what makes thumbnails pop",
    "design_dos": ["specific thing to do"],
    "design_donts": ["specific thing to avoid"],
    "complexity_level": "simple|moderate|complex",
    "ai_generation_approach": "specific prompt strategy for this niche"
  }},

  "copy_playbook": {{
    "title_formula": "the pattern winners follow",
    "title_keywords": ["keyword1", "keyword2", "keyword3"],
    "tone": "funny|heartfelt|professional|insider|inspirational",
    "tag_themes": ["theme1", "theme2", "theme3"],
    "description_structure": "how winners format descriptions",
    "hook_phrases": ["phrase that works in this niche"]
  }},

  "pricing_playbook": {{
    "price_range_min": 0.00,
    "price_range_max": 0.00,
    "sweet_spot": 0.00,
    "recommended_entry_price": 0.00,
    "use_sale_pricing": false,
    "pricing_notes": "any pricing strategy observations"
  }},

  "product_playbook": {{
    "primary_product_type": "shirt|mug|poster|digital|sticker",
    "secondary_products": ["product1", "product2"],
    "recommended_variations": ["variation1", "variation2"],
    "listings_to_launch": 3,
    "variation_strategy": "how to create variants"
  }},

  "competitive_insight": "one key observation about what separates winners from losers in this niche",
  "confidence": "high|medium|low"
}}"""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1500,
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
        print(f"[RICO] JSON parse error: {e}")
        return None


async def run_recon(supabase):
    """
    Rico's full routine:
    1. Pull all validated opportunities
    2. Search Etsy for top listings in each niche
    3. Reverse engineer the winning playbook
    4. Write playbook to the opportunity record
    5. Flag as ready for Dennis and Cody
    """
    task_id = await log_task_start(
        supabase, "recon", "research",
        "shop_analysis",
        {"mode": "live", "scheduled": True}
    )

    try:
        await update_agent_status(supabase, "recon", "running")
        print(f"\n[RICO] Starting recon at {datetime.now(timezone.utc)}")

        anthropic_key = os.getenv("ANTHROPIC_API_KEY")
        client = Anthropic(api_key=anthropic_key)

        # Pull validated opportunities
        response = supabase.table("opportunities")\
            .select("*")\
            .eq("status", "validated")\
            .order("final_score", desc=True)\
            .limit(15)\
            .execute()

        opportunities = response.data
        print(f"[RICO] {len(opportunities)} validated opportunities to recon")

        playbooks_built = 0
        total_cost = 0.0
        total_tokens = 0

        for opp in opportunities:
            print(f"[RICO] Reconning: '{opp.get('title')}' (Score: {opp.get('final_score')})")

            try:
                # Search Etsy for top listings in this niche
                search_term = opp.get("specific_angle") or opp.get("niche") or opp.get("title")
                listings = await get_top_listings(supabase, search_term)

                if not listings:
                    print(f"[RICO] No listings found for '{search_term}' — skipping")
                    continue

                print(f"[RICO] Analyzing {len(listings)} listings for '{opp.get('title')}'")

                # Build the playbook
                playbook = await build_playbook(client, opp, listings)

                if not playbook:
                    continue

                total_cost += playbook.get("cost_usd", 0)
                total_tokens += playbook.get("tokens_used", 0)

                # Write playbook to opportunity record
                supabase.table("opportunities").update({
                    "status": "in_production",
                    "playbook": playbook
                }).eq("id", opp["id"]).execute()

                playbooks_built += 1
                print(f"[RICO] ✓ Playbook built: '{opp.get('title')}'")
                print(f"[RICO]   Aesthetic: {playbook.get('design_playbook', {}).get('dominant_aesthetic')}")
                print(f"[RICO]   Entry price: ${playbook.get('pricing_playbook', {}).get('recommended_entry_price')}")
                print(f"[RICO]   Product: {playbook.get('product_playbook', {}).get('primary_product_type')}")

                # Budget check
                if total_cost >= 5.0:
                    print(f"[RICO] Budget limit approaching (${total_cost:.2f}) — stopping")
                    break

            except Exception as e:
                print(f"[RICO] Error on '{opp.get('title')}': {str(e)}")
                continue

        result = {
            "opportunities_reconned": len(opportunities),
            "playbooks_built": playbooks_built,
            "total_cost_usd": round(total_cost, 4),
            "total_tokens": total_tokens,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        await log_task_complete(
            supabase, task_id, result,
            cost_tokens=total_tokens,
            cost_usd=total_cost
        )
        await update_agent_status(supabase, "recon", "idle")

        print(f"\n[RICO] Complete:")
        print(f"[RICO]   Playbooks built: {playbooks_built}")
        print(f"[RICO]   Cost: ${total_cost:.4f}")
        return result

    except Exception as e:
        await report_error(supabase, "recon", e, {"task_id": task_id})
        await log_task_failed(supabase, task_id, str(e))
        await update_agent_status(supabase, "recon", "error")
        print(f"[RICO] Failed: {str(e)}")
        raise
