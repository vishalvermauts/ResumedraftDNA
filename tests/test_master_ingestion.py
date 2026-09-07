from app.ai.master_ingestion import section_chunks, source_section_chunks
from app.schemas.master_ingestion import MasterChunkExtraction, MasterSourceIngestRequest


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


def test_source_section_chunks_preserve_provenance_and_boundaries():
    chunks = source_section_chunks(
        "VISHAL VERMA\nEXPERIENCE\nRig Administrator\nEDUCATION\nMaster of IT\nCERTIFICATIONS\nFirst Aid",
        max_lines=2,
    )
    assert [chunk["section"] for chunk in chunks] == [
        "header", "employmentHistory", "education", "certifications"
    ]
    assert chunks[1]["lines"][0]["sourceId"] == "p0002"
    assert chunks[-1]["text"] == "First Aid"


def test_source_ingestion_contract_is_bounded_and_structured():
    request = MasterSourceIngestRequest(
        sourceFileName="master.docx",
        sourceFormat="docx",
        sourceFileHash="sha256:abc",
        rawText="EXPERIENCE\nRig Administrator",
    )
    assert len(request.rawText) < 250_000
    extracted = MasterChunkExtraction(items=[{"jobTitle": "Rig Administrator"}])
    assert extracted.items[0]["jobTitle"] == "Rig Administrator"
