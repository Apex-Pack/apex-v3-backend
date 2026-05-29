# ============================================
# APEX V3 — Scout Agent
# The House of Packard
# ============================================

import os
import json
import httpx
from anthropic import Anthropic
from datetime import datetime, timezone
from helpers import log_task_start, log_task_complete, log_task_failed, update_agent_status
from observability import trace_agent_call, report_error

ETSY_API_BASE = "https://openapi.etsy.com/v3"
ETSY_API_KEY = os.getenv("ETSY_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

def etsy_headers():
    access_token = os.getenv("ETSY_ACCESS_TOKEN")
    shared_secret = os.getenv("ETSY_SHARED_SECRET")
    return {
        "x-api-key": f"{ETSY_API_KEY}:{shared_secret}",
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

async def search_etsy_listings(query: str, limit: int = 25) -> dict:
    """
    Searches Etsy for listings matching a query.
    Returns listing data including prices, views,
    favorites, and shop info.
    """
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{ETSY_API_BASE}/application/listings/active",
            headers=etsy_headers(),
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
            return response.json()
        else:
            print(f"[SCOUT] Etsy API error: {response.status_code} — {response.text}")
            return {"results": [], "count": 0}

async def get_trending_searches() -> list:
    return [
        "funny hiking shirt",
        "trail running gift",
        "mountain bike tshirt",
        "camping mug funny",
        "nurse gift funny",
        "teacher appreciation gift",
        "dog mom shirt",
        "cat dad mug",
        "retirement gift funny",
        "fishing shirt funny",
        "golf gift funny",
        "gym motivation poster",
        "mental health awareness shirt",
        "introvert funny shirt",
        "bookworm gift",
        "coffee lover mug",
        "plant mom shirt",
        "astrology gift",
        "minimalist wall art",
        "funny work from home shirt",
    ]

async def analyze_opportunity(client: Anthropic, query: str, listings: list) -> dict:
    """
    Sends real Etsy listing data to Claude and
    scores the opportunity using the APEX V3 model.
    """
    listing_summary = []
    for l in listings[:10]:
        listing_summary.append({
            "title": l.get("title", "")[:100],
            "price": l.get("price", {}).get("amount", 0) / max(l.get("price", {}).get("divisor", 100), 1),
            "views": l.get("views", 0),
            "num_favorers": l.get("num_favorers", 0),
            "quantity": l.get("quantity", 0),
        })

    prompt = f"""You are Scout, the market research agent for APEX V3 — an autonomous Etsy business system.

Analyze this Etsy search opportunity and score it using the APEX V3 scoring model.

SEARCH QUERY: "{query}"

TOP LISTINGS DATA:
{json.dumps(listing_summary, indent=2)}

SCORING RUBRIC (score each 0-20, total = sum):

1. DEMAND SIGNAL (0-20): How strong is buyer demand?
   - Check: views, favorites, number of results
   - 16-20: Strong autocomplete presence, rising demand
   - 11-15: Confirmed demand, steady trend
   - 6-10: Some demand but limited signals
   - 0-5: Weak or speculative demand

2. COMPETITION WEAKNESS (0-20): How beatable is the competition?
   - Check: listing quality, price consistency, review counts
   - 16-20: Weak competition, poor listings dominate
   - 11-15: Mixed quality, some weak listings on page 1
   - 6-10: Decent competition but gaps exist
   - 0-5: Strong established shops dominate

3. MARGIN POTENTIAL (0-20): Can we make money?
   - Check: average prices in the niche
   - 16-20: Prices $35+ with demand
   - 11-15: Prices $23-35, healthy margin
   - 6-10: Prices $15-22, tight but viable
   - 0-5: Prices under $15, margin too thin

4. DESIGN FEASIBILITY (0-20): Can AI generate this?
   - 16-20: Typography, simple graphics, text-based
   - 11-15: Clean graphic design, flat vector style
   - 6-10: Moderate complexity, achievable
   - 0-5: Requires complex illustration or photorealism

5. LEGAL SAFETY (0-20): Any IP/trademark risk?
   - 16-20: Completely clean, generic themes
   - 11-15: No IP concerns, minor ambiguity
   - 6-10: Adjacent to IP territory, proceed carefully
   - 0-5: Trademarked terms or copyright risk — KILL

MANDATORY KILL CONDITIONS (return score 0 if any apply):
- Any trademarked brand names, sports teams, celebrities
- Price average under $12 (margin impossible after fees)
- Legal safety score under 10

Respond ONLY with valid JSON in this exact format:
{{
  "title": "descriptive opportunity name",
  "niche": "broad category",
  "specific_angle": "exact sub-niche or keyword cluster",
  "demand_score": 0,
  "competition_score": 0,
  "margin_score": 0,
  "design_score": 0,
  "legal_score": 0,
  "final_score": 0,
  "decision": "PURSUE|TEST|HOLD|KILL",
  "confidence": "high|medium|low",
  "key_risk": "single biggest risk",
  "avg_price": 0.00,
  "estimated_margin_pct": 0,
  "pod_viable": true,
  "digital_viable": false,
  "seasonal": false,
  "seasonal_peak": null,
  "evidence": {{
    "listing_count": 0,
    "avg_views": 0,
    "avg_favorites": 0,
    "price_range": "min-max"
  }}
}}"""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
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
        print(f"[SCOUT] JSON parse error: {e}")
        print(f"[SCOUT] Raw response: {response_text}")
        return None

async def run_scout(supabase):
    """
    Scout's full daily routine:
    1. Get list of seed search terms
    2. Search Etsy for each term
    3. Send data to Claude for scoring
    4. Write opportunities to Supabase
    5. Log everything for observability
    """
    task_id = await log_task_start(
        supabase, "scout", "research",
        "trend_analysis",
        {"mode": "live", "scheduled": True}
    )

    try:
        await update_agent_status(supabase, "scout", "running")
        print(f"\n[SCOUT] Starting trend analysis at {datetime.now(timezone.utc)}")

        client = Anthropic(api_key=ANTHROPIC_API_KEY)
        search_terms = await get_trending_searches()

        opportunities_found = 0
        opportunities_pursued = 0
        total_cost = 0.0
        total_tokens = 0

        for term in search_terms:
            print(f"[SCOUT] Scanning: '{term}'")

            try:
                etsy_data = await search_etsy_listings(term)
                listings = etsy_data.get("results", [])

                if not listings:
                    print(f"[SCOUT] No listings found for '{term}' — skipping")
                    continue

                opportunity = await analyze_opportunity(client, term, listings)

                if not opportunity:
                    continue

                total_cost += opportunity.get("cost_usd", 0)
                total_tokens += opportunity.get("tokens_used", 0)
                opportunities_found += 1

                final_score = opportunity.get("final_score", 0)
                decision = opportunity.get("decision", "KILL")

                if final_score >= 40 and decision != "KILL":
                    opportunities_pursued += 1

                    supabase.table("opportunities").insert({
                        "title": opportunity.get("title", term),
                        "niche": opportunity.get("niche", ""),
                        "specific_angle": opportunity.get("specific_angle", ""),
                        "demand_score": opportunity.get("demand_score", 0),
                        "competition_score": opportunity.get("competition_score", 0),
                        "margin_score": opportunity.get("margin_score", 0),
                        "design_score": opportunity.get("design_score", 0),
                        "legal_score": opportunity.get("legal_score", 0),
                        "final_score": final_score,
                        "status": "raw",
                        "evidence": opportunity.get("evidence", {}),
                        "pod_viable": opportunity.get("pod_viable", True),
                        "digital_viable": opportunity.get("digital_viable", False),
                        "seasonal": opportunity.get("seasonal", False),
                        "seasonal_peak": opportunity.get("seasonal_peak"),
                        "source_data": {
                            "search_term": term,
                            "decision": decision,
                            "confidence": opportunity.get("confidence", "medium"),
                            "key_risk": opportunity.get("key_risk", ""),
                            "avg_price": opportunity.get("avg_price", 0),
                            "estimated_margin_pct": opportunity.get("estimated_margin_pct", 0),
                            "tokens_used": opportunity.get("tokens_used", 0),
                            "cost_usd": opportunity.get("cost_usd", 0),
                        }
                    }).execute()

                    print(f"[SCOUT] ✓ Opportunity: '{opportunity.get('title')}' — Score: {final_score} — Decision: {decision}")
                else:
                    print(f"[SCOUT] ✗ Rejected: '{term}' — Score: {final_score} — Decision: {decision}")

                if total_cost >= 8.0:
                    print(f"[SCOUT] Daily budget limit approaching (${total_cost:.2f}) — stopping early")
                    break

            except Exception as e:
                print(f"[SCOUT] Error processing '{term}': {str(e)}")
                continue

        result = {
            "terms_scanned": len(search_terms),
            "opportunities_found": opportunities_found,
            "opportunities_pursued": opportunities_pursued,
            "total_cost_usd": round(total_cost, 4),
            "total_tokens": total_tokens,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        await log_task_complete(
            supabase, task_id, result,
            cost_tokens=total_tokens,
            cost_usd=total_cost
        )
        await update_agent_status(supabase, "scout", "idle")

        print(f"[SCOUT] Complete — {opportunities_pursued} opportunities written to database")
        print(f"[SCOUT] Cost: ${total_cost:.4f} | Tokens: {total_tokens}")
        return result

    except Exception as e:
        await report_error(supabase, "scout", e, {"task_id": task_id})
        await log_task_failed(supabase, task_id, str(e))
        await update_agent_status(supabase, "scout", "error")
        print(f"[SCOUT] Failed: {str(e)}")
        raise
