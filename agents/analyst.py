# ============================================
# APEX V3 — Analyst Agent (Alan)
# The House of Packard
# ============================================
# Alan's job: Take Scout's raw opportunities
# and prosecute them hard before validating.
# Must try to KILL every opportunity first.
# Only survivors get passed to Recon.
# ============================================

import os
import json
from anthropic import Anthropic
from datetime import datetime, timezone
from helpers import log_task_start, log_task_complete, log_task_failed, update_agent_status
from observability import report_error

async def prosecute_opportunity(client: Anthropic, opportunity: dict) -> dict:
    """
    Phase 1 — Prosecution.
    Alan's job is to find every reason this
    opportunity will FAIL before validating it.
    This is confirmation bias protection.
    """
    prompt = f"""You are Alan, the Analyst agent for APEX V3. Your job is PROSECUTION — finding every reason this opportunity will fail.

You must be a skeptic. You are looking for problems, not opportunities.

OPPORTUNITY TO PROSECUTE:
Title: {opportunity.get('title')}
Niche: {opportunity.get('niche')}
Specific Angle: {opportunity.get('specific_angle')}
Scout Score: {opportunity.get('final_score')}/100
Scout Decision: {opportunity.get('source_data', {}).get('decision')}
Average Price: ${opportunity.get('source_data', {}).get('avg_price', 0):.2f}
Estimated Margin: {opportunity.get('source_data', {}).get('estimated_margin_pct', 0)}%
Key Risk Identified: {opportunity.get('source_data', {}).get('key_risk')}

PROSECUTION CHECKLIST — Answer each honestly:
1. Is this niche likely oversaturated with established shops that dominate page 1?
2. Is the margin realistic after ALL Etsy fees (6.5% transaction + 3% + $0.25 processing + $0.20 listing + Printify base ~$10-14 for shirts)?
3. Is there any trademark, copyright, or IP risk in this niche?
4. Is demand seasonal and are we past the peak window?
5. Is the competition so strong that a new listing would never rank on page 1?
6. Are there any platform policy risks with this product type?

KILL TRIGGERS — Automatically reject if any apply:
- Estimated real margin after ALL fees drops below 25%
- Clear trademark or IP risk exists
- Niche is dominated by shops with 10,000+ sales and 500+ reviews per listing
- Seasonal product where peak is more than 60 days away or already passed
- Any Etsy policy violation risk

Respond ONLY with valid JSON:
{{
  "prosecution_result": "SURVIVED|REJECTED",
  "concerns_found": ["list of specific concerns, even if survived"],
  "kill_triggers_hit": ["list any kill triggers that fired, empty if none"],
  "real_margin_estimate": 0.0,
  "confidence_in_rejection": "high|medium|low",
  "prosecution_reasoning": "2-3 sentence summary of your prosecution findings"
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
    """
    Phase 2 — Validation.
    Only runs if prosecution was survived.
    Confirms the opportunity is real and
    attaches a risk profile.
    """
    prompt = f"""You are Alan, the Analyst agent for APEX V3. This opportunity survived prosecution. Now validate it properly.

OPPORTUNITY:
Title: {opportunity.get('title')}
Niche: {opportunity.get('niche')}
Specific Angle: {opportunity.get('specific_angle')}
Scout Score: {opportunity.get('final_score')}/100
Average Price: ${opportunity.get('source_data', {}).get('avg_price', 0):.2f}

PROSECUTION FINDINGS (survived but had these concerns):
{json.dumps(prosecution.get('concerns_found', []), indent=2)}

Prosecution reasoning: {prosecution.get('prosecution_reasoning')}
Real margin estimate: {prosecution.get('real_margin_estimate')}%

VALIDATION TASKS:
1. Confirm demand is real — is there genuine buyer intent for this specific angle?
2. Confirm margin is viable — at the average price, after all fees, is 30%+ achievable?
3. Confirm new entrant can rank — is there evidence a new shop could appear on page 1?
4. Assign risk profile — how risky is this opportunity overall?

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
  "top_3_failure_reasons": [
    "reason 1",
    "reason 2",
    "reason 3"
  ],
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
    """
    Alan's full routine:
    1. Pull all raw opportunities from Supabase
    2. Prosecute each one — try to kill it
    3. Validate survivors
    4. Update opportunity records with verdicts
    5. Flag validated ones for Recon
    """
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

        # Pull all raw opportunities Scout found
        response = supabase.table("opportunities")\
            .select("*")\
            .eq("status", "raw")\
            .order("final_score", desc=True)\
            .execute()

        opportunities = response.data
        print(f"[ALAN] {len(opportunities)} raw opportunities to prosecute")

        prosecuted = 0
        survived = 0
        validated = 0
        rejected = 0
        total_cost = 0.0
        total_tokens = 0

        for opp in opportunities:
            print(f"[ALAN] Prosecuting: '{opp.get('title')}' (Score: {opp.get('final_score')})")

            try:
                # Phase 1 — Prosecution
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
                    # Killed in prosecution
                    rejected += 1
                    supabase.table("opportunities").update({
                        "status": "rejected",
                        "prosecution_result": "rejected",
                        "prosecution_concerns": prosecution.get("concerns_found", []),
                    }).eq("id", opp["id"]).execute()
                    print(f"[ALAN] ✗ KILLED in prosecution: '{opp.get('title')}'")
                    print(f"[ALAN]   Reason: {prosecution.get('prosecution_reasoning')}")
                    continue

                # Survived prosecution
                survived += 1
                print(f"[ALAN] ✓ Survived prosecution: '{opp.get('title')}'")

                # Phase 2 — Validation
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
                    # Validated — ready for Recon
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

                    print(f"[ALAN] ✓ VALIDATED: '{opp.get('title')}' — Adjusted Score: {adjusted_score}")
                    print(f"[ALAN]   Strategy: {validation.get('recommended_entry_strategy')}")

                # Budget check
                if total_cost >= 6.0:
                    print(f"[ALAN] Budget limit approaching (${total_cost:.2f}) — stopping early")
                    break

            except Exception as e:
                print(f"[ALAN] Error processing '{opp.get('title')}': {str(e)}")
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
