import requests
import logging
from datetime import datetime
from dotenv import load_dotenv
from supabase import create_client, Client
import os

log = logging.getLogger(__name__)

load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))
supabase: Client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))


def fetch_all_active_products() -> list:
    """Fetch all active USD spot pairs from Coinbase."""
    url     = "https://api.coinbase.com/api/v3/brokerage/market/products"
    params  = {"product_type": "SPOT", "limit": 500}
    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        if resp.status_code != 200:
            print(f"❌ Coinbase error: {resp.status_code}")
            return []

        products = [
            p["product_id"]
            for p in resp.json().get("products", [])
            if p.get("status") == "online"
            and p.get("quote_currency_id") == "USD"
        ]
        print(f"✅ Fetched {len(products)} active USD pairs")
        return products

    except Exception as e:
        print(f"❌ fetch_all_active_products failed: {e}")
        return []


def fetch_product_details(product_id: str) -> dict:
    """
    Fetch full product details from Coinbase including:
    - current price
    - 24hr change %
    - 24hr high / low
    - 24hr volume
    - range from 24hr low (intraday move detector)
    
    This replaces two separate API calls (ticker + product) with richer data.
    Used by main.py to detect intraday pumps even when 24hr % looks small.
    """
    url = f"https://api.coinbase.com/api/v3/brokerage/market/products/{product_id}"
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
        if resp.status_code != 200:
            return {}

        data = resp.json()

        price      = float(data.get("price", 0) or 0)
        volume_24h = float(data.get("volume_24h", 0) or 0)
        change_24hr = float(
            data.get("price_percentage_change_24h") or
            data.get("price_percent_chg_24h") or 0
        )

        return {
            "price":       price,
            "change_24hr": round(change_24hr, 2),
            "volume_24h":  volume_24h,
        }

    except Exception as e:
        print(f"fetch_product_details failed for {product_id}: {e}")
        return {}


def store_price(product_id: str, price: float, volume: float = 0) -> bool:
    """Store price snapshot to Supabase."""
    try:
        supabase.table("prices").insert({
            "product_id": product_id,
            "price":      price,
            "volume":     volume or 0,
        }).execute()
        return True
    except Exception as e:
        print(f"store_price failed for {product_id}: {str(e)[:100]}")
        return False


def store_momentum_history(product_id: str, change_24hr: float, price: float, volume: float = 0) -> bool:
    """Store momentum snapshot for acceleration detection."""
    try:
        supabase.table("momentum_history").insert({
            "product_id":  product_id,
            "change_24hr": change_24hr,
            "price":       price,
            "volume":      volume or 0,
        }).execute()
        return True
    except Exception as e:
        print(f"store_momentum_history failed for {product_id}: {str(e)[:100]}")
        return False


# Quick test
if __name__ == "__main__":
    products = fetch_all_active_products()
    print("Sample:", products[:10])

    print("\nTesting product details fetch...")
    details = fetch_product_details("BTC-USD")
    print(f"BTC-USD: ${details.get('price'):,.2f} | "
          f"24hr: {details.get('change_24hr'):+.2f}% | "
          f"From low: +{details.get('range_from_low'):.2f}% | "
          f"Full range: {details.get('full_range'):.2f}%")

    store_price("BTC-USD", details.get("price", 0), details.get("volume_24h", 0))
    print("✅ Test complete")