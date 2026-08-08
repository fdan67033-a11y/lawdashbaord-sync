# -*- coding: utf-8 -*-
"""노무사 2015-2022 과목별 연도에서 40개 초과 케이스 조사."""
import json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

with open("study/questions.json", encoding="utf-8-sig") as f:
    qs = json.load(f)

from collections import defaultdict
nomy = [q for q in qs if q.get("exam") == "노무사"]

for subj in sorted(set(q.get("subject") for q in nomy)):
    ydata = defaultdict(list)
    for q in nomy:
        if q.get("subject") == subj:
            y = q.get("year")
            if isinstance(y, str):
                try: y = int(y)
                except: y = None
            ydata[y].append(q)
    for y in range(2015, 2023):
        items = ydata.get(y, [])
        if len(items) > 40:
            print(f"\n{subj} {y}: {len(items)}개 (40 초과!)")
            ids = sorted(q['id'] for q in items)
            print(f"  id 범위: {ids[0]}-{ids[-1]}, 중간 갭: {ids[24] if len(ids)>24 else '?'} / {ids[25] if len(ids)>25 else '?'}")
            print(f"  앞 25개 q 샘플: {items[0].get('q','')[:50]}")
            print(f"  뒤 25개 q 샘플: {items[25].get('q','')[:50] if len(items)>25 else '없음'}")
        elif len(items) > 25:
            print(f"\n{subj} {y}: {len(items)}개 (25 초과)")
