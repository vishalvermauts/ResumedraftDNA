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
    },
    
    # Newly Added Greenhouse & Lever companies from Australia job listing
    {
        "companyName": "JCDecaux",
        "careersUrl": "https://boards.greenhouse.io/jcdecaux",
        "connector": {
            "type": "greenhouse",
            "boardToken": "jcdecaux",
            "priority": ["greenhouse", "jsonld", "ai_search"],
            "configuration": {}
        }
    },
    {
        "companyName": "Eucalyptus",
        "careersUrl": "https://boards.greenhouse.io/eucalyptus",
        "connector": {
            "type": "greenhouse",
            "boardToken": "eucalyptus",
            "priority": ["greenhouse", "jsonld", "ai_search"],
            "configuration": {}
        }
    },
    {
        "companyName": "Culture Amp",
        "careersUrl": "https://boards.greenhouse.io/cultureamp",
        "connector": {
            "type": "greenhouse",
            "boardToken": "cultureamp",
            "priority": ["greenhouse", "jsonld", "ai_search"],
            "configuration": {}
        }
    },
    {
        "companyName": "HubSpot",
        "careersUrl": "https://boards.greenhouse.io/hubspot",
        "connector": {
            "type": "greenhouse",
            "boardToken": "hubspot",
            "priority": ["greenhouse", "jsonld", "ai_search"],
            "configuration": {}
        }
    },
    {
        "companyName": "Asana",
        "careersUrl": "https://boards.greenhouse.io/asana",
        "connector": {
            "type": "greenhouse",
            "boardToken": "asana",
            "priority": ["greenhouse", "jsonld", "ai_search"],
            "configuration": {}
        }
    },
    {
        "companyName": "Navan",
        "careersUrl": "https://boards.greenhouse.io/navan",
        "connector": {
            "type": "greenhouse",
            "boardToken": "navan",
            "priority": ["greenhouse", "jsonld", "ai_search"],
            "configuration": {}
        }
    },
    {
        "companyName": "AirTrunk",
        "careersUrl": "https://boards.greenhouse.io/airtrunk",
        "connector": {
            "type": "greenhouse",
            "boardToken": "airtrunk",
            "priority": ["greenhouse", "jsonld", "ai_search"],
            "configuration": {}
        }
    },
    {
        "companyName": "Sonder.io",
        "careersUrl": "https://boards.greenhouse.io/sonder",
        "connector": {
            "type": "greenhouse",
            "boardToken": "sonder",
            "priority": ["greenhouse", "jsonld", "ai_search"],
            "configuration": {}
        }
    },
    {
        "companyName": "Bugcrowd",
        "careersUrl": "https://boards.greenhouse.io/bugcrowd",
        "connector": {
            "type": "greenhouse",
            "boardToken": "bugcrowd",
            "priority": ["greenhouse", "jsonld", "ai_search"],
            "configuration": {}
        }
    },
    {
        "companyName": "LogicMonitor",
        "careersUrl": "https://boards.greenhouse.io/logicmonitor",
        "connector": {
            "type": "greenhouse",
            "boardToken": "logicmonitor",
            "priority": ["greenhouse", "jsonld", "ai_search"],
            "configuration": {}
        }
    },
    {
        "companyName": "Postman",
        "careersUrl": "https://boards.greenhouse.io/postman",
        "connector": {
            "type": "greenhouse",
            "boardToken": "postman",
            "priority": ["greenhouse", "jsonld", "ai_search"],
            "configuration": {}
        }
    },
    {
        "companyName": "Recorded Future",
        "careersUrl": "https://boards.greenhouse.io/recordedfuture",
        "connector": {
            "type": "greenhouse",
            "boardToken": "recordedfuture",
            "priority": ["greenhouse", "jsonld", "ai_search"],
            "configuration": {}
        }
    },
    {
        "companyName": "Adyen",
        "careersUrl": "https://boards.greenhouse.io/adyen",
        "connector": {
            "type": "greenhouse",
            "boardToken": "adyen",
            "priority": ["greenhouse", "jsonld", "ai_search"],
            "configuration": {}
        }
    },
    {
        "companyName": "Buildkite",
        "careersUrl": "https://boards.greenhouse.io/buildkite",
        "connector": {
            "type": "greenhouse",
            "boardToken": "buildkite",
            "priority": ["greenhouse", "jsonld", "ai_search"],
            "configuration": {}
        }
    },
    {
        "companyName": "Workato",
        "careersUrl": "https://boards.greenhouse.io/workato",
        "connector": {
            "type": "greenhouse",
            "boardToken": "workato",
            "priority": ["greenhouse", "jsonld", "ai_search"],
            "configuration": {}
        }
    },
    {
        "companyName": "Klaviyo",
        "careersUrl": "https://boards.greenhouse.io/klaviyo",
        "connector": {
            "type": "greenhouse",
            "boardToken": "klaviyo",
            "priority": ["greenhouse", "jsonld", "ai_search"],
            "configuration": {}
        }
    },
    {
        "companyName": "Cribl",
        "careersUrl": "https://boards.greenhouse.io/cribl",
        "connector": {
            "type": "greenhouse",
            "boardToken": "cribl",
            "priority": ["greenhouse", "jsonld", "ai_search"],
            "configuration": {}
        }
    },
    {
        "companyName": "Netskope",
        "careersUrl": "https://boards.greenhouse.io/netskope",
        "connector": {
            "type": "greenhouse",
            "boardToken": "netskope",
            "priority": ["greenhouse", "jsonld", "ai_search"],
            "configuration": {}
        }
    },
    {
        "companyName": "FeverUp",
        "careersUrl": "https://boards.greenhouse.io/feverup",
        "connector": {
            "type": "greenhouse",
            "boardToken": "feverup",
            "priority": ["greenhouse", "jsonld", "ai_search"],
            "configuration": {}
        }
    },
    {
        "companyName": "Roller",
        "careersUrl": "https://boards.greenhouse.io/roller",
        "connector": {
            "type": "greenhouse",
            "boardToken": "roller",
            "priority": ["greenhouse", "jsonld", "ai_search"],
            "configuration": {}
        }
    },
    {
        "companyName": "New Relic",
        "careersUrl": "https://boards.greenhouse.io/newrelic",
        "connector": {
            "type": "greenhouse",
            "boardToken": "newrelic",
            "priority": ["greenhouse", "jsonld", "ai_search"],
            "configuration": {}
        }
    },
    {
        "companyName": "Remote",
        "careersUrl": "https://jobs.lever.co/remote",
        "connector": {
            "type": "lever",
            "boardToken": "remote",
            "priority": ["lever", "jsonld", "ai_search"],
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
