# ============================================
# APEX V3 — Analyst Agent (Alan)
# The House of Packard
# ============================================

import os
import json
from anthropic import Anthropic
from datetime import datetime, timezone
from helpers import log_task_start, log_task_complete, log_task_failed, update_agent_status
from observability import report_error

async def prosecute_opportunity(client: Anthropic, opportunity: dict) -> dict:
    prompt = f"""You are Alan, the Analyst agent for APEX V3. Your job is PROSECUTION — finding reasons this opportunity will fail. Be a skeptic but be accurate and evidence-based.

OPPORTUNITY TO PROSECUTE:
Title: {opportunity.get('title')}
Niche: {opportunity.get('niche')}
Specific Angle: {opportunity.get('specific_angle')}
Scout Score: {opportunity.get('final_score')}/100
Average Price: ${opportunity.get('source_data', {}).get('avg_price', 0):.2f}
Estimated Margin: {opportunity.get('source_data', {}).get('estimated_margin_pct', 0)}%
Key Risk: {opportunity.get('source_data', {}).get('key_risk')}

ACCURATE COST STRUCTURE — USE THESE EXACT NUMBERS:
- Printify t-shirt (Bella Canvas 3001): $10.50 base cost
- Printify mug (11oz ceramic): $7.00 base cost
- Printify poster (18x24): $9.00 base cost
- Etsy transaction fee: 6.5% of sale price
- Etsy payment processing: 3% + $0.25 per transaction
- Etsy listing fee: $0.20 amortized (negligible per sale)
- Offsite ads blended rate: 1.8% effective cost

REAL MARGIN FORMULA — RUN THIS MATH:
margin = sale_price - product_cost - (sale_price * 0.065) - (sale_price * 0.03 + 0.25) - (sale_price * 0.018)
margin_pct = margin / sale_price * 100

EXAMPLE — $29.99 shirt:
29.99 - 10.50 - 1.95 - 1.15 - 0.54 = $15.85 profit = 52.8% margin — VIABLE

EXAMPLE — $19.99 mug:
19.99 - 7.00 - 1.30 - 0.85 - 0.36 = $10.48 profit = 52.4% margin — VIABLE

PROSECUTION CHECKLIST — Be specific, not vague:
1. Run the actual margin math using the average price and accurate costs above
2. Is competition so entrenched that EVERY page 1 listing has 500+ reviews from shops with 10,000+ sales? (Not just "competitive" — specifically entrenched)
3. Is there a SPECIFIC named trademark or copyright risk? (Not vague "IP concerns" — name the specific brand/IP)
4. Is this seasonal AND are we more than 60 days past peak demand?
5. Is there a specific Etsy policy violation?

KILL TRIGGERS — Only reject if CLEARLY and SPECIFICALLY true:
- Real margin below 30% using accurate costs above (show your math)
- NAMED trademark/copyright — specific brand names, characters, celebrities
- EVERY page 1 listing has 500+ reviews AND shops have 10,000+ sales (not just "saturated")
- Seasonal product more than 60 days past peak

DO NOT REJECT based on:
- General "competitive" or "saturated" without page 1 domination evidence
- Vague IP concerns without naming specific trademarks
- Pessimistic cost assumptions — use accurate costs above
- Low price without running actual math first

Respond ONLY with valid JSON:
{{
  "prosecution_result": "SURVIVED|REJECTED",
  "concerns_found": ["specific concerns with evidence"],
  "kill_triggers_hit": ["specific triggers with evidence, empty if none"],
  "real_margin_estimate": 0.0,
  "margin_calculation": "show math: $X price - $Y cost - $Z fees = $W profit = X%",
  "confidence_in_rejection": "high|medium|low",
  "prosecution_reasoning": "2-3 sentences with specific evidence, not general statements"
}}"""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=800,
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
        print(f"[ALAN] JSON parse error: {e}")
        return None


async def validate_opportunity(client: Anthropic, opportunity: dict, prosecution: dict) -> dict:
    prompt = f"""You are Alan, the Analyst agent for APEX V3. This opportunity survived prosecution. Now validate it.

OPPORTUNITY:
Title: {opportunity.get('title')}
Niche: {opportunity.get('niche')}
Specific Angle: {opportunity.get('specific_angle')}
Scout Score: {opportunity.get('final_score')}/100
Average Price: ${opportunity.get('source_data', {}).get('avg_price', 0):.2f}

PROSECUTION FINDINGS (survived with these concerns):
{json.dumps(prosecution.get('concerns_found', []), indent=2)}

Margin calculation: {prosecution.get('margin_calculation')}
Real margin estimate: {prosecution.get('real_margin_estimate')}%

VALIDATION TASKS:
1. Confirm demand is real — genuine buyer intent for this specific angle?
2. Confirm margin is viable — 30%+ confirmed using accurate costs?
3. Confirm new entrant can rank — is there at least ONE page 1 listing with under 100 reviews, OR at least one shop under 1 year old on page 1?
4. Assign overall risk level

Respond ONLY with valid JSON:
{{
  "validation_result": "VALIDATED|VALIDATED_WITH_CONCERNS|REJECTED",
  "demand_confirmed": true,
  "margin_confirmed": true,
  "new_entrant_can_rank": true,
  "adjusted_score": 0,
  "risk_profile": {{
    "overall_risk": "low|medium|high",
    "seasonal_risk": "low|medium|high",
    "competition_risk": "low|medium|high",
    "margin_risk": "low|medium|high",
    "platform_risk": "low|medium|high"
  }},
  "top_3_failure_reasons": ["reason 1", "reason 2", "reason 3"],
  "recommended_entry_strategy": "one sentence on how to win in this niche",
  "tokens_used": 0,
  "cost_usd": 0.0
}}"""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=800,
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
        print(f"[ALAN] Validation JSON parse error: {e}")
        return None


async def run_analyst(supabase):
    task_id = await log_task_start(
        supabase, "analyst", "research",
        "demand_validation",
        {"mode": "live", "scheduled": True}
    )

    try:
        await update_agent_status(supabase, "analyst", "running")
        print(f"\n[ALAN] Starting prosecution at {datetime.now(timezone.utc)}")

        anthropic_key = os.getenv("ANTHROPIC_API_KEY")
        client = Anthropic(api_key=anthropic_key)

        # Reset rejected opportunities so Alan can re-evaluate with better calibration
        supabase.table("opportunities").update({
            "status": "raw"
        }).eq("status", "rejected").execute()

        supabase.table("opportunities").update({
            "status": "raw"
        }).eq("status", "analyzing").execute()

        response = supabase.table("opportunities")\
            .select("*")\
            .eq("status", "raw")\
            .order("final_score", desc=True)\
            .execute()

        opportunities = response.data
        print(f"[ALAN] {len(opportunities)} opportunities to prosecute")

        prosecuted = 0
        survived = 0
        validated = 0
        rejected = 0
        total_cost = 0.0
        total_tokens = 0

        for opp in opportunities:
            print(f"[ALAN] Prosecuting: '{opp.get('title')}' (Score: {opp.get('final_score')})")

            try:
                supabase.table("opportunities").update({
                    "status": "analyzing"
                }).eq("id", opp["id"]).execute()

                prosecution = await prosecute_opportunity(client, opp)

                if not prosecution:
                    continue

                total_cost += prosecution.get("cost_usd", 0)
                total_tokens += prosecution.get("tokens_used", 0)
                prosecuted += 1

                prosecution_result = prosecution.get("prosecution_result")

                if prosecution_result == "REJECTED":
                    rejected += 1
                    supabase.table("opportunities").update({
                        "status": "rejected",
                        "prosecution_result": "rejected",
                        "prosecution_concerns": prosecution.get("concerns_found", []),
                    }).eq("id", opp["id"]).execute()
                    print(f"[ALAN] ✗ KILLED: '{opp.get('title')}'")
                    print(f"[ALAN]   Margin: {prosecution.get('margin_calculation')}")
                    print(f"[ALAN]   Reason: {prosecution.get('prosecution_reasoning')}")
                    continue

                survived += 1
                print(f"[ALAN] ✓ Survived: '{opp.get('title')}' — Margin: {prosecution.get('real_margin_estimate')}%")
                print(f"[ALAN]   Math: {prosecution.get('margin_calculation')}")

                validation = await validate_opportunity(client, opp, prosecution)

                if not validation:
                    continue

                total_cost += validation.get("cost_usd", 0)
                total_tokens += validation.get("tokens_used", 0)

                validation_result = validation.get("validation_result")

                if validation_result == "REJECTED":
                    rejected += 1
                    supabase.table("opportunities").update({
                        "status": "rejected",
                        "prosecution_result": "survived",
                        "prosecution_concerns": prosecution.get("concerns_found", []),
                        "risk_profile": validation.get("risk_profile", {}),
                    }).eq("id", opp["id"]).execute()
                    print(f"[ALAN] ✗ Rejected in validation: '{opp.get('title')}'")
                else:
                    validated += 1
                    adjusted_score = validation.get("adjusted_score", opp.get("final_score", 0))

                    supabase.table("opportunities").update({
                        "status": "validated",
                        "prosecution_result": "survived",
                        "prosecution_concerns": prosecution.get("concerns_found", []),
                        "final_score": adjusted_score,
                        "risk_profile": validation.get("risk_profile", {}),
                        "evidence": {
                            **(opp.get("evidence") or {}),
                            "validation": {
                                "demand_confirmed": validation.get("demand_confirmed"),
                                "margin_confirmed": validation.get("margin_confirmed"),
                                "new_entrant_can_rank": validation.get("new_entrant_can_rank"),
                                "top_3_failure_reasons": validation.get("top_3_failure_reasons", []),
                                "recommended_entry_strategy": validation.get("recommended_entry_strategy"),
                                "validation_result": validation_result,
                            }
                        }
                    }).eq("id", opp["id"]).execute()

                    print(f"[ALAN] ✓ VALIDATED: '{opp.get('title')}' — Score: {adjusted_score}")
                    print(f"[ALAN]   Strategy: {validation.get('recommended_entry_strategy')}")

                if total_cost >= 6.0:
                    print(f"[ALAN] Budget limit approaching (${total_cost:.2f}) — stopping")
                    break

            except Exception as e:
                print(f"[ALAN] Error: '{opp.get('title')}': {str(e)}")
                supabase.table("opportunities").update({
                    "status": "raw"
                }).eq("id", opp["id"]).execute()
                continue

        result = {
            "opportunities_reviewed": prosecuted,
            "survived_prosecution": survived,
            "validated": validated,
            "rejected": rejected,
            "total_cost_usd": round(total_cost, 4),
            "total_tokens": total_tokens,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        await log_task_complete(
            supabase, task_id, result,
            cost_tokens=total_tokens,
            cost_usd=total_cost
        )
        await update_agent_status(supabase, "analyst", "idle")

        print(f"\n[ALAN] Complete:")
        print(f"[ALAN]   Reviewed: {prosecuted}")
        print(f"[ALAN]   Validated: {validated}")
        print(f"[ALAN]   Rejected: {rejected}")
        print(f"[ALAN]   Cost: ${total_cost:.4f}")
        return result

    except Exception as e:
        await report_error(supabase, "analyst", e, {"task_id": task_id})
        await log_task_failed(supabase, task_id, str(e))
        await update_agent_status(supabase, "analyst", "error")
        print(f"[ALAN] Failed: {str(e)}")
        raise
