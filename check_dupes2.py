# -*- coding: utf-8 -*-
import json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

with open("study/questions.json", encoding="utf-8-sig") as f:
    qs = json.load(f)

# 노무사 경영학개론 2018: 50개인 이유 확인
print("=== 노무사 경영학개론 2018 (전체 50개) ===")
items = [q for q in qs if q.get("exam")=="노무사" and q.get("subject")=="경영학개론" and q.get("year")==2018]
print(f"총 {len(items)}개")
for i, q in enumerate(items):
    print(f"  [{i+1}] id={q['id']} q={str(q.get('q',''))[:60]}")

# 중복 검사: 실제 q 텍스트 기반
print("\n=== q 텍스트 중복 (같은 exam+subj+year에서) ===")
from collections import defaultdict
key2 = defaultdict(list)
for q in qs:
    k = (q.get("exam",""), q.get("subject",""), q.get("year"), (q.get("q","") or "").strip())
    key2[k].append(q['id'])

exact_dupes = {k: v for k, v in key2.items() if len(v) > 1}
print(f"완전 동일 q 텍스트 중복: {len(exact_dupes)}건")
for (exam, subj, year, q_text), ids in list(exact_dupes.items())[:10]:
    print(f"  {exam} {subj} {year} | q={q_text[:40]}... ids={ids}")

# 노무사 연도별 문제수 이상 체크 (25문제 시험이어야 하는 연도)
print("\n=== 노무사 연도별 문제수 (2015-2022 각 과목 25문 예상) ===")
from collections import Counter
nomy = [q for q in qs if q.get("exam")=="노무사"]
for subj in sorted(set(q.get("subject") for q in nomy)):
    ycount = Counter()
    for q in nomy:
        if q.get("subject") == subj:
            ycount[q.get("year")] += 1
    over = {y: n for y, n in ycount.items() if isinstance(y, int) and 2015 <= y <= 2022 and n > 40}
    if over:
        print(f"  {subj}: 이상 연도={over}")
