# ============================================
# APEX V3 — Main Application
# The House of Packard
# ============================================

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from supabase import create_client, Client
import os
from datetime import datetime, timezone

# Load environment variables from .env file
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
    Also writes a heartbeat to the audit log so we know
    the database connection is working.
    """
    try:
        # Write a heartbeat to the audit log
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
    """
    Returns the status of all 7 agents.
    The dashboard reads this to show which agents
    are online, idle, or running.
    """
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
    """
    Returns all opportunities ordered by score.
    The dashboard reads this to show the opportunity pipeline.
    """
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
    """
    Returns the 50 most recent agent tasks.
    The dashboard reads this for the live activity feed.
    """
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
    """
    Returns a financial summary.
    Treasurer writes to financial_events.
    This endpoint aggregates it for the dashboard.
    """
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
