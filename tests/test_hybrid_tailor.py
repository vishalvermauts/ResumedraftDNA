from app.ai.hybrid_tailor import analyze_resume


def test_transport_bullet_matches_travel_logistics():
    resume = {
        "employmentHistory": [{
            "jobTitle": "Operations Coordinator",
            "bulletPoints": [
                "Coordinated transport for offshore personnel",
                "Maintained office records",
            ],
        }],
        "projects": [
            {"title": "Offshore transport", "description": "Coordinated transport for offshore personnel"},
            {"title": "Personal website", "description": "Built a personal website"},
        ]
    }
    tailored, report = analyze_resume(
        resume,
        "Executive Assistant responsible for travel logistics and stakeholder coordination",
    )

    assert tailored["projects"][0]["title"] == "Offshore transport"
    assert tailored["employmentHistory"][0]["bulletPoints"][0].startswith("Coordinated transport")
    assert report["mode"] == "hybrid-experimental"
    assert "travel" in report["items"][0]["matchedConcepts"]
    assert report["comparison"]["aiOnly"]["projects"] == ["projects.0", "projects.1"]
    assert report["comparison"]["hybrid"]["projects"] == ["projects.0", "projects.1"]


def test_certifications_and_volunteering_ranked_by_relevance():
    resume = {
        "certifications": [
            {"name": "Standard First Aid"},
            {"name": "Control of Work Awareness Level 1"},
        ],
        "leadershipVolunteering": [
            {"organization": "Community Book Club", "role": "Member", "bulletPoints": ["Discussed literature"]},
            {"organization": "Offshore Logistics Support", "role": "Lead", "bulletPoints": ["Coordinated emergency travel"]},
        ]
    }
    tailored, report = analyze_resume(
        resume,
        "Offshore Travel Coordinator requiring travel logistics, control of work awareness, and emergency coordination",
    )

    assert tailored["certifications"][0]["name"] == "Control of Work Awareness Level 1"
    assert tailored["leadershipVolunteering"][0]["organization"] == "Offshore Logistics Support"
    assert any(item["type"] == "certification" for item in report["items"])
    assert any(item["type"] == "leadership-volunteering" for item in report["items"])

