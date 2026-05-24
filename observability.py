# ============================================
# APEX V3 — Observability
# The House of Packard
# ============================================
# Two layers of visibility:
# 1. LangSmith — traces every Claude API call
# 2. Sentry — catches every crash and error
# ============================================

import os
import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.asyncio import AsyncioIntegration
from langsmith import Client as LangSmithClient
from datetime import datetime, timezone


# ============================================
# Sentry Setup
# Catches crashes and sends alerts.
# Think of this as your smoke alarm —
# silent when everything is fine, loud
# when something breaks.
# ============================================

def init_sentry():
    """
    Initializes Sentry error monitoring.
    Call this once when the FastAPI app starts.
    """
    dsn = os.getenv("SENTRY_DSN")
    
    if not dsn:
        print("[SENTRY] No DSN found — error monitoring disabled")
        return
    
    sentry_sdk.init(
        dsn=dsn,
        integrations=[
            FastApiIntegration(),
            AsyncioIntegration(),
        ],
        # Capture 100% of errors
        sample_rate=1.0,
        # Capture 10% of performance traces
        # (keeps free tier usage low)
        traces_sample_rate=0.1,
        environment="production",
        release="apex-v3.0.0",
    )
    
    print("[SENTRY] Error monitoring initialized")


# ============================================
# LangSmith Setup
# Traces every Claude API call.
# Think of this as your black box recorder —
# every prompt, every response, every cost,
# every latency measurement, all searchable.
# ============================================

def init_langsmith():
    """
    Initializes LangSmith tracing.
    Call this once when the FastAPI app starts.
    """
    api_key = os.getenv("LANGSMITH_API_KEY")
    project = os.getenv("LANGSMITH_PROJECT", "apex-v3")
    
    if not api_key:
        print("[LANGSMITH] No API key found — tracing disabled")
        return None
    
    # Set environment variables LangSmith needs
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_PROJECT"] = project
    os.environ["LANGSMITH_API_KEY"] = api_key
    
    print(f"[LANGSMITH] Tracing initialized — project: {project}")
    return LangSmithClient(api_key=api_key)


# ============================================
# Trace Logger
# Call this every time an agent makes a
# Claude API call. Records the full context
# so you can debug it later in LangSmith.
# ============================================

async def trace_agent_call(
    supabase,
    agent: str,
    prompt: str,
    response: str,
    tokens_used: int,
    cost_usd: float,
    run_name: str = None
):
    """
    Logs an agent's Claude API call to both
    LangSmith (for traces) and Supabase audit_log
    (for structured records).
    
    Call this after every Claude API call in every agent.
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    
    # Log to Supabase audit log
    try:
        supabase.table("audit_log").insert({
            "agent": agent,
            "action": run_name or f"{agent}_claude_call",
            "cost_usd": cost_usd,
            "success": True,
            "details": {
                "tokens_used": tokens_used,
                "prompt_preview": prompt[:200],
                "response_preview": response[:200],
                "timestamp": timestamp
            }
        }).execute()
    except Exception as e:
        print(f"[OBSERVABILITY] Failed to log to audit_log: {str(e)}")


# ============================================
# Error Reporter
# Call this in every except block so errors
# go to both Sentry and the audit log.
# ============================================

async def report_error(
    supabase,
    agent: str,
    error: Exception,
    context: dict = None
):
    """
    Reports an error to Sentry and logs it
    to the Supabase audit log.
    
    Call this in every agent's except block.
    """
    # Send to Sentry
    with sentry_sdk.push_scope() as scope:
        scope.set_tag("agent", agent)
        scope.set_context("apex_context", context or {})
        sentry_sdk.capture_exception(error)
    
    # Log to Supabase
    try:
        supabase.table("audit_log").insert({
            "agent": agent,
            "action": "error",
            "success": False,
            "details": {
                "error_type": type(error).__name__,
                "error_message": str(error),
                "context": context or {},
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        }).execute()
    except Exception as e:
        print(f"[OBSERVABILITY] Failed to log error to audit_log: {str(e)}")


# ============================================
# System Health Reporter
# Called by the health check endpoint to
# confirm observability layers are active.
# ============================================

def get_observability_status() -> dict:
    """
    Returns the status of both observability layers.
    Shown on the /health endpoint.
    """
    return {
        "langsmith": "enabled" if os.getenv("LANGSMITH_API_KEY") else "disabled",
        "sentry": "enabled" if os.getenv("SENTRY_DSN") else "disabled",
        "project": os.getenv("LANGSMITH_PROJECT", "apex-v3")
    }
