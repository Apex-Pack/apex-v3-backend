# ============================================
# APEX V3 — Task Engine
# The House of Packard
# ============================================
# This is the brain's scheduler. It tells every
# agent when to wake up and run, logs every action,
# and handles failures gracefully.
# ============================================

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime, timezone
from supabase import Client
import traceback
from agents.scout import run_scout as scout_agent

# ============================================
# Task Logger
# Every agent action gets written to the tasks
# table before it runs and updated after.
# ============================================

async def log_task_start(supabase: Client, agent: str, room: str, task_type: str, input_data: dict) -> str:
    """
    Creates a task record in Supabase when an agent starts working.
    Returns the task ID so we can update it when the agent finishes.
    Think of this like clocking in at the start of a shift.
    """
    response = supabase.table("tasks").insert({
        "agent": agent,
        "room": room,
        "type": task_type,
        "status": "running",
        "input": input_data,
        "created_at": datetime.now(timezone.utc).isoformat()
    }).execute()
    
    return response.data[0]["id"]


async def log_task_complete(supabase: Client, task_id: str, output_data: dict, cost_tokens: int = 0, cost_usd: float = 0):
    """
    Updates a task record when an agent finishes successfully.
    Think of this like clocking out at the end of a shift.
    """
    supabase.table("tasks").update({
        "status": "succeeded",
        "output": output_data,
        "cost_tokens": cost_tokens,
        "cost_usd": cost_usd,
        "completed_at": datetime.now(timezone.utc).isoformat()
    }).eq("id", task_id).execute()


async def log_task_failed(supabase: Client, task_id: str, error: str, retries: int = 0):
    """
    Updates a task record when an agent fails.
    Records the error so we can debug it on the dashboard.
    """
    supabase.table("tasks").update({
        "status": "failed",
        "error": error,
        "retries": retries,
        "completed_at": datetime.now(timezone.utc).isoformat()
    }).eq("id", task_id).execute()


async def update_agent_status(supabase: Client, agent_name: str, status: str):
    """
    Updates an agent's status in the agents table.
    The dashboard reads this to show which agents are
    online, running, or idle.
    """
    supabase.table("agents").update({
        "status": status,
        "last_active": datetime.now(timezone.utc).isoformat()
    }).eq("name", agent_name).execute()


# ============================================
# Guardrail Checker
# Runs before every agent action to enforce
# the system's rules.
# ============================================

async def check_daily_listing_budget(supabase: Client) -> dict:
    """
    Checks how many listings have been published today.
    Blocks if we've hit the 3 listings/day limit.
    """
    today = datetime.now(timezone.utc).date().isoformat()
    
    response = supabase.table("financial_events")\
        .select("*")\
        .eq("category", "listing_fee")\
        .gte("timestamp", today)\
        .execute()
    
    listings_today = len(response.data)
    daily_spend = sum(e["amount"] for e in response.data)
    
    if listings_today >= 3:
        return {
            "allowed": False,
            "reason": f"Daily listing limit reached: {listings_today}/3 listings published today"
        }
    
    if daily_spend >= 5.0:
        return {
            "allowed": False,
            "reason": f"Daily listing fee budget reached: ${daily_spend:.2f}/$5.00"
        }
    
    return {
        "allowed": True,
        "listings_today": listings_today,
        "spend_today": daily_spend
    }


async def log_guardrail_event(supabase: Client, agent: str, action: str, rule: str, details: dict):
    """
    Logs every time a guardrail blocks an action.
    This is how we track what the system tried to do
    but wasn't allowed to.
    """
    supabase.table("guardrail_events").insert({
        "agent": agent,
        "action_attempted": action,
        "rule_violated": rule,
        "details": details,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }).execute()


# ============================================
# Agent Placeholders
# These are empty shells that will be filled
# in Week 2 and beyond. For now they just log
# that they ran so we can verify the scheduler
# is working correctly.
# ============================================

async def run_scout(supabase: Client):
    """
    Scout Agent — finds trending Etsy opportunities.
    Full implementation active.
    """
    try:
        await scout_agent(supabase)
    except Exception as e:
        error_msg = traceback.format_exc()
        print(f"[SCOUT] Failed: {error_msg}")

async def run_analyst(supabase: Client):
    """
    Analyst Agent — validates Scout's opportunities.
    Full implementation: Week 2, Day 7.
    """
    task_id = await log_task_start(
        supabase, "analyst", "research",
        "demand_validation",
        {"mode": "dry_run", "scheduled": True}
    )
    
    try:
        await update_agent_status(supabase, "analyst", "running")
        
        # ── ANALYST LOGIC GOES HERE (Week 2) ──
        result = {
            "status": "placeholder",
            "message": "Analyst agent placeholder — full implementation in Week 2",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        await log_task_complete(supabase, task_id, result)
        await update_agent_status(supabase, "analyst", "idle")
        print(f"[ANALYST] Completed successfully at {datetime.now(timezone.utc)}")
        
    except Exception as e:
        error_msg = traceback.format_exc()
        await log_task_failed(supabase, task_id, error_msg)
        await update_agent_status(supabase, "analyst", "error")
        print(f"[ANALYST] Failed: {str(e)}")


async def run_recon(supabase: Client):
    """
    Recon Agent — studies winning shops.
    Full implementation: Week 2, Day 8.
    """
    task_id = await log_task_start(
        supabase, "recon", "research",
        "shop_analysis",
        {"mode": "dry_run", "scheduled": True}
    )
    
    try:
        await update_agent_status(supabase, "recon", "running")
        
        # ── RECON LOGIC GOES HERE (Week 2) ──
        result = {
            "status": "placeholder",
            "message": "Recon agent placeholder — full implementation in Week 2",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        await log_task_complete(supabase, task_id, result)
        await update_agent_status(supabase, "recon", "idle")
        print(f"[RECON] Completed successfully at {datetime.now(timezone.utc)}")
        
    except Exception as e:
        error_msg = traceback.format_exc()
        await log_task_failed(supabase, task_id, error_msg)
        await update_agent_status(supabase, "recon", "error")
        print(f"[RECON] Failed: {str(e)}")


async def run_designer(supabase: Client):
    """Designer Agent — full implementation Week 3."""
    task_id = await log_task_start(supabase, "designer", "design_lab", "design_generation", {"mode": "dry_run"})
    try:
        await update_agent_status(supabase, "designer", "running")
        await log_task_complete(supabase, task_id, {"status": "placeholder"})
        await update_agent_status(supabase, "designer", "idle")
    except Exception as e:
        await log_task_failed(supabase, task_id, str(e))
        await update_agent_status(supabase, "designer", "error")


async def run_copywriter(supabase: Client):
    """Copywriter Agent — full implementation Week 3."""
    task_id = await log_task_start(supabase, "copywriter", "forge", "listing_copy", {"mode": "dry_run"})
    try:
        await update_agent_status(supabase, "copywriter", "running")
        await log_task_complete(supabase, task_id, {"status": "placeholder"})
        await update_agent_status(supabase, "copywriter", "idle")
    except Exception as e:
        await log_task_failed(supabase, task_id, str(e))
        await update_agent_status(supabase, "copywriter", "error")


async def run_publisher(supabase: Client):
    """Publisher Agent — full implementation Week 4."""
    task_id = await log_task_start(supabase, "publisher", "forge", "listing_publish", {"mode": "dry_run"})
    try:
        await update_agent_status(supabase, "publisher", "running")
        await log_task_complete(supabase, task_id, {"status": "placeholder"})
        await update_agent_status(supabase, "publisher", "idle")
    except Exception as e:
        await log_task_failed(supabase, task_id, str(e))
        await update_agent_status(supabase, "publisher", "error")


async def run_treasurer(supabase: Client):
    """Treasurer Agent — full implementation Week 5."""
    task_id = await log_task_start(supabase, "treasurer", "treasury", "portfolio_review", {"mode": "dry_run"})
    try:
        await update_agent_status(supabase, "treasurer", "running")
        await log_task_complete(supabase, task_id, {"status": "placeholder"})
        await update_agent_status(supabase, "treasurer", "idle")
    except Exception as e:
        await log_task_failed(supabase, task_id, str(e))
        await update_agent_status(supabase, "treasurer", "error")


# ============================================
# The Full Daily Pipeline
# This runs every day at 6am UTC.
# Scout → Analyst → Recon → Designer + Copywriter → Publisher → Treasurer
# ============================================

async def run_daily_pipeline(supabase: Client):
    """
    The full APEX business loop.
    Runs every agent in sequence once per day.
    Each agent reads from and writes to Supabase
    so the next agent always has fresh data.
    """
    print(f"\n{'='*50}")
    print(f"[APEX] Daily pipeline starting at {datetime.now(timezone.utc)}")
    print(f"{'='*50}\n")
    
    # Research Room — runs in sequence
    await run_scout(supabase)
    await run_analyst(supabase)
    await run_recon(supabase)
    
    # Creation — Designer and Copywriter work in parallel in future
    # For now running in sequence for simplicity
    await run_designer(supabase)
    await run_copywriter(supabase)
    
    # Publishing — only runs if guardrails pass
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
    
    # Treasury — always runs last
    await run_treasurer(supabase)
    
    print(f"\n[APEX] Daily pipeline complete at {datetime.now(timezone.utc)}\n")


# ============================================
# Scheduler Setup
# Call this from main.py to start the scheduler
# when the FastAPI server boots up.
# ============================================

def create_scheduler(supabase: Client) -> AsyncIOScheduler:
    """
    Creates and configures the APScheduler instance.
    Returns it so main.py can start and stop it
    with the FastAPI app lifecycle.
    """
    scheduler = AsyncIOScheduler(timezone="UTC")
    
    # Full pipeline runs every day at 6am UTC
    scheduler.add_job(
        run_daily_pipeline,
        CronTrigger(hour=6, minute=0),
        args=[supabase],
        id="daily_pipeline",
        name="APEX Daily Business Loop",
        replace_existing=True
    )
    
    # Health pulse every 30 minutes
    # Keeps the Etsy API connection active
    # and confirms the system is alive
    scheduler.add_job(
        lambda: print(f"[APEX] System pulse at {datetime.now(timezone.utc)}"),
        "interval",
        minutes=30,
        id="system_pulse",
        name="System Health Pulse"
    )
    
    return scheduler
