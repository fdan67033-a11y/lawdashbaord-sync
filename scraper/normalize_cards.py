# -*- coding: utf-8 -*-
"""카드 메타 정규화: 시험명 통일 + zip 재분류 + 과목 표준화 + 중복(가답안↔확정정답) 표시.
각 카드 json의 meta에 추가: exam_norm, subjects_norm, variant, dedup_key, is_duplicate.
산출: data/exams_cards/_normalized_index.json (시험/과목/연도별 '중복제외' 문제수)
멱등. 사용: py -3.12 scraper\\normalize_cards.py
"""
import os, sys, glob, json, re
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CARDS = os.path.join(ROOT, "data", "exams_cards")
ZIPMAP = json.load(open(os.path.join(ROOT, "data", "_zip_src_map.json"), encoding="utf-8"))
ZIPMAP_NORM = {re.sub(r"[^가-힣0-9a-z]", "", k.lower().rsplit(".", 1)[0]): v for k, v in ZIPMAP.items()}

EXAM = {"cpa": "회계사", "semu": "세무사", "bupmu": "법무사", "web_bupmu": "법무사",
        "zip_semu": "세무사", "zip_bupmu": "법무사", "zip_cpa": "회계사"}
# 과목 표준화(긴 키 먼저)
SUBJ_CANON = [
    ("세법학개론", "세법"), ("세법개론", "세법"), ("세법학", "세법"), ("세무회계", "세법"), ("세법", "세법"),
    ("기업법", "상법"), ("상법", "상법"),
    ("회계학개론", "회계학"), ("재무회계", "회계학"), ("원가", "회계학"), ("회계감사", "회계감사"), ("회계학", "회계학"),
    ("민사소송법", "민사소송법"), ("민사집행법", "민사집행법"), ("민법", "민법"),
    ("형사소송법", "형사소송법"), ("형법", "형법"),
    ("부동산등기법", "부동산등기법"), ("상업등기법", "상업등기법"), ("비송사건절차법", "비송사건절차법"),
    ("공탁법", "공탁법"), ("가족관계", "가족관계등록법"), ("헌법", "헌법"),
    ("행정소송법", "행정소송법"), ("재정학", "재정학"), ("경영학", "경영학"),
    ("경제원론", "경제원론"), ("영어", "영어"),
]

def resolve_exam(staged, meta):
    src = staged.split("__")[0]
    if src in EXAM:
        return EXAM[src]
    if src == "zip_zip" or src == "zip":
        base = staged.split("__", 1)[1] if "__" in staged else staged
        key = re.sub(r"[^가-힣0-9a-z]", "", base.lower())
        # 1) zip 원본 매핑 부분일치
        for k, v in ZIPMAP_NORM.items():
            if k and (k in key or key in k):
                return EXAM.get(v, v)
        # 2) 키워드 폴백
        if re.search(r"기업법|세법개론|경제원론|회계감사|원가", base):
            return "회계사"
        if re.search(r"세법학|재정학|회계학개론|행정소송", base):
            return "세무사"
        return "회계사"  # 2024/2025 zip 배치는 회계사
    return EXAM.get(src, meta.get("exam", src))

def canon_subjects(meta, staged):
    text = " ".join(meta.get("subjects", [])) + " " + staged
    out = []
    for kw, canon in SUBJ_CANON:
        if kw in text and canon not in out:
            out.append(canon)
    return out

def variant(staged):
    if re.search(r"확정정답|확정답안|최종정답|최종답", staged):
        return "확정정답"
    if "가답안" in staged or "정답가안" in staged:
        return "가답안"
    if "해설" in staged:
        return "해설"
    return "문제"

VAR_RANK = {"해설": 3, "확정정답": 2, "문제": 1, "가답안": 0}

def main():
    files = [f for f in glob.glob(os.path.join(CARDS, "*.json"))
             if not os.path.basename(f).startswith("_")]
    cards = []
    for f in files:
        d = json.load(open(f, encoding="utf-8"))
        staged = os.path.basename(f)[:-5]
        m = d["meta"]
        m["exam_norm"] = resolve_exam(staged, m)
        m["subjects_norm"] = canon_subjects(m, staged)
        m["variant"] = variant(staged)
        key = "|".join([m["exam_norm"], m.get("year", ""), m.get("round", ""),
                        m.get("phase", ""), m.get("form", ""),
                        ",".join(sorted(m["subjects_norm"]))])
        m["dedup_key"] = key
        cards.append((f, d, staged))
    # 중복 처리: 같은 dedup_key 그룹에서 대표 1개만 is_duplicate=False
    from collections import defaultdict
    groups = defaultdict(list)
    for f, d, staged in cards:
        groups[d["meta"]["dedup_key"]].append((f, d, staged))
    dup = 0
    for key, grp in groups.items():
        # 대표: variant 우선순위 높은 것 -> 문제수 많은 것
        grp.sort(key=lambda x: (VAR_RANK.get(x[1]["meta"]["variant"], 0), x[1]["n_questions"]), reverse=True)
        for i, (f, d, staged) in enumerate(grp):
            d["meta"]["is_duplicate"] = (i != 0) and (len(grp) > 1) and (key.strip("|") != "")
            json.dump(d, open(f, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            if d["meta"]["is_duplicate"]:
                dup += 1
    # 통계(중복제외)
    from collections import Counter
    by_exam = Counter(); by_subj = Counter(); by_year = Counter()
    uniq_q = 0; raw_q = 0
    for f, d, staged in cards:
        raw_q += d["n_questions"]
        if d["meta"].get("is_duplicate"):
            continue
        uniq_q += d["n_questions"]
        by_exam[d["meta"]["exam_norm"]] += d["n_questions"]
        for s in (d["meta"]["subjects_norm"] or ["(미분류)"]):
            by_subj[s] += d["n_questions"]
        by_year[d["meta"].get("year", "?")] += d["n_questions"]
    idx = {"files": len(cards), "raw_questions": raw_q, "unique_questions": uniq_q,
           "duplicate_files": dup, "by_exam": dict(by_exam.most_common()),
           "by_subject": dict(by_subj.most_common()), "by_year": dict(sorted(by_year.items()))}
    json.dump(idx, open(os.path.join(CARDS, "_normalized_index.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"[정규화] 파일 {len(cards)} | 원문제 {raw_q} -> 중복제외 {uniq_q} | 중복파일 {dup}")
    print("시험별(중복제외):", dict(by_exam.most_common()))
    print("과목별 top10:", dict(by_subj.most_common(10)))

if __name__ == "__main__":
    main()
