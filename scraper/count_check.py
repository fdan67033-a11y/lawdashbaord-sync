# -*- coding: utf-8 -*-
"""olta 수집 현황 + 직전 체크 대비 증감/속도 출력."""
import io
import json
import sys
import time
import sqlite3
from datetime import datetime
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "olta_qa.db"
SNAP = ROOT / "data" / ".olta_count_snapshot.json"
TOTALS = {"qa": 51500, "consult": 18068}
LABEL = {"qa": "질의응답", "consult": "지방세상담"}

con = sqlite3.connect(DB)
con.execute("PRAGMA busy_timeout=8000")
cur = {b: con.execute("SELECT COUNT(*) FROM olta_qa WHERE board=? AND detail_fetched=1", (b,)).fetchone()[0]
       for b in ("qa", "consult")}
con.close()

prev = {}
try:
    prev = json.loads(SNAP.read_text(encoding="utf-8"))
except Exception:
    pass
now = time.time()
elapsed = None
if prev.get("ts"):
    elapsed = now - prev["ts"]

print(f"[{datetime.now().strftime('%H:%M:%S')}] olta 수집 현황")
for b in ("qa", "consult"):
    tot = TOTALS[b]
    cnt = cur[b]
    line = f"  {LABEL[b]}: {cnt:,} / {tot:,}  (남은 {tot-cnt:,})"
    if b in prev:
        d = cnt - prev[b]
        line += f"  ▲+{d:,}" if d >= 0 else f"  ▼{d:,}"
        if elapsed and elapsed > 0 and d > 0:
            line += f"  · {d/elapsed*60:.0f}/분 ({elapsed/60:.1f}분 경과)"
    print(line)

SNAP.write_text(json.dumps({"ts": now, "qa": cur["qa"], "consult": cur["consult"]}, ensure_ascii=False), encoding="utf-8")
