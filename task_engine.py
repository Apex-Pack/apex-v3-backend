# ============================================
# APEX V3 — Task Engine
# The House of Packard
# ============================================

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime, timezone
from supabase import Client
import traceback
from helpers import log_task_start, log_task_complete, log_task_failed, update_agent_status
from agents.scout import run_scout as scout_agent
from agents.analyst import run_analyst as analyst_agent
from agents.recon import run_recon as recon_agent
from agents.designer import run_designer as designer_agent
from agents.copywriter import run_copywriter as copywriter_agent

async def check_daily_listing_budget(supabase: Client) -> dict:
    today = datetime.now(timezone.utc).date().isoformat()
    response = supabase.table("financial_events")\
        .select("*")\
        .eq("category", "listing_fee")\
        .gte("timestamp", today)\
        .execute()
    listings_today = len(response.data)
    daily_spend = sum(e["amount"] for e in response.data)
    if listings_today >= 3:
        return {"allowed": False, "reason": f"Daily listing limit reached: {listings_today}/3"}
    if daily_spend >= 5.0:
        return {"allowed": False, "reason": f"Daily budget reached: ${daily_spend:.2f}/$5.00"}
    return {"allowed": True, "listings_today": listings_today, "spend_today": daily_spend}


async def log_guardrail_event(supabase: Client, agent: str, action: str, rule: str, details: dict):
    supabase.table("guardrail_events").insert({
        "agent": agent,
        "action_attempted": action,
        "rule_violated": rule,
        "details": details,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }).execute()


async def run_scout(supabase: Client):
    try:
        await scout_agent(supabase)
    except Exception as e:
        print(f"[SCOUT] Failed: {traceback.format_exc()}")


async def run_analyst(supabase: Client):
    try:
        await analyst_agent(supabase)
    except Exception as e:
        print(f"[ALAN] Failed: {traceback.format_exc()}")


async def run_recon(supabase: Client):
    try:
        await recon_agent(supabase)
    except Exception as e:
        print(f"[RICO] Failed: {traceback.format_exc()}")


async def run_designer(supabase: Client):
    try:
        await designer_agent(supabase)
    except Exception as e:
        print(f"[DENNIS] Failed: {traceback.format_exc()}")


async def run_copywriter(supabase: Client):
    try:
        await copywriter_agent(supabase)
    except Exception as e:
        print(f"[CODY] Failed: {traceback.format_exc()}")


async def run_publisher(supabase: Client):
    task_id = await log_task_start(supabase, "publisher", "forge", "listing_publish", {"mode": "placeholder"})
    try:
        await update_agent_status(supabase, "publisher", "running")
        await log_task_complete(supabase, task_id, {"status": "placeholder"})
        await update_agent_status(supabase, "publisher", "idle")
    except Exception as e:
        await log_task_failed(supabase, task_id, str(e))
        await update_agent_status(supabase, "publisher", "error")


async def run_treasurer(supabase: Client):
    task_id = await log_task_start(supabase, "treasurer", "treasury", "portfolio_review", {"mode": "placeholder"})
    try:
        await update_agent_status(supabase, "treasurer", "running")
        await log_task_complete(supabase, task_id, {"status": "placeholder"})
        await update_agent_status(supabase, "treasurer", "idle")
    except Exception as e:
        await log_task_failed(supabase, task_id, str(e))
        await update_agent_status(supabase, "treasurer", "error")


async def run_daily_pipeline(supabase: Client):
    print(f"\n{'='*50}")
    print(f"[APEX] Daily pipeline starting at {datetime.now(timezone.utc)}")
    print(f"{'='*50}\n")

    await run_scout(supabase)
    await run_analyst(supabase)
    await run_recon(supabase)
    await run_designer(supabase)
    await run_copywriter(supabase)

    guardrail_check = await check_daily_listing_budget(supabase)
    if guardrail_check["allowed"]:
        await run_publisher(supabase)
    else:
        print(f"[GUARDRAIL] Publisher blocked: {guardrail_check['reason']}")
        await log_guardrail_event(
            supabase, "publisher",
            "publish_listing",
            guardrail_check["reason"],
            guardrail_check
        )

    await run_treasurer(supabase)
    print(f"\n[APEX] Daily pipeline complete at {datetime.now(timezone.utc)}\n")


def create_scheduler(supabase: Client) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        run_daily_pipeline,
        CronTrigger(hour=6, minute=0),
        args=[supabase],
        id="daily_pipeline",
        name="APEX Daily Business Loop",
        replace_existing=True
    )
    scheduler.add_job(
        lambda: print(f"[APEX] System pulse at {datetime.now(timezone.utc)}"),
        "interval",
        minutes=30,
        id="system_pulse",
        name="System Health Pulse"
    )
    return scheduler
