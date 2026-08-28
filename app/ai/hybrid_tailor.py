"""Deterministic relevance analysis used by the experimental hybrid tailor."""

import re


ALIASES = {
    "travel": {"transport", "transportation", "logistics", "mobilization", "movement"},
    "coordination": {"coordinated", "organised", "organized", "scheduling", "liaison"},
    "stakeholder": {"client", "customer", "vendor", "supplier", "partner"},
    "reporting": {"reports", "reporting", "excel", "spreadsheet", "analysis"},
    "events": {"event", "events", "conference", "function"},
    "administration": {"administrative", "administrator", "office", "calendar", "diary"},
}
STOPWORDS = {
    "a", "an", "and", "for", "from", "in", "of", "on", "or", "the", "to", "with",
}


def _tokens(value):
    return {
        token for token in re.findall(r"[a-z0-9]+", str(value or "").lower())
        if token not in STOPWORDS
    }


def _concepts(tokens):
    found = set(tokens)
    for concept, aliases in ALIASES.items():
        if concept in tokens or tokens.intersection(aliases):
            found.add(concept)
    return found


def _text(value):
    if isinstance(value, dict):
        return " ".join(_text(v) for v in value.values())
    if isinstance(value, list):
        return " ".join(_text(v) for v in value)
    return str(value or "")


def _score(item_text, jd_tokens):
    item_tokens = _concepts(_tokens(item_text))
    if not item_tokens or not jd_tokens:
        return 0.0, []
    matched = sorted(item_tokens.intersection(jd_tokens))
    exact = len(_tokens(item_text).intersection(jd_tokens))
    score = min(1.0, (exact * 0.12) + (len(matched) * 0.16))
    return round(score, 3), matched


def analyze_resume(resume, job_description):
    """Rank source evidence without deleting or rewriting master-resume data."""
    jd_tokens = _concepts(_tokens(job_description))
    report = {
        "mode": "hybrid-experimental",
        "jobConcepts": sorted(jd_tokens),
        "items": [],
        "comparison": {"aiOnly": {}, "hybrid": {}},
    }
    result = dict(resume or {})

    def ranked(values, item_type, path_prefix):
        scored = []
        for index, value in enumerate(values or []):
            score, matched = _score(_text(value), jd_tokens)
            scored.append((score, index, value))
            report["items"].append({
                "type": item_type,
                "index": index,
                "path": f"{path_prefix}.{index}",
                "score": score,
                "matchedConcepts": matched,
            })
        original_paths = [f"{path_prefix}.{index}" for index in range(len(scored))]
        ranked_paths = [
            f"{path_prefix}.{index}" for _, index, _ in sorted(scored, key=lambda row: (-row[0], row[1]))
        ]
        section = "projects" if item_type == "project" else "experienceBullets"
        report["comparison"]["aiOnly"].setdefault(section, []).extend(original_paths)
        report["comparison"]["hybrid"].setdefault(section, []).extend(ranked_paths)
        return [value for _, _, value in sorted(scored, key=lambda row: (-row[0], row[1]))]

    projects = result.get("projects") if isinstance(result, dict) else None
    if isinstance(projects, list):
        result["projects"] = ranked(projects, "project", "projects")

    # Keep each job and every bullet, but surface the most relevant evidence first.
    employment = result.get("employmentHistory") if isinstance(result, dict) else None
    if isinstance(employment, list):
        ranked_employment = []
        for index, entry in enumerate(employment):
            copied = dict(entry) if isinstance(entry, dict) else entry
            bullets = copied.get("bulletPoints") if isinstance(copied, dict) else None
            if isinstance(bullets, list):
                copied["bulletPoints"] = ranked(bullets, "experience-bullet", f"employmentHistory.{index}.bulletPoints")
            score, matched = _score(_text(entry), jd_tokens)
            report["items"].append({
                "type": "experience",
                "index": index,
                "path": f"employmentHistory.{index}",
                "score": score,
                "matchedConcepts": matched,
            })
            ranked_employment.append((score, index, copied))
        result["employmentHistory"] = [value for _, _, value in sorted(
            ranked_employment, key=lambda row: (-row[0], row[1])
        )]

    return result, report


def build_hybrid_prompt(job_description, resume, report):
    return (
        "HYBRID MODE: the deterministic engine selected and ranked source content first.\n"
        "Rewrite only verified facts from the supplied master resume. Do not add claims.\n"
        f"JOB DESCRIPTION:\n{job_description}\n\n"
        f"RANKING REPORT:\n{report}\n\n"
        f"MASTER RESUME:\n{resume}"
    )
