# ============================================
# APEX V3 — Main Application
# The House of Packard
# ============================================

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from dotenv import load_dotenv
from supabase import create_client, Client
from task_engine import create_scheduler, run_daily_pipeline
from observability import init_sentry, init_langsmith, get_observability_status
import os
import httpx
import secrets
from datetime import datetime, timezone

load_dotenv()

app = FastAPI(
    title="APEX V3",
    description="Autonomous Business Operating System — The House of Packard",
    version="3.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

supabase: Client = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_SERVICE_KEY")
)

scheduler = create_scheduler(supabase)
oauth_state_store = {}

@app.on_event("startup")
async def startup_event():
    init_sentry()
    init_langsmith()
    scheduler.start()
    print(f"[APEX] System online at {datetime.now(timezone.utc)}")
    print(f"[APEX] Scheduler started — daily pipeline runs at 06:00 UTC")

@app.on_event("shutdown")
async def shutdown_event():
    scheduler.shutdown()
    print(f"[APEX] System offline at {datetime.now(timezone.utc)}")

@app.get("/")
def root():
    return {
        "system": "APEX V3",
        "status": "online",
        "org": "The House of Packard",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

@app.get("/health")
def health_check():
    try:
        supabase.table("audit_log").insert({
            "agent": "system",
            "action": "health_check",
            "success": True,
            "details": {
                "message": "APEX V3 backend is online",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        }).execute()

        return {
            "status": "healthy",
            "database": "connected",
            "scheduler": "running" if scheduler.running else "stopped",
            "next_pipeline_run": str(scheduler.get_job("daily_pipeline").next_run_time),
            "observability": get_observability_status(),
            "etsy_oauth": "configured" if os.getenv("ETSY_ACCESS_TOKEN") else "not configured",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

    except Exception as e:
        return {
            "status": "unhealthy",
            "database": "error",
            "error": str(e),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

@app.get("/etsy/auth")
async def etsy_auth():
    import hashlib
    import base64

    api_key = os.getenv("ETSY_API_KEY")
    callback_url = f"{os.getenv('RAILWAY_URL', 'https://web-production-8056d.up.railway.app')}/etsy/callback"

    code_verifier = secrets.token_urlsafe(64)
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).rstrip(b'=').decode()

    state = secrets.token_urlsafe(32)
    oauth_state_store[state] = code_verifier

    scopes = " ".join([
        "listings_r",
        "listings_w",
        "listings_d",
        "shops_r",
        "shops_w",
        "transactions_r",
        "billing_r",
    ])

    auth_url = (
        f"https://www.etsy.com/oauth/connect"
        f"?response_type=code"
        f"&redirect_uri={callback_url}"
        f"&scope={scopes}"
        f"&client_id={api_key}"
        f"&state={state}"
        f"&code_challenge={code_challenge}"
        f"&code_challenge_method=S256"
    )

    return RedirectResponse(url=auth_url)


@app.get("/etsy/auth/debug")
async def etsy_auth_debug():
    import hashlib
    import base64

    api_key = os.getenv("ETSY_API_KEY")
    callback_url = f"{os.getenv('RAILWAY_URL', 'https://web-production-8056d.up.railway.app')}/etsy/callback"

    code_verifier = secrets.token_urlsafe(64)
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).rstrip(b'=').decode()

    state = secrets.token_urlsafe(32)

    scopes = " ".join([
        "listings_r",
        "listings_w",
        "listings_d",
        "shops_r",
        "shops_w",
        "transactions_r",
        "billing_r",
    ])

    auth_url = (
        f"https://www.etsy.com/oauth/connect"
        f"?response_type=code"
        f"&redirect_uri={callback_url}"
        f"&scope={scopes}"
        f"&client_id={api_key}"
        f"&state={state}"
        f"&code_challenge={code_challenge}"
        f"&code_challenge_method=S256"
    )

    return {
        "callback_url_being_sent": callback_url,
        "api_key_loaded": bool(api_key),
        "full_auth_url": auth_url,
        "instruction": "Make sure callback_url_being_sent exactly matches what is in your Etsy app settings"
    }


@app.get("/etsy/callback")
async def etsy_callback(code: str = None, state: str = None, error: str = None):
    if error:
        return {"error": f"Etsy authorization failed: {error}"}

    if not code or not state:
        return {"error": "Missing code or state parameter"}

    code_verifier = oauth_state_store.get(state)
    if not code_verifier:
        return {"error": "Invalid state — possible CSRF attack or session expired"}

    api_key = os.getenv("ETSY_API_KEY")
    callback_url = f"{os.getenv('RAILWAY_URL', 'https://web-production-8056d.up.railway.app')}/etsy/callback"

    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://api.etsy.com/v3/public/oauth/token",
            data={
                "grant_type": "authorization_code",
                "client_id": api_key,
                "redirect_uri": callback_url,
                "code": code,
                "code_verifier": code_verifier,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )

    if response.status_code != 200:
        return {
            "error": "Token exchange failed",
            "status_code": response.status_code,
            "details": response.text
        }

    token_data = response.json()
    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")
    expires_in = token_data.get("expires_in")

    oauth_state_store.pop(state, None)

    supabase.table("audit_log").insert({
        "agent": "system",
        "action": "etsy_oauth_complete",
        "success": True,
        "details": {
            "expires_in": expires_in,
            "has_refresh_token": bool(refresh_token),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    }).execute()

    return {
        "status": "SUCCESS — COPY THESE VALUES TO RAILWAY",
        "instructions": "Add ETSY_ACCESS_TOKEN and ETSY_REFRESH_TOKEN as Railway environment variables",
        "ETSY_ACCESS_TOKEN": access_token,
        "ETSY_REFRESH_TOKEN": refresh_token,
        "expires_in_seconds": expires_in,
        "expires_in_hours": round(expires_in / 3600, 1) if expires_in else None,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@app.get("/agents")
def get_agents():
    try:
        response = supabase.table("agents").select("*").execute()
        return {
            "agents": response.data,
            "count": len(response.data)
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/opportunities")
def get_opportunities():
    try:
        response = supabase.table("opportunities")\
            .select("*")\
            .order("final_score", desc=True)\
            .execute()
        return {
            "opportunities": response.data,
            "count": len(response.data)
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/tasks/recent")
def get_recent_tasks():
    try:
        response = supabase.table("tasks")\
            .select("*")\
            .order("created_at", desc=True)\
            .limit(50)\
            .execute()
        return {
            "tasks": response.data,
            "count": len(response.data)
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/treasury/summary")
def get_treasury_summary():
    try:
        response = supabase.table("financial_events")\
            .select("*")\
            .execute()

        events = response.data
        total_revenue = sum(e["amount"] for e in events if e["type"] == "revenue")
        total_costs = sum(e["amount"] for e in events if e["type"] == "cost")
        net_profit = total_revenue - total_costs

        return {
            "total_revenue": round(total_revenue, 2),
            "total_costs": round(total_costs, 2),
            "net_profit": round(net_profit, 2),
            "event_count": len(events)
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/scout/run")
async def run_scout_debug():
    try:
        from agents.scout import run_scout
        result = await run_scout(supabase)
        return {
            "status": "completed",
            "result": result,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        import traceback
        return {
            "status": "error",
            "error": str(e),
            "traceback": traceback.format_exc(),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }


@app.get("/analyst/run")
async def run_analyst_debug():
    try:
        from agents.analyst import run_analyst
        result = await run_analyst(supabase)
        return {
            "status": "completed",
            "result": result,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        import traceback
        return {
            "status": "error",
            "error": str(e),
            "traceback": traceback.format_exc(),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }


@app.get("/recon/run")
async def run_recon_debug():
    try:
        from agents.recon import run_recon
        result = await run_recon(supabase)
        return {
            "status": "completed",
            "result": result,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        import traceback
        return {
            "status": "error",
            "error": str(e),
            "traceback": traceback.format_exc(),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }


@app.get("/pipeline/run")
async def trigger_pipeline_get():
    try:
        await run_daily_pipeline(supabase)
        return {
            "status": "completed",
            "message": "Daily pipeline completed successfully",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        return {"error": str(e)}


@app.post("/pipeline/run")
async def trigger_pipeline():
    try:
        await run_daily_pipeline(supabase)
        return {
            "status": "completed",
            "message": "Daily pipeline completed successfully",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        return {"error": str(e)}
