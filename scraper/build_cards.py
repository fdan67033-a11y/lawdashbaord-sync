# -*- coding: utf-8 -*-
"""추출 텍스트(data/exams_text/*.txt) -> 문제 단위 JSON 카드.
각 파일: 파일명에서 메타(시험/연도/회차/차수/과목/형) 추출 + 본문에서 문제 분할.
문제 분할: 【문N】 우선, 없으면 'N.'/'문N' 패턴. 선택지 ①~⑤ 추출. 정답/해설 있으면 포함.
출력: data/exams_cards/<staged>.json (meta + questions[]) + _cards_index.json(통계)
멱등. 사용: py -3.12 scraper\\build_cards.py
"""
import os, re, sys, json, glob
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "data", "exams_text")
OUT = os.path.join(ROOT, "data", "exams_cards")
os.makedirs(OUT, exist_ok=True)

EXAM = {"cpa": "회계사", "semu": "세무사", "bupmu": "법무사", "web_bupmu": "법무사"}
SUBJECTS = ["세법학개론", "세법학", "세무회계", "세법", "상법", "민사소송법", "민사집행법", "민법",
            "형사소송법", "형법", "부동산등기법", "상업등기법", "비송사건절차법", "공탁법",
            "가족관계", "헌법", "행정소송법", "회계학개론", "회계학", "재정학", "경영학",
            "경제원론", "영어", "원가", "재무회계", "회계감사"]
CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩"

def meta_from_name(staged):
    parts = staged.split("__")
    src = parts[0]
    rest = " ".join(parts[1:])
    m = {"source": src, "exam": EXAM.get(src, src), "file": staged}
    ym = re.search(r"((?:19|20)\d{2})\s*년", rest) or re.search(r"\b(20\d{2})\b", rest)
    m["year"] = ym.group(1) if ym else ""
    hm = re.search(r"제?\s*(\d+)\s*회", rest)
    m["round"] = hm.group(1) if hm else ""
    cm = re.search(r"([12])\s*차", rest)
    m["phase"] = cm.group(1) if cm else ""
    fm = re.search(r"([A-Ba-b])\s*형", rest)
    m["form"] = fm.group(1).upper() if fm else ""
    subs = [s for s in SUBJECTS if s in rest]
    # 더 구체적인 것 우선(긴 키워드가 앞)
    m["subjects"] = subs[:3]
    return m

def split_questions(text):
    """질문 블록 리스트 반환. (번호, 본문) """
    # 1) 【문 N】
    marks = list(re.finditer(r"【\s*문\s*(\d+)\s*】", text))
    if len(marks) >= 3:
        return _slice(text, marks)
    # 2) 문 N. / 문N)
    marks = list(re.finditer(r"(?:^|\n|\s)문\s*(\d+)\s*[.)]", text))
    if len(marks) >= 3:
        return _slice(text, marks)
    # 3) 인라인/줄머리 'N.'/'N)' — 뒤에 선택지 ①가 따르고 번호가 순차(과목별 리셋 허용)
    return _seq_split(text)


def _seq_split(text):
    cands = list(re.finditer(r"(\d{1,3})\s*[.)]", text))
    chosen, expected = [], 1
    for m in cands:
        no = int(m.group(1))
        if no > 200 or "①" not in text[m.end():m.end() + 900]:
            continue
        if no == expected or no == expected + 1:      # 순차(한 문제 건너뜀 허용)
            chosen.append(m); expected = no + 1
        elif no == 1 and len(chosen) >= 5:            # 새 과목/교시 리셋
            chosen.append(m); expected = 2
    if len(chosen) >= 5:
        return _slice(text, chosen)
    return []

def _slice(text, marks):
    out = []
    for i, mm in enumerate(marks):
        no = mm.group(1)
        s = mm.end()
        e = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        body = text[s:e].strip()
        if body:
            out.append((no, body))
    return out

def parse_choices(body):
    """본문에서 지문/선택지/정답/해설 분리."""
    # 정답
    ans = ""
    am = re.search(r"정답\s*[:：]?\s*([①-⑩]|\d)", body)
    if am:
        ans = am.group(1)
    # 해설
    exp = ""
    em = re.search(r"해설\s*[:：]", body)
    if em:
        exp = body[em.end():].strip()[:1500]
        body_q = body[:em.start()]
    else:
        body_q = body
    # 선택지: ①~⑤ 위치로 분할
    cmarks = list(re.finditer(r"[①-⑩]", body_q))
    choices = []
    stem = body_q
    if len(cmarks) >= 2:
        stem = body_q[:cmarks[0].start()].strip()
        for i, cm in enumerate(cmarks):
            cs = cm.end()
            ce = cmarks[i + 1].start() if i + 1 < len(cmarks) else len(body_q)
            ch = body_q[cs:ce].strip()
            # 정답표기 앞부분 제거
            ch = re.split(r"정답\s*[:：]", ch)[0].strip()
            if ch:
                choices.append({"no": CIRCLED.index(cm.group(0)) + 1, "text": ch[:500]})
    return re.sub(r"\s+", " ", stem)[:1200], choices, ans, re.sub(r"\s+", " ", exp)

def main():
    files = sorted(glob.glob(os.path.join(SRC, "*.txt")))
    index = {"files": 0, "questions": 0, "with_answer": 0, "with_explanation": 0, "empty_files": [], "drm_txt": []}
    per = []
    for f in files:
        staged = os.path.basename(f)[:-4]
        raw = open(f, "rb").read()
        if raw[:8].find(b"DRMONE") != -1 or raw[:1] == b"\x9b":
            index["drm_txt"].append(staged)
            continue
        text = raw.decode("utf-8", errors="replace")
        meta = meta_from_name(staged)
        blocks = split_questions(text)
        qs = []
        for no, body in blocks:
            stem, choices, ans, exp = parse_choices(body)
            if not stem and not choices:
                continue
            q = {"no": no, "stem": stem, "choices": choices}
            if ans: q["answer"] = ans
            if exp: q["explanation"] = exp
            qs.append(q)
        rec = {"meta": meta, "n_questions": len(qs), "questions": qs}
        json.dump(rec, open(os.path.join(OUT, staged + ".json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        index["files"] += 1
        index["questions"] += len(qs)
        index["with_answer"] += sum(1 for q in qs if q.get("answer"))
        index["with_explanation"] += sum(1 for q in qs if q.get("explanation"))
        if len(qs) == 0:
            index["empty_files"].append(staged)
        per.append((staged, len(qs)))
    json.dump(index, open(os.path.join(OUT, "_cards_index.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"[완료] 파일 {index['files']} | 문제 {index['questions']} | 정답있음 {index['with_answer']} | 해설있음 {index['with_explanation']}")
    print(f"  파싱0 파일: {len(index['empty_files'])}개 | DRM걸린txt(건너뜀): {len(index['drm_txt'])}개")
    # 상위/하위 표본
    per.sort(key=lambda x: -x[1])
    print("  최다 추출:", [(s[:30], n) for s, n in per[:3]])
    print("  0개 예시:", [s[:40] for s in index['empty_files'][:5]])

if __name__ == "__main__":
    main()
