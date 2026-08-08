# -*- coding: utf-8 -*-
import json, os, sys, io
from collections import defaultdict
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ROOT = "."
EXAMS_DIR = os.path.join(ROOT, "data", "exams_updated")
QUESTIONS_JSON = os.path.join(ROOT, "study", "questions.json")

with open(QUESTIONS_JSON, encoding="utf-8-sig") as f:
    existing = json.load(f)

existing_combo = defaultdict(int)
for item in existing:
    y = item.get("year")
    if isinstance(y, str):
        try: y = int(y)
        except: pass
    existing_combo[(item.get("exam",""), item.get("subject",""), y)] += 1

ALLOWED_EXAMS = {"세무사", "법무사", "감정평가사", "노무사"}
YEAR_RANGE = (2015, 2026)

def parse_year(raw):
    if raw is None: return None
    try:
        y = int(str(raw).strip()[:4])
        return y if 1990 <= y <= 2030 else None
    except: return None

def get_exam_subj_year_from_file(fpath, fname):
    try:
        with open(fpath, encoding="utf-8-sig") as f:
            d = json.load(f)
    except: return []

    items = []
    if isinstance(d, list):
        items = d
    elif isinstance(d, dict) and "questions" in d:
        meta = d.get("meta", {})
        exam_raw = meta.get("exam_norm") or meta.get("exam","")
        year = parse_year(meta.get("year"))
        subjects = meta.get("subjects_norm") or meta.get("subjects") or []
        for q in d["questions"]:
            items.append({
                "_exam": exam_raw, "_year": year,
                "_subject": subjects[0] if subjects else "?",
                "q": q.get("stem",""), "no": q.get("no")
            })

    results = []
    for item in items:
        if "_exam" in item:
            exam, year, subj = item["_exam"], item["_year"], item["_subject"]
        else:
            exam = item.get("exam","")
            year = parse_year(item.get("year"))
            subj = item.get("subject","?")

        # 정규화
        EXAM_NORM = {"공인회계사":"회계사","공인노무사":"노무사","zip_semu":"세무사"}
        exam = EXAM_NORM.get(exam, exam)

        if exam not in ALLOWED_EXAMS: continue
        if not year or not (YEAR_RANGE[0] <= year <= YEAR_RANGE[1]): continue

        combo = (exam, subj, year)
        if existing_combo[combo] > 0: continue  # 이미 있는 조합
        results.append(combo)

    return results

print("=== 파일별 추가될 (exam, subject, year) 조합 ===")
total = 0
for fname in sorted(os.listdir(EXAMS_DIR)):
    if not fname.endswith(".json"): continue
    fpath = os.path.join(EXAMS_DIR, fname)
    combos = get_exam_subj_year_from_file(fpath, fname)
    if combos:
        from collections import Counter
        cnt = Counter(combos)
        print(f"\n[{fname[:70]}]")
        for combo, n in sorted(cnt.items()):
            print(f"  {combo[0]} / {combo[1]} / {combo[2]}: {n}문")
            total += n

print(f"\n=== 총 {total}문 추가 예정 ===")

print("\n\n=== 현재 세무사 갭 (exam, subject, year) 현황 ===")
semu_targets = [
    ("세무사","민법",2016),("세무사","상법",2015),("세무사","세법학개론",2017),
    ("세무사","재정학",2015),("세무사","재정학",2016),("세무사","행정소송법",2016),
]
for combo in semu_targets:
    cnt = existing_combo[combo]
    print(f"  {combo}: 기존 {cnt}문 {'(갭!)' if cnt == 0 else '(있음)'}")
