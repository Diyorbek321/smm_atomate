"""Qayta rejalashtirish: muddati o'tgan pending_review elementlarni
biznesning o'z jadvali (posting_hours / posts_per_week) bo'yicha
ertangi kundan boshlab kelajakka bir tekis taqsimlaydi.

Band slotlar (kelajakdagi mavjud elementlar) chetlab o'tiladi.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone

TZ = timezone(timedelta(hours=5))  # Asia/Tashkent
APPLY = "--apply" in sys.argv


def psql(sql: str) -> list[list[str]]:
    out = subprocess.run(
        ["docker", "exec", "autosmm-postgres-1", "psql", "-U", "autosmm", "-d", "autosmm",
         "-t", "-A", "-F", "\t", "-c", sql],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return [line.split("\t") for line in out.splitlines() if line]


def slots(start_day, hours: list[int], per_week: int, taken: set[datetime]):
    """Kunlar bo'ylab bir tekis: base + qoldiq birinchi kunlarga."""
    base, extra = divmod(per_week, 7)
    day, week_index = start_day, 0
    while True:
        quota = base + (1 if week_index < extra else 0)
        for hour in hours[:quota]:
            moment = datetime.combine(day, datetime.min.time(), TZ).replace(hour=hour)
            if moment not in taken:
                yield moment
        day += timedelta(days=1)
        week_index = (week_index + 1) % 7


businesses = psql(
    "select id, name, settings::text from businesses where is_active order by name;"
)
tomorrow = datetime.now(TZ).date() + timedelta(days=1)
total, plan_rows = 0, []

for business_id, name, raw_settings in businesses:
    cfg = json.loads(raw_settings)
    hours = sorted(cfg.get("posting_hours") or [10])
    per_week = int(cfg.get("posts_per_week") or 5)

    stale = psql(
        f"select id, scheduled_at, topic from content_items "
        f"where business_id='{business_id}' and status='pending_review' "
        f"and scheduled_at < now() order by scheduled_at;"
    )
    taken = {
        datetime.fromisoformat(row[0]).astimezone(TZ)
        for row in psql(
            f"select scheduled_at from content_items "
            f"where business_id='{business_id}' and scheduled_at >= now() "
            f"and status not in ('rejected','published');"
        )
    }
    if not stale:
        continue

    feed = slots(tomorrow, hours, per_week, taken)
    print(f"\n=== {name} — {len(stale)} ta ko'chiriladi "
          f"(soatlar {hours}, haftada {per_week}) ===")
    for item_id, old, topic in stale:
        new = next(feed)
        taken.add(new)
        plan_rows.append((item_id, new))
        print(f"  {old[:10]} -> {new:%Y-%m-%d %H:%M}  {topic[:44]}")
    total += len(stale)

print(f"\nJAMI: {total} ta element")

if not APPLY:
    print("(quruq yurish — o'zgartirish kiritilmadi; qo'llash uchun --apply)")
    raise SystemExit

cases = " ".join(f"when '{i}' then timestamptz '{m.isoformat()}'" for i, m in plan_rows)
ids = ",".join(f"'{i}'" for i, _ in plan_rows)
psql(
    f"update content_items set scheduled_at = case id::text {cases} end, "
    f"sent_for_review = false, review_message_id = null, review_chat_id = null, "
    f"updated_at = now() where id in ({ids});"
)
print(f"QO'LLANDI: {total} ta element ko'chirildi va qayta ko'rib chiqishga qo'yildi")
