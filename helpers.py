# ============================================
# APEX V3 — Shared Helper Functions
# The House of Packard
# ============================================
# These functions are used by both the task
# engine AND the agents. Keeping them here
# prevents circular imports.
# ============================================

from datetime import datetime, timezone


async def log_task_start(supabase, agent: str, room: str, task_type: str, input_data: dict) -> str:
    """Creates a task record when an agent starts working."""
    response = supabase.table("tasks").insert({
        "agent": agent,
        "room": room,
        "type": task_type,
        "status": "running",
        "input": input_data,
        "created_at": datetime.now(timezone.utc).isoformat()
    }).execute()
    return response.data[0]["id"]


async def log_task_complete(supabase, task_id: str, output_data: dict, cost_tokens: int = 0, cost_usd: float = 0):
    """Updates a task record when an agent finishes successfully."""
    supabase.table("tasks").update({
        "status": "succeeded",
        "output": output_data,
        "cost_tokens": cost_tokens,
        "cost_usd": cost_usd,
        "completed_at": datetime.now(timezone.utc).isoformat()
    }).eq("id", task_id).execute()


async def log_task_failed(supabase, task_id: str, error: str, retries: int = 0):
    """Updates a task record when an agent fails."""
    supabase.table("tasks").update({
        "status": "failed",
        "error": error,
        "retries": retries,
        "completed_at": datetime.now(timezone.utc).isoformat()
    }).eq("id", task_id).execute()


async def update_agent_status(supabase, agent_name: str, status: str):
    """Updates an agent's status in the agents table."""
    supabase.table("agents").update({
        "status": status,
        "last_active": datetime.now(timezone.utc).isoformat()
    }).eq("name", agent_name).execute()
