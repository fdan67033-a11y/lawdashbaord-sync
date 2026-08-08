# -*- coding: utf-8 -*-
"""
_gamp_struct/ 의 신규 기출 파일을 questions.json에 병합하는 스크립트.

사용법:
  python merge_gamp.py [--dry-run] [--files file1.json file2.json ...]
  --dry-run  : questions.json을 수정하지 않고 미리보기만
  --files    : 지정 파일만 병합 (기본: INCLUDE_FILES 목록)
"""

import json, os, sys, shutil
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
GAMP_DIR = os.path.join(BASE, "data", "_gamp_struct")
QUESTIONS_PATH = os.path.join(BASE, "study", "questions.json")

# 병합할 파일 목록 (실제 텍스트가 확인/추정된 파일들만)
# 이 목록에 없는 파일은 병합하지 않음
INCLUDE_FILES = [
    # 세무사 2015 1차 (공기출에서 실제 텍스트 파싱 확인)
    "semu_2015_1차_회계학개론.json",
    "semu_2015_1차_민법.json",
    "semu_2015_1차_행정소송법.json",
    "semu_2015_1차_세법학개론.json",
    # 세무사 상법 URL이 실제 세법학개론이었으므로 제외
    # "semu_2015_1차_상법.json",

    # 법무사 2015 1차 상법 (Chrome MCP 실제 추출)
    "bupmu_2015_1차_상법.json",

    # 법무사 2020 1차 상법 (공기출 실제 텍스트)
    "bupmu_2020_1차_상법.json",

    # 법무사 2021 1차 헌법 (Chrome MCP 실제 추출 확인)
    "bupmu_2021_1차_헌법.json",

    # 법무사 2023 1차 (Chrome MCP/WebFetch 실제 텍스트 추출 확인)
    "bupmu_2023_1차_민법.json",
    "bupmu_2023_1차_상법.json",

    # 법무사 2024 1차 헌법 (공기출 실제 텍스트)
    "bupmu_2024_1차_헌법.json",

    # 법무사 2025 1차 헌법 (Chrome MCP 실제 추출)
    "bupmu_2025_1차_헌법.json",

    # 공인노무사 2015-2022 미병합 파일 (공기출 텍스트 파싱)
    "nomy_2015_1차_경영학개론.json",
    "nomy_2015_1차_경제학개론.json",
    "nomy_2015_1차_노동법Ⅱ.json",
    "nomy_2015_1차_민법.json",
    "nomy_2015_1차_사회보험법.json",
    "nomy_2016_1차_경제학개론.json",
    "nomy_2016_1차_민법.json",
    "nomy_2016_1차_사회보험법.json",
    "nomy_2017_1차_경제학개론.json",
    "nomy_2017_1차_노동법Ⅰ.json",
    "nomy_2017_1차_민법.json",
    "nomy_2017_1차_사회보험법.json",
    "nomy_2018_1차_경영학개론.json",
    "nomy_2018_1차_경제학개론.json",
    "nomy_2018_1차_노동법Ⅰ.json",
    "nomy_2018_1차_노동법Ⅱ.json",
    "nomy_2019_1차_경영학개론.json",
    "nomy_2019_1차_경제학개론.json",
    "nomy_2019_1차_민법.json",
    "nomy_2019_1차_사회보험법.json",
    "nomy_2020_1차_경영학개론.json",
    "nomy_2020_1차_노동법Ⅰ.json",
    "nomy_2020_1차_노동법Ⅱ.json",
    "nomy_2020_1차_사회보험법.json",
    "nomy_2021_1차_경영학개론.json",
    "nomy_2021_1차_노동법Ⅰ.json",
    "nomy_2021_1차_노동법Ⅱ.json",
    "nomy_2022_1차_경영학개론.json",
    "nomy_2022_1차_경제학개론.json",
    "nomy_2022_1차_노동법Ⅰ.json",
    "nomy_2022_1차_노동법Ⅱ.json",
    "nomy_2022_1차_민법.json",
    "nomy_2022_1차_사회보험법.json",

    # 노무사 2023 민법 (comcbt.com 교사용 PDF 파싱, 25문)
    "nomy_2023_1차_민법.json",

    # 노무사 2023 노동법Ⅰ (완료)
    "nomy_2023_1차_노동법Ⅰ.json",

    # 노무사 2021 민법 (완료)
    "nomy_2021_1차_민법.json",

    # 노무사 2020 경제학개론 (공기출 텍스트 파싱, 25문)
    "nomy_2020_1차_경제학개론.json",

    # 세무사 2017 행정소송법
    "semu_2017_1차_행정소송법.json",

    # 감정평가사 2023 (공기출 HTML 텍스트 파싱)
    "gamp_2023_1차_감정평가관련법규.json",
    "gamp_2023_1차_경제학원론.json",
    "gamp_2023_1차_민법.json",
    "gamp_2023_1차_회계학원론.json",

    # 감정평가사 2019 2차 논술 (기존 _gamp_struct에 있으나 미병합)
    "gamp_2019_2차_법규.json",
    "gamp_2019_2차_실무.json",
    "gamp_2019_2차_이론.json",

    # 법무사 2020 민법 (기존 _gamp_struct에 있으나 미병합)
    "bupmu_2020_1차_민법.json",

    # 감정평가사 2019 1차 (신규 추가)
    "gamp_2019_1차_감정평가관계법규.json",
    "gamp_2019_1차_회계학.json",

    # 법무사 헌법 신규 (2015~2023)
    "bupmu_2015_1차_헌법.json",
    "bupmu_2016_1차_헌법.json",
    "bupmu_2017_1차_헌법.json",
    "bupmu_2018_1차_헌법.json",
    "bupmu_2019_1차_헌법.json",
    "bupmu_2020_1차_헌법.json",
    "bupmu_2022_1차_헌법.json",
    "bupmu_2023_1차_헌법.json",

    # 법무사 상법 신규 (2016~2025)
    "bupmu_2016_1차_상법.json",
    "bupmu_2017_1차_상법.json",
    "bupmu_2018_1차_상법.json",
    "bupmu_2019_1차_상법.json",
    "bupmu_2021_1차_상법.json",
    "bupmu_2022_1차_상법.json",
    "bupmu_2024_1차_상법.json",
    "bupmu_2025_1차_상법.json",

    # 법무사 민법 신규 (2016~2025)
    "bupmu_2016_1차_민법.json",
    "bupmu_2017_1차_민법.json",
    "bupmu_2018_1차_민법.json",
    "bupmu_2019_1차_민법.json",
    "bupmu_2021_1차_민법.json",
    "bupmu_2024_1차_민법.json",
    "bupmu_2025_1차_민법.json",
]

def load_questions():
    with open(QUESTIONS_PATH, encoding="utf-8-sig") as f:
        return json.load(f)

def check_duplicates(existing, new_items):
    """중복 검사: (exam, subject, year, round, q 첫 30자)로 판별"""
    seen = set()
    for q in existing:
        key = (q.get("exam",""), q.get("subject",""), q.get("year",""), q.get("round",""), (q.get("q","") or "")[:30])
        seen.add(key)
    dupes = []
    unique = []
    for q in new_items:
        key = (q.get("exam",""), q.get("subject",""), q.get("year",""), q.get("round",""), (q.get("q","") or "")[:30])
        if key in seen:
            dupes.append(q)
        else:
            seen.add(key)
            unique.append(q)
    return unique, dupes

def main():
    dry_run = "--dry-run" in sys.argv
    custom_files = None
    if "--files" in sys.argv:
        idx = sys.argv.index("--files")
        custom_files = sys.argv[idx+1:]

    files = custom_files if custom_files else INCLUDE_FILES

    print(f"=== 기출 병합 {'(DRY RUN)' if dry_run else ''} ===")
    print(f"병합 대상 파일 수: {len(files)}")

    # questions.json 로드
    existing = load_questions()
    max_id = max(q.get("id", 0) for q in existing) if existing else -1
    print(f"기존 문제 수: {len(existing)}, 최대 ID: {max_id}")

    new_items = []
    skipped = []

    for fname in files:
        fpath = os.path.join(GAMP_DIR, fname)
        if not os.path.exists(fpath):
            print(f"  [SKIP] {fname} - 파일 없음")
            skipped.append(fname)
            continue
        data = None
        for enc in ["utf-8", "utf-8-sig"]:
            try:
                with open(fpath, encoding=enc) as f:
                    data = json.load(f)
                break
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
        if data is None:
            print(f"  [ERROR] {fname} - JSON 파싱 실패")
            skipped.append(fname)
            continue

        if not isinstance(data, list) or not data:
            print(f"  [SKIP] {fname} - 빈 배열")
            skipped.append(fname)
            continue

        # exam name 정규화 ("공인노무사" → "노무사")
        EXAM_ALIAS = {"공인노무사": "노무사"}
        for q in data:
            if q.get("exam") in EXAM_ALIAS:
                q["exam"] = EXAM_ALIAS[q["exam"]]

        print(f"  [OK] {fname} - {len(data)}문제")
        new_items.extend(data)

    # 중복 제거
    unique, dupes = check_duplicates(existing, new_items)
    if dupes:
        print(f"\n중복 문제 제외: {len(dupes)}개")
        for d in dupes[:5]:
            print(f"  - {d.get('exam')} {d.get('subject')} {d.get('year')} 문{d.get('id')}")
        if len(dupes) > 5:
            print(f"  ... 외 {len(dupes)-5}개")

    # ID 재발급
    next_id = max_id + 1
    for q in unique:
        q["id"] = next_id
        next_id += 1

    print(f"\n병합 예정 문제 수: {len(unique)}")
    print(f"병합 후 총 문제 수: {len(existing) + len(unique)}")

    if not unique:
        print("병합할 문제가 없습니다.")
        return

    if dry_run:
        print("\n[DRY RUN] questions.json은 수정되지 않았습니다.")
        return

    # 백업
    bak = QUESTIONS_PATH + f".bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(QUESTIONS_PATH, bak)
    print(f"\n백업: {bak}")

    # 병합 & 저장
    merged = existing + unique
    with open(QUESTIONS_PATH, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, separators=(",", ":"))

    size_kb = os.path.getsize(QUESTIONS_PATH) / 1024
    print(f"저장 완료: questions.json ({size_kb:.0f} KB, {len(merged)}문제)")

if __name__ == "__main__":
    main()
