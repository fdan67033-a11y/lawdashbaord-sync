# -*- coding: utf-8 -*-
"""완전 중복(exam+subject+year+q 텍스트 완전 동일) 제거. 낮은 id 유지."""
import json, sys, shutil, io
from datetime import datetime
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

QUESTIONS_PATH = "study/questions.json"

with open(QUESTIONS_PATH, encoding="utf-8-sig") as f:
    qs = json.load(f)

print(f"입력: {len(qs)}문제")

seen = {}  # key -> first occurrence index
keep_ids = set()
remove_ids = []

for q in qs:
    k = (
        q.get("exam", ""),
        q.get("subject", ""),
        q.get("year"),
        (q.get("q", "") or "").strip()
    )
    qid = q["id"]
    if k not in seen:
        seen[k] = qid
        keep_ids.add(qid)
    else:
        remove_ids.append((qid, seen[k]))

print(f"중복 제거 대상: {len(remove_ids)}개")
if remove_ids:
    for rid, orig_id in remove_ids[:10]:
        print(f"  id={rid} (원본 id={orig_id})")
    if len(remove_ids) > 10:
        print(f"  ... 외 {len(remove_ids)-10}개")

deduped = [q for q in qs if q["id"] in keep_ids]
print(f"결과: {len(deduped)}문제")

bak = QUESTIONS_PATH + f".bak.dedup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
shutil.copy2(QUESTIONS_PATH, bak)
print(f"백업: {bak}")

with open(QUESTIONS_PATH, "w", encoding="utf-8") as f:
    json.dump(deduped, f, ensure_ascii=False, separators=(",", ":"))

import os
size_kb = os.path.getsize(QUESTIONS_PATH) / 1024
print(f"저장: questions.json ({size_kb:.0f} KB, {len(deduped)}문제)")
