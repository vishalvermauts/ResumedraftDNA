import asyncio
import os
from datetime import datetime
from app.db.mongo import db

# Seeding data
SEED_COMPANIES = [
    # SmartRecruiters
    {
        "companyName": "Sodexo",
        "careersUrl": "https://jobs.smartrecruiters.com/Sodexo",
        "connector": {
            "type": "smartrecruiters",
            "boardToken": "Sodexo",
            "priority": ["smartrecruiters", "jsonld", "ai_search"],
            "configuration": {}
        }
    },
    {
        "companyName": "Visa",
        "careersUrl": "https://jobs.smartrecruiters.com/Visa",
        "connector": {
            "type": "smartrecruiters",
            "boardToken": "Visa",
            "priority": ["smartrecruiters", "jsonld", "ai_search"],
            "configuration": {}
        }
    },
    {
        "companyName": "IKEA",
        "careersUrl": "https://jobs.smartrecruiters.com/IKEA",
        "connector": {
            "type": "smartrecruiters",
            "boardToken": "IKEA",
            "priority": ["smartrecruiters", "jsonld", "ai_search"],
            "configuration": {}
        }
    },
    {
        "companyName": "Bosch",
        "careersUrl": "https://jobs.smartrecruiters.com/BoschGroup",
        "connector": {
            "type": "smartrecruiters",
            "boardToken": "BoschGroup",
            "priority": ["smartrecruiters", "jsonld", "ai_search"],
            "configuration": {}
        }
    },
    
    # Greenhouse
    {
        "companyName": "Stripe",
        "careersUrl": "https://boards.greenhouse.io/stripe",
        "connector": {
            "type": "greenhouse",
            "boardToken": "stripe",
            "priority": ["greenhouse", "jsonld", "ai_search"],
            "configuration": {}
        }
    },
    {
        "companyName": "Airbnb",
        "careersUrl": "https://boards.greenhouse.io/airbnb",
        "connector": {
            "type": "greenhouse",
            "boardToken": "airbnb",
            "priority": ["greenhouse", "jsonld", "ai_search"],
            "configuration": {}
        }
    },
    {
        "companyName": "Figma",
        "careersUrl": "https://boards.greenhouse.io/figma",
        "connector": {
            "type": "greenhouse",
            "boardToken": "figma",
            "priority": ["greenhouse", "jsonld", "ai_search"],
            "configuration": {}
        }
    },
    {
        "companyName": "Reddit",
        "careersUrl": "https://boards.greenhouse.io/reddit",
        "connector": {
            "type": "greenhouse",
            "boardToken": "reddit",
            "priority": ["greenhouse", "jsonld", "ai_search"],
            "configuration": {}
        }
    },
    {
        "companyName": "Robinhood",
        "careersUrl": "https://boards.greenhouse.io/robinhood",
        "connector": {
            "type": "greenhouse",
            "boardToken": "robinhood",
            "priority": ["greenhouse", "jsonld", "ai_search"],
            "configuration": {}
        }
    },
    {
        "companyName": "Zoom",
        "careersUrl": "https://boards.greenhouse.io/zoom",
        "connector": {
            "type": "greenhouse",
            "boardToken": "zoom",
            "priority": ["greenhouse", "jsonld", "ai_search"],
            "configuration": {}
        }
    },
    
    # Lever
    {
        "companyName": "Netflix",
        "careersUrl": "https://jobs.lever.co/netflix",
        "connector": {
            "type": "lever",
            "boardToken": "netflix",
            "priority": ["lever", "jsonld", "ai_search"],
            "configuration": {}
        }
    },
    {
        "companyName": "Spotify",
        "careersUrl": "https://jobs.lever.co/spotify",
        "connector": {
            "type": "lever",
            "boardToken": "spotify",
            "priority": ["lever", "jsonld", "ai_search"],
            "configuration": {}
        }
    },
    
    # Ashby
    {
        "companyName": "Linear",
        "careersUrl": "https://jobs.ashbyhq.com/linear",
        "connector": {
            "type": "ashby",
            "boardToken": "linear",
            "priority": ["ashby", "jsonld", "ai_search"],
            "configuration": {}
        }
    },
    {
        "companyName": "Vercel",
        "careersUrl": "https://jobs.ashbyhq.com/vercel",
        "connector": {
            "type": "ashby",
            "boardToken": "vercel",
            "priority": ["ashby", "jsonld", "ai_search"],
            "configuration": {}
        }
    },
    {
        "companyName": "Retool",
        "careersUrl": "https://jobs.ashbyhq.com/retool",
        "connector": {
            "type": "ashby",
            "boardToken": "retool",
            "priority": ["ashby", "jsonld", "ai_search"],
            "configuration": {}
        }
    }
]

async def seed():
    # Set MONGODB_URI to point to localhost for local testing if running locally,
    # but the environment MONGODB_URI will override it on deployment.
    await db.connect()
    
    print(f"Starting seeding of {len(SEED_COMPANIES)} global companies...")
    
    inserted_count = 0
    skipped_count = 0
    
    for item in SEED_COMPANIES:
        # Check if already exists in company_watchlists (matching by name or token)
        token = item["connector"]["boardToken"]
        existing = await db.db.company_watchlists.find_one({
            "$or": [
                {"companyName": item["companyName"]},
                {"connector.boardToken": token}
            ]
        })
        
        if existing:
            skipped_count += 1
            print(f"Skipped: {item['companyName']} (already exists)")
        else:
            doc = {
                "companyName": item["companyName"],
                "careersUrl": item["careersUrl"],
                "connector": item["connector"],
                "pollingFrequencyMinutes": 720,
                "enabled": True,
                "uid": "system",
                "createdAt": datetime.utcnow(),
                "nextRunAt": datetime.utcnow()
            }
            await db.db.company_watchlists.insert_one(doc)
            inserted_count += 1
            print(f"Seeded: {item['companyName']}")
            
    print(f"Seeding complete. Seeded {inserted_count} new entries, skipped {skipped_count} existing entries.")
    await db.close()

if __name__ == "__main__":
    asyncio.run(seed())
