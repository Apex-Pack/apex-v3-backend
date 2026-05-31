# ============================================
# APEX V3 — Designer Agent (Dennis)
# The House of Packard
# ============================================

import os
import json
import httpx
import base64
import io
from anthropic import Anthropic
from datetime import datetime, timezone
from helpers import log_task_start, log_task_complete, log_task_failed, update_agent_status
from observability import report_error

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
DRIVE_FOLDER_ID = "1n9f2z-ZhnZOFjSdcXrUeT3L_ofCYNloS"


def get_drive_service():
    """
    Authenticates to Google Drive using the service account
    credentials stored in Railway environment variables.
    """
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    service_account_info = json.loads(os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON"))
    credentials = service_account.Credentials.from_service_account_info(
        service_account_info,
        scopes=["https://www.googleapis.com/auth/drive"]
    )
    return build("drive", "v3", credentials=credentials)


async def upload_to_drive(image_data: str, mime_type: str, filename: str) -> dict:
    """
    Uploads a base64 image to the APEX Designs folder in Google Drive.
    Returns the file ID and web view link.
    """
    try:
        from googleapiclient.http import MediaIoBaseUpload

        drive = get_drive_service()
        image_bytes = base64.b64decode(image_data)
        file_stream = io.BytesIO(image_bytes)

        file_metadata = {
            "name": filename,
            "parents": [DRIVE_FOLDER_ID]
        }

        media = MediaIoBaseUpload(
            file_stream,
            mimetype=mime_type,
            resumable=False
        )

        file = drive.files().create(
            body=file_metadata,
            media_body=media,
            fields="id, webViewLink, name"
        ).execute()

        return {
            "success": True,
            "file_id": file.get("id"),
            "view_link": file.get("webViewLink"),
            "filename": file.get("name")
        }

    except Exception as e:
        print(f"[DENNIS] Drive upload error: {str(e)}")
        return {"success": False, "error": str(e)}


async def generate_design_prompt(client: Anthropic, opportunity: dict, playbook: dict, variant: int) -> tuple:
    """
    Uses Claude to craft the perfect image generation
    prompt based on Rico's playbook.
    """
    design_playbook = playbook.get("design_playbook", {})
    copy_playbook = playbook.get("copy_playbook", {})
    product_type = playbook.get("product_playbook", {}).get("primary_product_type", "shirt")

    variant_directions = {
        1: "primary design — follow the playbook exactly",
        2: "alternative color scheme — same concept, different palette",
        3: "simplified version — cleaner, more minimal than variant 1"
    }

    prompt = f"""You are Dennis, the Designer agent for APEX V3. Write a precise image generation prompt for a print-on-demand product design.

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
Tone: {copy_playbook.get('tone')}

VARIANT {variant}: {variant_directions.get(variant, 'alternative approach')}

Write a precise image generation prompt. It must:
1. Specify "white background" for clean POD results
2. Specify "high contrast" for thumbnail visibility
3. Include "vector style flat design" for clean print results
4. Describe specific visual elements, colors, composition
5. Be under 150 words

CRITICAL RULES:
- NO trademarked brands, logos, or characters
- NO photorealistic human faces
- NO text or words in the image
- Designs must work at print resolution

Respond with ONLY the image prompt — no preamble, no explanation."""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}]
    )

    tokens_used = message.usage.input_tokens + message.usage.output_tokens
    cost = (message.usage.input_tokens * 0.000003) + (message.usage.output_tokens * 0.000015)
    return message.content[0].text.strip(), tokens_used, cost


async def generate_image(prompt: str) -> dict:
    """
    Calls the Gemini image generation API.
    Returns image data and metadata.
    """
    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.post(
                f"{GEMINI_API_BASE}/models/gemini-2.5-flash-image:generateContent",
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
                error_text = response.text[:300]
                print(f"[DENNIS] Gemini API error: {response.status_code} — {error_text}")
                return {"success": False, "error": f"API error {response.status_code}"}

    except Exception as e:
        print(f"[DENNIS] Image generation error: {str(e)}")
        return {"success": False, "error": str(e)}


async def save_design(supabase, opportunity_id: str, variant: int, image_data: str, mime_type: str, prompt: str, product_type: str, drive_link: str = None, drive_file_id: str = None) -> dict:
    """
    Saves design to Supabase products table with Drive link.
    """
    try:
        extension = "png" if "png" in mime_type else "jpg"
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
                "image_data": image_data,
                "has_image": True,
                "drive_link": drive_link,
                "drive_file_id": drive_file_id,
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
    1. Pull opportunities with playbooks
    2. Generate design prompts using Claude
    3. Generate images using Gemini
    4. Upload to Google Drive
    5. Save designs to products table with Drive links
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

        if not opportunities:
            print("[DENNIS] No opportunities ready — check that Rico has run first")
            result = {
                "opportunities_processed": 0,
                "designs_created": 0,
                "total_cost_usd": 0,
                "total_tokens": 0,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            await log_task_complete(supabase, task_id, result)
            await update_agent_status(supabase, "designer", "idle")
            return result

        designs_created = 0
        total_cost = 0.0
        total_tokens = 0

        for opp in opportunities:
            playbook = opp.get("playbook", {})
            if not playbook:
                print(f"[DENNIS] No playbook for '{opp.get('title')}' — skipping")
                continue

            product_type = playbook.get("product_playbook", {}).get("primary_product_type", "shirt")
            opp_title_clean = opp.get('title', 'design').replace(' ', '_').replace('/', '_')[:40]
            print(f"\n[DENNIS] Designing: '{opp.get('title')}' ({product_type})")

            variants_created = 0

            for variant in [1, 2]:
                print(f"[DENNIS] Generating variant {variant}...")

                # Generate prompt using Claude
                design_prompt, tokens, cost = await generate_design_prompt(client, opp, playbook, variant)
                total_tokens += tokens
                total_cost += cost

                print(f"[DENNIS] Prompt: {design_prompt[:120]}...")

                # Generate image using Gemini
                image_result = await generate_image(design_prompt)

                if image_result.get("success"):
                    # Upload to Google Drive
                    extension = "png" if "png" in image_result["mime_type"] else "jpg"
                    filename = f"{opp_title_clean}_v{variant}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.{extension}"

                    drive_result = await upload_to_drive(
                        image_result["image_data"],
                        image_result["mime_type"],
                        filename
                    )

                    if drive_result.get("success"):
                        print(f"[DENNIS] ✓ Uploaded to Drive: {drive_result.get('view_link')}")
                    else:
                        print(f"[DENNIS] ✗ Drive upload failed: {drive_result.get('error')}")

                    # Save to Supabase with Drive link
                    save_result = await save_design(
                        supabase,
                        opp["id"],
                        variant,
                        image_result["image_data"],
                        image_result["mime_type"],
                        design_prompt,
                        product_type,
                        drive_link=drive_result.get("view_link"),
                        drive_file_id=drive_result.get("file_id")
                    )

                    if save_result.get("success"):
                        variants_created += 1
                        designs_created += 1
                        print(f"[DENNIS] ✓ Variant {variant} saved — Product ID: {save_result.get('product_id')}")
                    else:
                        print(f"[DENNIS] ✗ Save failed: {save_result.get('error')}")
                else:
                    print(f"[DENNIS] ✗ Image generation failed: {image_result.get('error')}")

            if variants_created > 0:
                print(f"[DENNIS] ✓ '{opp.get('title')}' — {variants_created} variants created")
            else:
                print(f"[DENNIS] ✗ No variants created for '{opp.get('title')}'")

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
