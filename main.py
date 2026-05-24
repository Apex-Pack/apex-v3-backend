# ============================================
# APEX V3 — Main Application
# The House of Packard
# ============================================

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from supabase import create_client, Client
from task_engine import create_scheduler, run_daily_pipeline
from observability import init_sentry, init_langsmith, get_observability_status
import os
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
