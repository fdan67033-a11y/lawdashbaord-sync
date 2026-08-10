#!/usr/bin/env python3
"""
merge_updated.py
================
data/exams_updated/ 안의 기출문제 파일들을 분석하여
아직 study/questions.json에 병합되지 않은 것들을 변환·병합한다.

사용법:
    python merge_updated.py           # 실제 병합
    python merge_updated.py --dry-run # 실제 저장 안 함
"""

import json
import os
import sys
import io
import shutil
import re
from pathlib import Path
from collections import defaultdict
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# ─────────────────────────────────────────────
# 경로 설정
# ─────────────────────────────────────────────
ROOT = Path(__file__).parent
EXAMS_DIR = ROOT / "data" / "exams_updated"
QUESTIONS_JSON = ROOT / "study" / "questions.json"

# ─────────────────────────────────────────────
# 상수 / 정규화 맵
# ─────────────────────────────────────────────
EXAM_NORM = {
    "공인회계사": "회계사",
    "공인노무사": "노무사",
    "zip_semu": "세무사",
    "zip_zip": None,   # 파일 내 exam_norm 사용
}

# 회계사는 이미 2015-2025 완전 → 건너뜀
ALLOWED_EXAMS = {"세무사", "법무사", "감정평가사", "노무사"}

# 회차 계산 기준 연도 (시험명 → 첫 회차 연도)
ROUND_BASE = {
    "세무사": 1963,    # 1회=1963 → round = year - 1963 + 1, 단순히 year-1963으로 하지 않고
    "법무사": 1963,
    "감정평가사": 1974,
    "회계사": 1961,
    "노무사": 1991,
}
# 실제 계산: round = year - base_year + 1 인데 주어진 규칙이 달라서 직접 명시
# 주어진 규칙: 세무사=year-1984, 법무사=year-1994, 감정평가사=year-1987, 회계사=year-1982, 노무사=year-1992
ROUND_FORMULA = {
    "세무사": lambda y: y - 1963,    # 1회=1964 기준이면 y-1963
    "법무사": lambda y: y - 1994,
    "감정평가사": lambda y: y - 1987,
    "회계사": lambda y: y - 1982,
    "노무사": lambda y: y - 1992,
}
# 실제 파일에서 확인한 값으로 보정
# 2016 세무사 53회 → 2016-1963=53 ✓
# 2019 법무사 25회 → 2019-1994=25 ✓
# 그대로 사용

YEAR_RANGE = (2015, 2026)


# ─────────────────────────────────────────────
# 유틸
# ─────────────────────────────────────────────
def normalize_exam(raw: str) -> str | None:
    """시험명 정규화. None이면 건너뜀."""
    if raw in EXAM_NORM:
        return EXAM_NORM[raw]
    if raw in ALLOWED_EXAMS:
        return raw
    # 긴 이름 매핑
    for k, v in EXAM_NORM.items():
        if k in raw:
            return v
    return raw  # 그대로 반환 후 허용 목록 체크에서 걸러짐


def parse_year(raw) -> int | None:
    if raw is None:
        return None
    try:
        y = int(str(raw).strip()[:4])
        return y if 1990 <= y <= 2030 else None
    except (ValueError, TypeError):
        return None


def parse_round(raw, exam: str, year: int) -> int | None:
    """회차 파싱. 실패 시 공식으로 계산."""
    if raw is not None and raw != "" and raw != 0:
        try:
            r = int(str(raw).strip())
            if r > 0:
                return r
        except (ValueError, TypeError):
            pass
    # 공식으로 계산
    formula = ROUND_FORMULA.get(exam)
    if formula and year:
        try:
            r = formula(year)
            return r if r > 0 else None
        except Exception:
            pass
    return None


def detect_subject_from_filename(filename: str, exam: str, subjects_norm: list) -> str | None:
    """파일명 + subjects_norm에서 과목 결정 (단일 과목인 경우)."""
    fn = filename.lower()

    # 파일명에서 명시적 과목 탐지
    if "헌법" in fn:
        return "헌법"
    if "민사소송법" in fn or "민소법" in fn:
        return "민사소송법"
    if "형법" in fn:
        return "형법"
    if "형사소송법" in fn or "형소법" in fn:
        return "형사소송법"
    if "부동산등기법" in fn or "부동산등기" in fn:
        return "부동산등기법"
    if "공탁법" in fn:
        return "공탁법"
    if "상업등기법" in fn or "상등법" in fn:
        return "상업등기법"
    if "민법" in fn:
        return "민법"
    if "상법" in fn:
        return "상법"
    if "행정소송법" in fn or "행소법" in fn:
        return "행정소송법"
    if "재정학" in fn:
        return "재정학"
    if "세법학개론" in fn or "세법개론" in fn:
        return "세법학개론"
    if "회계학" in fn and "원가" not in fn:
        return "회계학"
    if "원가" in fn:
        return "원가관리회계"
    if "감평이론" in fn or "감정평가론" in fn or "감평론" in fn:
        return "감정평가론"
    if "감평실무" in fn or "감정평가실무" in fn:
        return "감정평가실무"
    if "회계" in fn and "2부" in fn:
        return "회계학2부"
    if "세법" in fn and "2부" in fn:
        return "세법학2부"

    # subjects_norm이 단일이면 그것 사용
    if subjects_norm and len(subjects_norm) == 1:
        return subjects_norm[0]

    return None


def get_subject_by_no(no_int: int, exam: str, filename: str, meta: dict) -> str:
    """
    세무사 1교시 / 2교시 패턴으로 과목 결정.
    1~40: 재정학 / 세법학개론(1교시), 회계학개론(2교시)
    41~80: 세법학개론(1교시), 선택과목(2교시)
    """
    fn_lower = filename.lower()
    subjects_norm = meta.get("subjects_norm", []) or []

    if exam == "세무사":
        # 1교시 파일 판단
        is_1kosi = "1교시" in filename or "1교시" in str(meta.get("file", ""))
        # 2교시 파일 판단
        is_2kosi = "2교시" in filename or "2교시" in str(meta.get("file", ""))

        if is_1kosi:
            if no_int <= 40:
                return "재정학"
            else:
                return "세법학개론"

        if is_2kosi:
            # 선택과목 판단
            if "민법" in fn_lower or "민법" in str(meta.get("file", "")):
                elective = "민법"
            elif "행정소송법" in fn_lower or "행소법" in fn_lower or \
                 "행정소송법" in str(meta.get("file", "")) or "행소법" in str(meta.get("file", "")):
                elective = "행정소송법"
            elif "상법" in fn_lower or "상법" in str(meta.get("file", "")):
                elective = "상법"
            else:
                elective = subjects_norm[-1] if subjects_norm else "선택과목"

            if no_int <= 40:
                return "회계학개론"
            else:
                return elective

    # 기본값: subjects_norm 첫 번째
    if subjects_norm:
        return subjects_norm[0]
    return "기타"


def choices_to_list(choices) -> list:
    """choices 배열을 텍스트 리스트로 변환."""
    if not choices:
        return []
    if isinstance(choices, list):
        if choices and isinstance(choices[0], dict):
            return [item.get("text", "") for item in choices]
        # 이미 문자열 리스트
        return [str(c) for c in choices]
    return []


# ─────────────────────────────────────────────
# 형식 A 파싱
# ─────────────────────────────────────────────
def process_format_a(data: dict, filename: str) -> list[dict]:
    """형식 A (meta + questions) → compact 레코드 리스트."""
    meta = data.get("meta", {})
    questions = data.get("questions", [])

    # exam 정규화
    raw_exam = meta.get("exam_norm") or meta.get("exam", "")
    exam = normalize_exam(raw_exam)
    if not exam or exam not in ALLOWED_EXAMS:
        return []

    # year 파싱
    year = parse_year(meta.get("year"))
    if not year or not (YEAR_RANGE[0] <= year <= YEAR_RANGE[1]):
        return []

    # round 파싱
    round_val = parse_round(meta.get("round"), exam, year)

    subjects_norm = meta.get("subjects_norm") or meta.get("subjects") or []

    records = []
    for q in questions:
        if not isinstance(q, dict):
            continue

        no_raw = q.get("no", "")
        # no를 int로 변환
        try:
            no_int = int(str(no_raw).strip().lstrip("0") or "0")
        except (ValueError, TypeError):
            no_int = 0

        # 과목 결정
        # 1) meta에 단일 과목이고 2교시/1교시 구분 필요 없는 경우
        fn_subject = detect_subject_from_filename(filename, exam, subjects_norm)

        if fn_subject and len(subjects_norm) <= 1:
            subject = fn_subject
        elif exam == "세무사" and len(subjects_norm) > 1:
            subject = get_subject_by_no(no_int, exam, filename, meta)
        elif fn_subject:
            subject = fn_subject
        elif subjects_norm:
            subject = subjects_norm[0]
        else:
            subject = "기타"

        stem = q.get("stem", "")
        choices = choices_to_list(q.get("choices", []))

        answer_raw = q.get("answer")
        if answer_raw is None:
            answer = None
        else:
            try:
                answer = int(answer_raw)
            except (ValueError, TypeError):
                answer = None

        record = {
            "exam": exam,
            "subject": subject,
            "year": year,
            "round": round_val,
            "q": stem,
            "c": choices,
            "a": answer,
            "e": q.get("my_explanation", "") or "",
            "s": q.get("law_status", "") or "",
            "v": bool(q.get("verify", False)),
            "cn": q.get("change_note", "") or "",
        }
        records.append(record)

    return records


# ─────────────────────────────────────────────
# 형식 B 파싱 (flat list)
# ─────────────────────────────────────────────
def process_format_b(data: list, filename: str) -> list[dict]:
    """형식 B (flat list) → compact 레코드 리스트."""
    records = []
    for item in data:
        if not isinstance(item, dict):
            continue

        raw_exam = item.get("exam", "")
        exam = normalize_exam(raw_exam)
        if not exam or exam not in ALLOWED_EXAMS:
            continue

        year = parse_year(item.get("year"))
        if not year or not (YEAR_RANGE[0] <= year <= YEAR_RANGE[1]):
            continue

        round_val = item.get("round")
        if round_val is not None:
            try:
                round_val = int(round_val)
            except (ValueError, TypeError):
                round_val = parse_round(None, exam, year)

        record = {
            "exam": exam,
            "subject": item.get("subject", "기타"),
            "year": year,
            "round": round_val,
            "q": item.get("q", ""),
            "c": item.get("c", []),
            "a": item.get("a"),
            "e": item.get("e", "") or "",
            "s": item.get("s", "") or "",
            "v": bool(item.get("v", False)),
            "cn": item.get("cn", "") or "",
        }
        records.append(record)

    return records


# ─────────────────────────────────────────────
# 중복 체크 키
# ─────────────────────────────────────────────
def make_dup_key(exam: str, subject: str, year, q: str) -> tuple:
    return (exam, subject, str(year), (q or "")[:30])


# ─────────────────────────────────────────────
# 메인
# ─────────────────────────────────────────────
def main():
    dry_run = "--dry-run" in sys.argv

    if dry_run:
        print("[DRY-RUN] 실제 저장은 하지 않습니다.\n")

    # ── 기존 questions.json 로드 ──
    print(f"기존 questions.json 로딩 중: {QUESTIONS_JSON}")
    with open(QUESTIONS_JSON, encoding="utf-8-sig") as f:
        existing = json.load(f)
    print(f"  → 기존 문제 수: {len(existing):,}개")

    # 중복 키 셋 구성
    existing_keys = set()
    existing_combo = defaultdict(int)  # (exam, subject, year) → 문제 수
    for item in existing:
        key = make_dup_key(
            item.get("exam", ""),
            item.get("subject", ""),
            item.get("year"),
            item.get("q", ""),
        )
        existing_keys.add(key)
        y = item.get("year")
        if isinstance(y, str):
            try: y = int(y)
            except: pass
        existing_combo[(item.get("exam",""), item.get("subject",""), y)] += 1

    # 다음 id 계산
    max_id = max((item.get("id", 0) for item in existing), default=0)
    next_id = max_id + 1

    # ── exams_updated 파일 순회 ──
    json_files = sorted(EXAMS_DIR.glob("*.json"))
    print(f"\nexams_updated 파일 수: {len(json_files)}개")

    new_records = []
    skipped_files = []
    subject_counts = defaultdict(int)
    exam_counts = defaultdict(int)

    for fpath in json_files:
        filename = fpath.name
        try:
            with open(fpath, encoding="utf-8-sig") as f:
                data = json.load(f)
        except Exception as e:
            print(f"  [SKIP] {filename}: JSON 파싱 오류 - {e}")
            skipped_files.append(filename)
            continue

        # 형식 판별
        if isinstance(data, list):
            records = process_format_b(data, filename)
        elif isinstance(data, dict) and "questions" in data:
            records = process_format_a(data, filename)
        else:
            # 알 수 없는 형식
            skipped_files.append(filename)
            continue

        # 중복 필터링
        file_added = 0
        for rec in records:
            # 이미 해당 (exam, subject, year) 조합에 문제가 있으면 건너뜀 (갭만 채움)
            combo = (rec["exam"], rec["subject"], rec["year"])
            if existing_combo[combo] > 0:
                continue

            key = make_dup_key(rec["exam"], rec["subject"], rec["year"], rec["q"])
            if key not in existing_keys:
                existing_keys.add(key)  # 중복 방지 (같은 배치 내)
                rec["id"] = next_id
                next_id += 1
                new_records.append(rec)
                subject_counts[f"{rec['exam']}|{rec['subject']}"] += 1
                exam_counts[rec["exam"]] += 1
                file_added += 1

        if file_added > 0:
            print(f"  [OK] {filename}: {file_added}문제 추가 예정")
        else:
            pass  # 중복 또는 범위 외

    # ── 결과 요약 ──
    print(f"\n{'='*60}")
    print(f"총 추가 예정 문제 수: {len(new_records):,}개")
    print(f"{'='*60}")

    if new_records:
        print("\n[시험별 추가 수]")
        for exam in sorted(exam_counts):
            print(f"  {exam}: {exam_counts[exam]:,}문제")

        print("\n[과목별 추가 수 (Top 30)]")
        sorted_subjects = sorted(subject_counts.items(), key=lambda x: -x[1])
        for key, cnt in sorted_subjects[:30]:
            exam, subj = key.split("|", 1)
            print(f"  {exam} / {subj}: {cnt}문제")
        if len(sorted_subjects) > 30:
            print(f"  ... 외 {len(sorted_subjects)-30}개 과목")
    else:
        print("추가할 새 문제가 없습니다.")

    if skipped_files:
        print(f"\n[스킵된 파일: {len(skipped_files)}개]")
        for fn in skipped_files[:10]:
            print(f"  - {fn}")

    # ── 실제 저장 ──
    if dry_run:
        print("\n[DRY-RUN] 저장 생략.")
        return

    if not new_records:
        print("\n추가할 문제가 없으므로 저장하지 않습니다.")
        return

    # 백업 (타임스탬프 포함)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = QUESTIONS_JSON.with_suffix(f".json.bak.{ts}")
    shutil.copy2(QUESTIONS_JSON, backup_path)
    print(f"\n백업 완료: {backup_path}")

    # 병합 후 저장
    merged = existing + new_records
    with open(QUESTIONS_JSON, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, separators=(",", ":"))

    print(f"저장 완료: {QUESTIONS_JSON}")
    print(f"  기존 {len(existing):,}개 + 신규 {len(new_records):,}개 = 총 {len(merged):,}개")


if __name__ == "__main__":
    main()
