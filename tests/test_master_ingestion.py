from app.ai.master_ingestion import section_chunks


def test_section_chunks_are_stable_and_bounded():
    resume = {
        "projects": [{"id": str(i)} for i in range(9)],
        "certifications": [{"id": "c1"}],
    }
    chunks = section_chunks(resume, max_items=4)
    assert [chunk["chunkId"] for chunk in chunks] == [
        "projects:0001", "projects:0002", "projects:0003", "certifications:0001"
    ]
    assert [len(chunk["items"]) for chunk in chunks[:3]] == [4, 4, 1]
    assert section_chunks(resume, max_items=4) == chunks


def test_section_chunks_reject_invalid_bound():
    try:
        section_chunks({}, max_items=0)
    except ValueError as error:
        assert "positive" in str(error)
    else:
        raise AssertionError("expected invalid chunk bound to fail")
