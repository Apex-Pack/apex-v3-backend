# ============================================
# APEX V3 — Main Application
# The House of Packard
# ============================================

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from supabase import create_client, Client
from task_engine import create_scheduler, run_daily_pipeline
import os
from datetime import datetime, timezone

# Load environment variables
load_dotenv()

# ============================================
# Initialize FastAPI app
# ============================================
app = FastAPI(
    title="APEX V3",
    description="Autonomous Business Operating System — The House of Packard",
    version="3.0.0"
)

# ============================================
# CORS Middleware
# Allows the dashboard on Vercel to talk to
# this backend on Railway
# ============================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================
# Connect to Supabase
# ============================================
supabase: Client = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_SERVICE_KEY")
)

# ============================================
# Scheduler — starts with the app, stops with the app
# ============================================
scheduler = create_scheduler(supabase)

@app.on_event("startup")
async def startup_event():
    """Runs when the FastAPI server boots up on Railway."""
    scheduler.start()
    print(f"[APEX] System online at {datetime.now(timezone.utc)}")
    print(f"[APEX] Scheduler started — daily pipeline runs at 06:00 UTC")

@app.on_event("shutdown")
async def shutdown_event():
    """Runs when the server shuts down."""
    scheduler.shutdown()
    print(f"[APEX] System offline at {datetime.now(timezone.utc)}")

# ============================================
# Routes
# ============================================

@app.get("/")
def root():
    """Root endpoint — confirms the server is alive."""
    return {
        "system": "APEX V3",
        "status": "online",
        "org": "The House of Packard",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@app.get("/health")
def health_check():
    """
    Health check endpoint.
    Railway pings this to confirm the server is running.
    Writes a heartbeat to the audit log.
    """
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
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

    except Exception as e:
        return {
            "status": "unhealthy",
            "database": "error",
            "error": str(e),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }


@app.get("/agents")
def get_agents():
    """Returns the status of all 7 agents."""
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
    """Returns all opportunities ordered by score."""
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
    """Returns the 50 most recent agent tasks."""
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
    """Returns a financial summary for the dashboard."""
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


@app.post("/pipeline/run")
async def trigger_pipeline():
    """
    Manually triggers the full daily pipeline.
    Use this from the dashboard to run the system
    on demand instead of waiting for 6am UTC.
    """
    try:
        await run_daily_pipeline(supabase)
        return {
            "status": "completed",
            "message": "Daily pipeline completed successfully",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        return {"error": str(e)}
