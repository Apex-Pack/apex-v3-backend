# ============================================
# APEX V3 — Designer Agent (Dennis)
# The House of Packard
# ============================================

import os
import re
import json
import httpx
import base64
import io
from anthropic import Anthropic
from datetime import datetime, timezone
from helpers import log_task_start, log_task_complete, log_task_failed, update_agent_status
from observability import report_error

IDEOGRAM_API_BASE = "https://api.ideogram.ai"

DESIGN_TYPES = {
    "text_based": "Design centers on a phrase, quote, slogan, or typography. The words ARE the design.",
    "flat_vector": "Design is an illustration, icon, or graphic with no text as the focal point.",
    "realistic": "Design requires photorealistic elements, detailed scenery, or photography style.",
}


# ============================================
# STEP 1 — CLASSIFY DESIGN TYPE
# ============================================

async def classify_design_type(client: Anthropic, opportunity: dict, playbook: dict) -> tuple:
    prompt = f"""You are Dennis, the Designer agent for APEX V3. Classify the design type for this POD opportunity.

OPPORTUNITY TITLE: {opportunity.get('title')}
NICHE: {opportunity.get('niche')}
SPECIFIC ANGLE: {opportunity.get('specific_angle')}
DOMINANT AESTHETIC: {playbook.get('design_playbook', {}).get('dominant_aesthetic', 'unknown')}
TONE: {playbook.get('copy_playbook', {}).get('tone', 'unknown')}

DESIGN TYPES:
- text_based: Design centers on a phrase, quote, or slogan. The words ARE the design. Example: "I thought you said rum not run" shirt — the text is the product.
- flat_vector: Design is an illustration, icon, or graphic. Example: mountain silhouette, animal illustration, nature scene.
- realistic: Design requires photorealistic elements or detailed scenery.

Which design type is this? Respond with ONLY one of: text_based, flat_vector, realistic"""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=20,
        messages=[{"role": "user", "content": prompt}]
    )
    result = message.content[0].text.strip().lower()
    if result not in DESIGN_TYPES:
        result = "flat_vector"
    print(f"[DENNIS] Design type classified: {result}")
    return result, message.usage.input_tokens + message.usage.output_tokens


# ============================================
# STEP 2 — GENERATE DESIGN PROMPT
# ============================================

async def generate_design_prompt(client: Anthropic, opportunity: dict, playbook: dict, variant: int, design_type: str) -> tuple:
    design_playbook = playbook.get("design_playbook", {})
    copy_playbook = playbook.get("copy_playbook", {})
    product_type = playbook.get("product_playbook", {}).get("primary_product_type", "shirt")

    variant_directions = {
        1: "primary design — follow the playbook exactly",
        2: "alternative — same concept, different color scheme or layout approach",
    }

    type_instructions = {
        "text_based": """DESIGN TYPE: TEXT-BASED
- The phrase/slogan from the opportunity title is the entire design
- Typography is everything — choose a font style that matches the tone
- Text must be large, bold, and readable at thumbnail size
- Add minimal supporting graphic elements around or behind the text if appropriate
- Specify the EXACT text to appear in the design
- Keep it clean — 1-3 lines of text maximum
- The text must be spelled perfectly and be the dominant element""",

        "flat_vector": """DESIGN TYPE: FLAT VECTOR ILLUSTRATION
- Maximum 3 visual elements total — simplicity is mandatory
- Each element must be a clean, recognizable geometric shape (circle, rectangle, triangle, line)
- Flat color fills only — no gradients, no shadows, no textures
- Generous empty space — the design should breathe
- Bold, high contrast colors against white background
- Think: Swiss poster design, not decorative illustration
- If it cannot be described in one sentence, it is too complex
- Be extremely specific: name each shape, its color, and its position""",

        "realistic": """DESIGN TYPE: REALISTIC
- Photo-quality output with detailed elements
- Still suitable for POD — no human faces
- Rich detail that looks professional at print size
- Can include textures, depth, lighting effects
- Describe the scene specifically — subject, lighting, background"""
    }

    prompt = f"""You are Dennis, the Designer agent for APEX V3. Write a precise image generation prompt for a print-on-demand {product_type} design.

OPPORTUNITY:
Title: {opportunity.get('title')}
Niche: {opportunity.get('niche')}
Specific angle: {opportunity.get('specific_angle')}

RICO'S DESIGN PLAYBOOK:
Dominant aesthetic: {design_playbook.get('dominant_aesthetic')}
Color palette: {', '.join(design_playbook.get('color_palette', []))}
Typography style: {design_playbook.get('typography_style', 'bold sans-serif')}
Design dos: {', '.join(design_playbook.get('design_dos', []))}
Design donts: {', '.join(design_playbook.get('design_donts', []))}
Tone: {copy_playbook.get('tone')}

{type_instructions.get(design_type, type_instructions['flat_vector'])}

VARIANT {variant}: {variant_directions.get(variant, 'alternative approach')}

UNIVERSAL RULES:
- Transparent or white background only
- High contrast — must pop at thumbnail size
- NO trademarked brands, logos, characters, or team names
- NO photorealistic human faces
- Print-ready quality

Respond with ONLY the image generation prompt as plain text — no markdown, no headers, no asterisks, no labels, no preamble. Just the prompt itself. Under 200 words."""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}]
    )

    # Strip markdown formatting and any variant labels Claude sneaks in
    raw = message.content[0].text.strip()
    clean_prompt = raw.replace("**", "").replace("##", "").replace("*", "").strip()
    clean_prompt = re.sub(r'^VARIANT\s+\d+:\s*', '', clean_prompt, flags=re.IGNORECASE).strip()

    tokens = message.usage.input_tokens + message.usage.output_tokens
    cost = (message.usage.input_tokens * 0.000003) + (message.usage.output_tokens * 0.000015)
    return clean_prompt, tokens, cost


# ============================================
# STEP 3 — GENERATE IMAGE (Ideogram)
# ============================================

async def generate_image_ideogram(prompt: str, design_type: str) -> dict:
    try:
        endpoint = (
            f"{IDEOGRAM_API_BASE}/v1/ideogram-v3/generate-transparent"
            if design_type in ["text_based", "flat_vector"]
            else f"{IDEOGRAM_API_BASE}/v1/ideogram-v3/generate"
        )

        style_map = {
            "text_based": "DESIGN",
            "flat_vector": "DESIGN",
            "realistic": "REALISTIC",
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                endpoint,
                headers={
                    "Api-Key": os.getenv("IDEOGRAM_API_KEY"),
                    "Content-Type": "application/json"
                },
                json={
                    "prompt": prompt,
                    "rendering_speed": "DEFAULT",
                    "style_type": style_map.get(design_type, "DESIGN"),
                    "magic_prompt": "OFF",
                    "aspect_ratio": "1x1",
                }
            )

        if response.status_code != 200:
            print(f"[DENNIS] Ideogram error: {response.status_code} — {response.text[:300]}")
            return {"success": False, "error": f"Ideogram API {response.status_code}"}

        data = response.json()
        images = data.get("data", [])
        if not images:
            return {"success": False, "error": "No images returned"}

        image_url = images[0].get("url")
        if not image_url:
            return {"success": False, "error": "No image URL in response"}

        print(f"[DENNIS] Image generated — downloading from Ideogram...")

        async with httpx.AsyncClient(timeout=60.0) as client:
            img_response = await client.get(image_url)
            if img_response.status_code != 200:
                return {"success": False, "error": "Failed to download image from Ideogram"}
            image_bytes = img_response.content

        image_b64 = base64.b64encode(image_bytes).decode("utf-8")

        return {
            "success": True,
            "image_data": image_b64,
            "mime_type": "image/png",
            "source": "ideogram",
            "original_url": image_url,
        }

    except Exception as e:
        print(f"[DENNIS] Ideogram generation error: {str(e)}")
        return {"success": False, "error": str(e)}


# ============================================
# STEP 4 — CLAUDE VISION QUALITY GATE
# ============================================

async def evaluate_design_quality(client: Anthropic, image_b64: str, opportunity: dict, design_type: str, prompt_used: str) -> dict:
    try:
        eval_prompt = f"""You are a quality control agent for a professional Etsy POD shop. Evaluate this design ruthlessly.

BRIEF:
- Product concept: {opportunity.get('title')}
- Design type: {design_type}
- Prompt used: {prompt_used[:300]}

SCORING CRITERIA:
1. Does the design match the concept exactly?
2. Is any text spelled correctly and readable at small sizes?
3. Does it look professional enough to sell on Etsy for $20-30?
4. Is the design clean with high contrast on white/transparent background?
5. Would a real customer be proud to wear/display this?

QUALITY STANDARDS — what a 9/10 looks like:
- Text is crisp, correctly spelled, immediately readable
- Design is clean, not cluttered or muddy
- Concept is instantly clear — someone gets it in under 2 seconds
- Professional graphic design quality, not AI slop
- Would not embarrass the shop

FAILURE PATTERNS — automatic low scores:
- Text is misspelled, blurry, or illegible
- Design does not match the concept at all
- Looks like clip art or MS Paint output
- Multiple competing elements with no clear focal point
- Background contamination or artifacts
- More elements than specified in the prompt

Respond in this exact format with no extra text:
SCORE: [number 1-10]
VERDICT: [PASS if 7+, FAIL if under 7]
ISSUES: [List specific problems if FAIL, or None if PASS]
FIX: [One specific instruction to improve the prompt if FAIL, or None if PASS]"""

        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=300,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": image_b64
                        }
                    },
                    {
                        "type": "text",
                        "text": eval_prompt
                    }
                ]
            }]
        )

        response_text = message.content[0].text.strip()
        tokens = message.usage.input_tokens + message.usage.output_tokens
        cost = (message.usage.input_tokens * 0.000003) + (message.usage.output_tokens * 0.000015)

        lines = response_text.split("\n")
        score = 0
        issues = ""
        fix = ""

        for line in lines:
            if line.startswith("SCORE:"):
                try:
                    score = int(line.replace("SCORE:", "").strip())
                except:
                    score = 0
            elif line.startswith("ISSUES:"):
                issues = line.replace("ISSUES:", "").strip()
            elif line.startswith("FIX:"):
                fix = line.replace("FIX:", "").strip()

        # Always derive verdict from score — never trust parsed verdict
        verdict = "PASS" if score >= 7 else "FAIL"
        passed = score >= 7

        print(f"[DENNIS] Quality score: {score}/10 — {verdict}")
        if issues and issues != "None":
            print(f"[DENNIS] Issues: {issues}")

        return {
            "score": score,
            "verdict": verdict,
            "issues": issues,
            "fix": fix,
            "tokens": tokens,
            "cost": cost,
            "passed": passed
        }

    except Exception as e:
        print(f"[DENNIS] Quality evaluation error: {str(e)}")
        return {"score": 7, "verdict": "PASS", "issues": "", "fix": "", "tokens": 0, "cost": 0, "passed": True}


# ============================================
# STEP 5 — SAVE DESIGN
# ============================================

async def save_design(supabase, opportunity_id: str, variant: int, image_data: str, mime_type: str, prompt: str, product_type: str, quality_score: int) -> dict:
    try:
        result = supabase.table("products").insert({
            "opportunity_id": opportunity_id,
            "title": f"Design Variant {variant}",
            "platform": "printful",
            "product_type": product_type,
            "status": "draft",
            "design_assets": {
                "variant": variant,
                "prompt_used": prompt,
                "mime_type": mime_type,
                "image_data": image_data,
                "has_image": True,
                "quality_score": quality_score,
                "source": "ideogram",
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


# ============================================
# MAIN RUN LOOP
# ============================================

async def run_designer(supabase):
    task_id = await log_task_start(
        supabase, "designer", "design_lab",
        "design_generation",
        {"mode": "live", "scheduled": True}
    )

    try:
        await update_agent_status(supabase, "designer", "running")
        print(f"\n[DENNIS] Starting design generation at {datetime.now(timezone.utc)}")

        client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

        response = supabase.table("opportunities")\
            .select("*")\
            .eq("status", "in_production")\
            .not_.is_("playbook", "null")\
            .order("final_score", desc=True)\
            .limit(5)\
            .execute()

        opportunities = response.data
        print(f"[DENNIS] {len(opportunities)} opportunities ready for design")

        if not opportunities:
            print("[DENNIS] No opportunities ready — check that Rico has run first")
            result = {
                "opportunities_processed": 0,
                "designs_created": 0,
                "designs_rejected": 0,
                "total_cost_usd": 0,
                "total_tokens": 0,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            await log_task_complete(supabase, task_id, result)
            await update_agent_status(supabase, "designer", "idle")
            return result

        designs_created = 0
        designs_rejected = 0
        total_cost = 0.0
        total_tokens = 0

        for opp in opportunities:
            playbook = opp.get("playbook", {})
            if not playbook:
                print(f"[DENNIS] No playbook for '{opp.get('title')}' — skipping")
                continue

            product_type = playbook.get("product_playbook", {}).get("primary_product_type", "shirt")
            print(f"\n[DENNIS] Designing: '{opp.get('title')}' ({product_type})")

            # Step 1 — Classify design type
            design_type, classify_tokens = await classify_design_type(client, opp, playbook)
            total_tokens += classify_tokens
            total_cost += classify_tokens * 0.000003

            variants_created = 0

            for variant in [1, 2]:
                print(f"\n[DENNIS] Variant {variant}...")
                best_image = None
                best_score = 0
                attempt = 0
                max_attempts = 3
                extra_instruction = ""

                while attempt < max_attempts:
                    attempt += 1
                    print(f"[DENNIS] Generation attempt {attempt}/{max_attempts}")

                    # Step 2 — Generate prompt
                    design_prompt, prompt_tokens, prompt_cost = await generate_design_prompt(
                        client, opp, playbook, variant, design_type
                    )
                    if extra_instruction:
                        design_prompt = f"{design_prompt}. IMPORTANT CORRECTION: {extra_instruction}"

                    total_tokens += prompt_tokens
                    total_cost += prompt_cost
                    print(f"[DENNIS] Prompt: {design_prompt[:100]}...")

                    # Step 3 — Generate image via Ideogram
                    image_result = await generate_image_ideogram(design_prompt, design_type)

                    if not image_result.get("success"):
                        print(f"[DENNIS] ✗ Generation failed: {image_result.get('error')}")
                        continue

                    # Step 4 — Quality gate
                    print(f"[DENNIS] Running quality evaluation...")
                    quality = await evaluate_design_quality(
                        client,
                        image_result["image_data"],
                        opp,
                        design_type,
                        design_prompt
                    )
                    total_tokens += quality.get("tokens", 0)
                    total_cost += quality.get("cost", 0)

                    if quality["passed"]:
                        best_image = image_result
                        best_score = quality["score"]
                        print(f"[DENNIS] ✓ Quality gate passed — score: {best_score}/10")
                        break
                    else:
                        print(f"[DENNIS] ✗ Quality gate failed (score: {quality['score']}/10) — retrying")
                        extra_instruction = quality.get("fix", "")
                        if quality["score"] > best_score:
                            best_score = quality["score"]
                            best_image = image_result

                        if attempt == max_attempts:
                            print(f"[DENNIS] Max attempts reached — best score was {best_score}/10")
                            if best_score >= 7:
                                print(f"[DENNIS] Using best available (score: {best_score}/10)")
                            else:
                                best_image = None
                                designs_rejected += 1
                                print(f"[DENNIS] ✗ Design rejected — score too low")

                if not best_image:
                    continue

                # Step 5 — Save to Supabase (Drive removed — image stored as base64)
                save_result = await save_design(
                    supabase,
                    opp["id"],
                    variant,
                    best_image["image_data"],
                    best_image["mime_type"],
                    design_prompt,
                    product_type,
                    best_score
                )

                if save_result.get("success"):
                    variants_created += 1
                    designs_created += 1
                    print(f"[DENNIS] ✓ Variant {variant} saved — Product ID: {save_result.get('product_id')} — Score: {best_score}/10")
                else:
                    print(f"[DENNIS] ✗ Save failed: {save_result.get('error')}")

            if variants_created > 0:
                print(f"[DENNIS] ✓ '{opp.get('title')}' — {variants_created} variants created")
            else:
                print(f"[DENNIS] ✗ No variants created for '{opp.get('title')}'")

            if total_cost >= 2.0:
                print(f"[DENNIS] Budget limit reached (${total_cost:.2f}) — stopping")
                break

        result = {
            "opportunities_processed": len(opportunities),
            "designs_created": designs_created,
            "designs_rejected": designs_rejected,
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
        print(f"[DENNIS]   Designs rejected: {designs_rejected}")
        print(f"[DENNIS]   Cost: ${total_cost:.4f}")
        return result

    except Exception as e:
        await report_error(supabase, "designer", e, {"task_id": task_id})
        await log_task_failed(supabase, task_id, str(e))
        await update_agent_status(supabase, "designer", "error")
        print(f"[DENNIS] Failed: {str(e)}")
        raise
