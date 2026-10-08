"""Seed script for AlphaHedge paper stock trading platform."""
from google.cloud import firestore

PROJECT_ID = "qwiklabs-gcp-03-99d8dc84aabc"

def seed_portfolio():
    db = firestore.Client(project=PROJECT_ID)
    
    # 1. Seed holdings
    holdings = [
        {
            "ticker": "GOOGL",
            "name": "Alphabet Inc.",
            "shares": 50,
            "avg_price": 178.50,
            "current_price": 182.20,
            "sector": "Technology",
            "notes": "Core AI & cloud play",
        },
        {
            "ticker": "NVDA",
            "name": "NVIDIA Corporation",
            "shares": 25,
            "avg_price": 120.00,
            "current_price": 134.50,
            "sector": "Semiconductors",
            "notes": "High beta AI compute leader",
        },
        {
            "ticker": "AAPL",
            "name": "Apple Inc.",
            "shares": 40,
            "avg_price": 225.00,
            "current_price": 231.00,
            "sector": "Consumer Electronics",
            "notes": "Defensive cash cow with edge AI",
        },
        {
            "ticker": "AMZN",
            "name": "Amazon.com Inc.",
            "shares": 30,
            "avg_price": 185.00,
            "current_price": 190.50,
            "sector": "E-commerce & Cloud",
            "notes": "AWS cloud growth rebound",
        },
    ]

    print(f"Seeding holdings into project: {PROJECT_ID}...")
    for item in holdings:
        doc_ref = db.collection("portfolio_holdings").document(item["ticker"])
        doc_ref.set(item)
        print(f"  ✓ Seeded holding {item['ticker']}")

    # 2. Seed portfolio summary / cash balance
    account_summary = {
        "cash_balance": 50000.00,
        "initial_capital": 100000.00,
        "currency": "USD",
        "benchmark": "SPY",
        "risk_profile": "Growth / Alpha Seeking",
    }
    db.collection("portfolio_meta").document("account").set(account_summary)
    print("  ✓ Seeded portfolio metadata (cash_balance: $50,000)")

    print("Seeding completed successfully!")

if __name__ == "__main__":
    seed_portfolio()
