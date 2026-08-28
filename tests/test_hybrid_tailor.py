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
