# ============================================
# APEX V3 — Token Manager
# The House of Packard
# ============================================
# Handles OAuth token storage and auto-refresh.
# Tokens are stored in Supabase so they persist
# across Railway restarts and auto-refresh
# without any manual intervention.
# ============================================

import os
import httpx
from datetime import datetime, timezone, timedelta

ETSY_API_KEY = os.getenv("ETSY_API_KEY")
ETSY_SHARED_SECRET = os.getenv("ETSY_SHARED_SECRET")


async def get_valid_etsy_token(supabase) -> str:
    """
    Returns a valid Etsy access token.
    If the current token is expired or about to expire,
    automatically refreshes it and saves the new one.
    
    Think of this like a valet who always makes sure
    your car is fueled up before you need it.
    """
    try:
        # Get current token from Supabase
        response = supabase.table("tokens")\
            .select("*")\
            .eq("service", "etsy")\
            .single()\
            .execute()
        
        token_record = response.data
        
        if not token_record:
            print("[TOKEN] No Etsy token found in database")
            return None
        
        # Check if token expires within the next 5 minutes
        expires_at = datetime.fromisoformat(
            token_record["expires_at"].replace("Z", "+00:00")
        )
        now = datetime.now(timezone.utc)
        time_until_expiry = (expires_at - now).total_seconds()
        
        if time_until_expiry > 300:
            # Token is still valid — return it
            print(f"[TOKEN] Etsy token valid for {int(time_until_expiry/60)} more minutes")
            return token_record["access_token"]
        
        # Token is expired or expiring soon — refresh it
        print(f"[TOKEN] Etsy token expiring in {int(time_until_expiry)} seconds — refreshing")
        return await refresh_etsy_token(supabase, token_record["refresh_token"])
    
    except Exception as e:
        print(f"[TOKEN] Error getting token: {str(e)}")
        return None


async def refresh_etsy_token(supabase, refresh_token: str) -> str:
    """
    Uses the refresh token to get a new access token from Etsy.
    Saves the new tokens back to Supabase automatically.
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.etsy.com/v3/public/oauth/token",
                data={
                    "grant_type": "refresh_token",
                    "client_id": os.getenv("ETSY_API_KEY"),
                    "refresh_token": refresh_token,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            )
        
        if response.status_code != 200:
            print(f"[TOKEN] Refresh failed: {response.status_code} — {response.text}")
            return None
        
        token_data = response.json()
        new_access_token = token_data.get("access_token")
        new_refresh_token = token_data.get("refresh_token", refresh_token)
        expires_in = token_data.get("expires_in", 3600)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        
        # Save new tokens to Supabase
        supabase.table("tokens").update({
            "access_token": new_access_token,
            "refresh_token": new_refresh_token,
            "expires_at": expires_at.isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat()
        }).eq("service", "etsy").execute()
        
        print(f"[TOKEN] Etsy token refreshed successfully — valid for {expires_in/3600:.1f} hours")
        return new_access_token
    
    except Exception as e:
        print(f"[TOKEN] Refresh error: {str(e)}")
        return None


async def get_etsy_headers(supabase) -> dict:
    """
    Returns the complete headers needed for Etsy API calls.
    Always uses a valid, non-expired token.
    Call this instead of building headers manually.
    """
    access_token = await get_valid_etsy_token(supabase)
    
    if not access_token:
        raise Exception("Could not get valid Etsy access token")
    
    return {
        "x-api-key": f"{os.getenv('ETSY_API_KEY')}:{os.getenv('ETSY_SHARED_SECRET')}",
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
