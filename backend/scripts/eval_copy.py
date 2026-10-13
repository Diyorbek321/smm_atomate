"""Copy-quality eval: the same briefs through the writer and the editor.

The one honest way to judge a prompt or model change is to run it against the
work it will actually do — before and after, same briefs, same knowledge base.
Feelings about a single post do not survive twelve of them in a table.

Usage (from backend/):
    python -m scripts.eval_copy                     # all briefs
    python -m scripts.eval_copy --limit 3           # quick smoke run
    python -m scripts.eval_copy --json out.json     # save for later diffing
    python -m scripts.eval_copy --compare old.json  # per-brief delta vs a run

Needs an LLM key (real calls, real cost — roughly one plan's worth of copy),
but no database and no running services.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.agents.copywriter import CopyRequest, CopywriterAgent
from app.agents.editor import EditorAgent, EditorRequest
from app.models.business import Business
from app.models.enums import (
    BusinessCategory,
    ContentPillar,
    ContentType,
    Language,
    Plan,
    ToneOfVoice,
)
from app.models.knowledge_base import KnowledgeBase

BRIEFS_PATH = Path(__file__).with_name("eval_briefs.json")


def load_fixture() -> dict[str, Any]:
    return json.loads(BRIEFS_PATH.read_text())


def build_business(spec: dict[str, Any]) -> Business:
    business = Business(
        name=spec["name"],
        plan=Plan.PRO,
        category=BusinessCategory(spec["category"]),
        tone_of_voice=ToneOfVoice(spec["tone_of_voice"]),
        target_audience=spec.get("target_audience", ""),
        language=Language(spec.get("language", "uz")),
        timezone="Asia/Tashkent",
        settings={},
    )
    # Agents only read the id; no database row needs to exist behind it.
    business.id = uuid.uuid4()
    return business


def build_knowledge(spec: dict[str, Any]) -> KnowledgeBase:
    knowledge = KnowledgeBase(raw_notes="")
    for key, value in spec.items():
        setattr(knowledge, key, value)
    return knowledge


async def run_brief(
    business: Business, knowledge: KnowledgeBase, brief: dict[str, Any]
) -> dict[str, Any]:
    copywriter = CopywriterAgent()
    editor = EditorAgent()
    request = CopyRequest(
        business=business,
        knowledge=knowledge,
        content_type=ContentType(brief["content_type"]),
        pillar=ContentPillar(brief["pillar"]),
        topic=brief["topic"],
        angle=brief.get("angle", ""),
        goal=brief.get("goal", ""),
    )
    copy = await copywriter.run(request)
    review = await editor.run(
        EditorRequest(
            business=business,
            knowledge=knowledge,
            copy=copy,
            content_type=request.content_type,
            topic=request.topic,
        )
    )
    severities = [issue.severity for issue in review.report.issues]
    usage = copywriter.usage.as_dict()
    usage_editor = editor.usage.as_dict()
    return {
        "id": brief["id"],
        "pillar": brief["pillar"],
        "type": brief["content_type"],
        "score": review.score,
        "approved": review.approved,
        "critical": severities.count("critical"),
        "major": severities.count("major"),
        "minor": severities.count("minor"),
        "caption_tg": review.copy.caption_tg,
        "cost_usd": round(usage["cost_usd"] + usage_editor["cost_usd"], 5),
        "models": sorted(set(usage["models"] + usage_editor["models"])),
    }


async def run_all(limit: int | None) -> dict[str, Any]:
    fixture = load_fixture()
    business = build_business(fixture["business"])
    knowledge = build_knowledge(fixture["knowledge"])
    briefs = fixture["briefs"][:limit] if limit else fixture["briefs"]

    results: list[dict[str, Any]] = []
    for brief in briefs:  # sequential on purpose: quota-friendly, order-stable
        try:
            results.append(await run_brief(business, knowledge, brief))
        except Exception as exc:  # a failed brief is itself a finding
            results.append(
                {"id": brief["id"], "pillar": brief["pillar"], "type": brief["content_type"],
                 "score": 0.0, "approved": False, "error": str(exc)[:200]}
            )
        print(_row(results[-1]))

    scores = [r["score"] for r in results if "error" not in r]
    summary = {
        "ran_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "briefs": len(results),
        "failed": sum(1 for r in results if "error" in r),
        "approved": sum(1 for r in results if r.get("approved")),
        "avg_score": round(statistics.mean(scores), 2) if scores else 0.0,
        "min_score": min(scores) if scores else 0.0,
        "total_cost_usd": round(sum(r.get("cost_usd", 0.0) for r in results), 4),
    }
    return {"summary": summary, "results": results}


def _row(r: dict[str, Any]) -> str:
    if "error" in r:
        return f"  {r['id']:<22} XATO: {r['error'][:80]}"
    flag = "OK " if r["approved"] else "REJ"
    return (
        f"  {r['id']:<22} {flag} score={r['score']:<5} "
        f"crit={r['critical']} maj={r['major']} min={r['minor']} ${r['cost_usd']}"
    )


def _print_summary(summary: dict[str, Any]) -> None:
    print(
        f"\nJAMI: {summary['briefs']} brief | o'rtacha ball {summary['avg_score']} | "
        f"eng past {summary['min_score']} | tasdiqlangan {summary['approved']} | "
        f"xato {summary['failed']} | narx ${summary['total_cost_usd']}"
    )


def _compare(current: dict[str, Any], baseline_path: Path) -> None:
    baseline = json.loads(baseline_path.read_text())
    old = {r["id"]: r for r in baseline.get("results", [])}
    print(f"\nTAQQOSLASH ({baseline_path.name} bilan):")
    for r in current["results"]:
        prev = old.get(r["id"])
        if prev is None:
            continue
        delta = round(r.get("score", 0) - prev.get("score", 0), 2)
        mark = "+" if delta > 0 else ""
        print(f"  {r['id']:<22} {prev.get('score', 0):<5} -> {r.get('score', 0):<5} ({mark}{delta})")
    old_avg = baseline.get("summary", {}).get("avg_score", 0)
    new_avg = current["summary"]["avg_score"]
    print(f"  {'O`RTACHA':<22} {old_avg:<5} -> {new_avg:<5} ({round(new_avg - old_avg, 2):+})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--limit", type=int, default=None, help="run only the first N briefs")
    parser.add_argument("--json", type=Path, default=None, help="write full results to this file")
    parser.add_argument("--compare", type=Path, default=None, help="earlier --json output to diff against")
    args = parser.parse_args()

    print("Kopirayter + muharrir eval boshlanadi...\n")
    outcome = asyncio.run(run_all(args.limit))
    _print_summary(outcome["summary"])
    if args.compare:
        _compare(outcome, args.compare)
    if args.json:
        args.json.write_text(json.dumps(outcome, ensure_ascii=False, indent=2))
        print(f"\nNatija saqlandi: {args.json}")


if __name__ == "__main__":
    main()
