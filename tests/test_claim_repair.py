def test_claim_repair_uses_the_same_threshold_as_final_validation():
    from app.ai.validation import attach_claim_evidence, repair_unsupported_claims, validate_source_backed_sections

    source = {
        "leadershipVolunteering": [{
            "role": "President",
            "organization": "UTS Red Cross Society",
            "sourceEvidenceIds": ["source:leadership:1"],
            "bulletPoints": ["Coordinated community lunches and donations for asylum seeker families."],
        }]
    }
    generated = {
        "leadershipVolunteering": [{
            "role": "President",
            "organization": "UTS Red-Cross Society",
            "sourceEvidenceIds": ["source:leadership:1"],
            # One generic overlap is insufficient and must be restored.
            "bulletPoints": ["Led strategic community programs for vulnerable groups."],
        }]
    }

    repaired = attach_claim_evidence(repair_unsupported_claims(generated, source))
    assert repaired["leadershipVolunteering"][0]["bulletPoints"] == source["leadershipVolunteering"][0]["bulletPoints"]
    validate_source_backed_sections(repaired, source)


def test_shared_source_id_preserves_evidence_for_each_record():
    from app.ai.validation import attach_claim_evidence, validate_source_backed_sections

    source = {
        "leadershipVolunteering": [
            {"organization": "Hiking", "sourceEvidenceIds": ["p0206"], "bulletPoints": ["Organised hiking events in national parks."]},
            {"organization": "Red Cross", "sourceEvidenceIds": ["p0206"], "bulletPoints": ["Coordinated community lunches and donations."]},
        ]
    }
    generated = attach_claim_evidence({
        "leadershipVolunteering": [
            {"organization": "Hiking", "sourceEvidenceIds": ["p0206"], "bulletPoints": ["Organised hiking events in national parks."]},
        ]
    })
    validate_source_backed_sections(generated, source)
