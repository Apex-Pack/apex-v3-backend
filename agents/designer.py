# ============================================
# APEX V3 — Designer Agent (Dennis)
# The House of Packard
# ============================================
# Dennis's job: Take Rico's playbooks and
# generate real product designs using the
# Gemini image generation API. Produces
# 2-3 design variants per opportunity and
# stores assets in Cloudflare R2.
# ============================================

import os
import json
import httpx
import base64
from anthropic import Anthropic
from datetime import datetime, timezone
from helpers import log_task_start, log_task_complete, log_task_failed, update_agent_status
from observability import report_error

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"

async def generate_design_prompt(client: Anthropic, opportunity: dict, playbook: dict, variant: int) -> str:
    """
    Uses Claude to craft the perfect image generation
    prompt based on Rico's playbook.
    Dennis thinks before he draws.
    """
    design_playbook = playbook.get("design_playbook", {})
    copy_playbook = playbook.get("copy_playbook", {})
    product_type = playbook.get("product_playbook", {}).get("primary_product_type", "shirt")

    variant_directions = {
        1: "primary design — follow the playbook exactly",
        2: "alternative color scheme — same concept, different palette",
        3: "simplified version — cleaner, more minimal than variant 1"
    }

    prompt = f"""You are Dennis, the Designer agent for APEX V3. Your job is to write a precise image generation prompt for a print-on-demand product design.

OPPORTUNITY:
Title: {opportunity.get('title')}
Niche: {opportunity.get('niche')}
Product Type: {product_type}

RICO'S DESIGN PLAYBOOK:
Dominant aesthetic: {design_playbook.get('dominant_aesthetic')}
Color palette: {', '.join(design_playbook.get('color_palette', []))}
Typography style: {design_playbook.get('typography_style')}
Complexity level: {design_playbook.get('complexity_level')}
AI generation approach: {design_playbook.get('ai_generation_approach')}
Design dos: {', '.join(design_playbook.get('design_dos', []))}
Design donts: {', '.join(design_playbook.get('design_donts', []))}

Tone from copy playbook: {copy_playbook.get('tone')}

VARIANT {variant}: {variant_directions.get(variant, 'alternative approach')}

Write a precise Gemini image generation prompt for this POD design. The prompt must:
1. Specify "transparent background" for apparel designs
2. Specify "high contrast" for thumbnail visibility
3. Include "vector style" or "flat design" for clean print results
4. Describe the specific visual elements, not just the concept
5. Include color specifications
6. Be under 200 words

CRITICAL RULES:
- NO trademarked brands, logos, or copyrighted characters
- NO photorealistic human faces
- NO text in the image (text will be added separately)
- Designs must be print-ready at 300 DPI

Respond with ONLY the image generation prompt — no preamble, no explanation, just the prompt itself."""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}]
    )

    return message.content[0].text.strip()


async def generate_image(prompt: str) -> dict:
    """
    Calls the Gemini image generation API with
    the prompt Dennis crafted.
    Returns the image data and metadata.
    """
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{GEMINI_API_BASE}/models/gemini-2.0-flash-preview-image-generation:generateContent",
                headers={
                    "Content-Type": "application/json",
                    "x-goog-api-key": os.getenv("GEMINI_API_KEY")
                },
                json={
                    "contents": [{
                        "parts": [{"text": prompt}]
                    }],
                    "generationConfig": {
                        "responseModalities": ["TEXT", "IMAGE"]
                    }
                }
            )

            if response.status_code == 200:
                data = response.json()
                # Extract image from response
                candidates = data.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    for part in parts:
                        if "inlineData" in part:
                            return {
                                "success": True,
                                "image_data": part["inlineData"]["data"],
                                "mime_type": part["inlineData"]["mimeType"],
                            }
                return {"success": False, "error": "No image in response"}
            else:
                print(f"[DENNIS] Gemini API error: {response.status_code} — {response.text[:200]}")
                return {"success": False, "error": f"API error {response.status_code}"}

    except Exception as e:
        print(f"[DENNIS] Image generation error: {str(e)}")
        return {"success": False, "error": str(e)}


async def save_design_to_supabase(supabase, opportunity_id: str, variant: int, image_data: str, mime_type: str, prompt: str, product_type: str) -> dict:
    """
    Saves design metadata to Supabase products table.
    Stores the image as base64 in the design_assets field
    until Cloudflare R2 is connected.
    """
    try:
        # Create product record
        result = supabase.table("products").insert({
            "opportunity_id": opportunity_id,
            "title": f"Design Variant {variant}",
            "platform": "printify",
            "product_type": product_type,
            "status": "draft",
            "design_assets": {
                "variant": variant,
                "prompt_used": prompt,
                "mime_type": mime_type,
                "image_data_preview": image_data[:100] + "...",
                "has_image": True,
                "generated_at": datetime.now(timezone.utc).isoformat()
            }
        }).execute()

        return {
            "success": True,
            "product_id": result.data[0]["id"] if result.data else None
        }
    except Exception as e:
        print(f"[DENNIS] Save error: {str(e)}")
        return {"success": False, "error": str(e)}


async def run_designer(supabase):
    """
    Dennis's full routine:
    1. Pull opportunities with status 'in_production'
    2. Read Rico's playbook for each
    3. Generate 2-3 design variants using Gemini
    4. Save designs to products table
    5. Update opportunity status
    """
    task_id = await log_task_start(
        supabase, "designer", "design_lab",
        "design_generation",
        {"mode": "live", "scheduled": True}
    )

    try:
        await update_agent_status(supabase, "designer", "running")
        print(f"\n[DENNIS] Starting design generation at {datetime.now(timezone.utc)}")

        anthropic_key = os.getenv("ANTHROPIC_API_KEY")
        client = Anthropic(api_key=anthropic_key)

        # Pull opportunities ready for design
        response = supabase.table("opportunities")\
            .select("*")\
            .eq("status", "in_production")\
            .not_.is_("playbook", "null")\
            .order("final_score", desc=True)\
            .limit(5)\
            .execute()

        opportunities = response.data
        print(f"[DENNIS] {len(opportunities)} opportunities ready for design")

        designs_created = 0
        total_cost = 0.0
        total_tokens = 0

        for opp in opportunities:
            playbook = opp.get("playbook", {})
            if not playbook:
                print(f"[DENNIS] No playbook for '{opp.get('title')}' — skipping")
                continue

            product_type = playbook.get("product_playbook", {}).get("primary_product_type", "shirt")
            print(f"\n[DENNIS] Designing: '{opp.get('title')}' ({product_type})")

            variants_created = 0

            for variant in [1, 2]:
                print(f"[DENNIS] Generating variant {variant}...")

                # Generate prompt using Claude
                design_prompt = await generate_design_prompt(client, opp, playbook, variant)
                total_tokens += 150
                total_cost += 0.002

                print(f"[DENNIS] Prompt: {design_prompt[:100]}...")

                # Generate image using Gemini
                image_result = await generate_image(design_prompt)

                if image_result.get("success"):
                    # Save to products table
                    save_result = await save_design_to_supabase(
                        supabase,
                        opp["id"],
                        variant,
                        image_result["image_data"],
                        image_result["mime_type"],
                        design_prompt,
                        product_type
                    )

                    if save_result.get("success"):
                        variants_created += 1
                        designs_created += 1
                        print(f"[DENNIS] ✓ Variant {variant} created — Product ID: {save_result.get('product_id')}")
                    else:
                        print(f"[DENNIS] ✗ Failed to save variant {variant}")
                else:
                    print(f"[DENNIS] ✗ Image generation failed for variant {variant}: {image_result.get('error')}")

            if variants_created > 0:
                print(f"[DENNIS] ✓ '{opp.get('title')}' — {variants_created} variants created")
            else:
                print(f"[DENNIS] ✗ No variants created for '{opp.get('title')}'")

            # Budget check
            if total_cost >= 3.0:
                print(f"[DENNIS] Budget limit approaching (${total_cost:.2f}) — stopping")
                break

        result = {
            "opportunities_processed": len(opportunities),
            "designs_created": designs_created,
            "total_cost_usd": round(total_cost, 4),
            "total_tokens": total_tokens,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        await log_task_complete(
            supabase, task_id, result,
            cost_tokens=total_tokens,
            cost_usd=total_cost
        )
        await update_agent_status(supabase, "designer", "idle")

        print(f"\n[DENNIS] Complete:")
        print(f"[DENNIS]   Designs created: {designs_created}")
        print(f"[DENNIS]   Cost: ${total_cost:.4f}")
        return result

    except Exception as e:
        await report_error(supabase, "designer", e, {"task_id": task_id})
        await log_task_failed(supabase, task_id, str(e))
        await update_agent_status(supabase, "designer", "error")
        print(f"[DENNIS] Failed: {str(e)}")
        raise
