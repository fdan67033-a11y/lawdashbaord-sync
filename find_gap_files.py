# -*- coding: utf-8 -*-
import json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

with open("data/exams_text_v2/_extract_index.json", encoding="utf-8-sig") as f:
    idx = json.load(f)

TARGETS = [
    # 세무사 갭
    ("세무사", "상법", 2015, "2015년 세무사 1차 상법"),
    ("세무사", "재정학", 2015, "2015년 세무사 1차 재정학"),
    ("세무사", "행정소송법", 2015, "2015년 세무사 1차 행정소송법"),
    ("세무사", "세법학개론", 2015, "2015년 세무사 1차 세법학개론"),
    ("세무사", "민법", 2016, "2016년 세무사"),
    ("세무사", "재정학", 2016, "2016년 제53회 세무사 1차 1교시"),
    ("세무사", "세법학개론", 2016, "2016년 제53회 세무사 1차 1교시"),
    ("세무사", "행정소송법", 2016, "2016년 세무사"),
    ("세무사", "세법학개론", 2017, "2017년 세무사 1차 1교시"),
    # 감정평가사 2019
    ("감정평가사", "전체", 2019, "2019년"),
    # 법무사 2016-2017
    ("법무사", "1차", 2016, "2016년 제22회 법무사"),
    ("법무사", "1차", 2017, "2017년도 법무사1차"),
]

print("=== 갭 커버 가능 파일 ===")
for exam, subj, year, keyword in TARGETS:
    matches = [item for item in idx if keyword in item.get('folder','')]
    if matches:
        for m in matches[:2]:
            print(f"[{exam} {subj} {year}] {m['folder'][:50]} | {m['file'][:40]}")
            print(f"  -> {m.get('txt','')[:60]}")
    else:
        print(f"[{exam} {subj} {year}] ★미발견: '{keyword}'")

# 전체 semu 폴더 목록 (2015-2017)
print("\n=== semu 2015-2017 폴더 목록 ===")
seen_folders = set()
for item in idx:
    if item.get('source') == 'semu':
        folder = item.get('folder','')
        if any(y in folder for y in ['2015','2016','2017']) and folder not in seen_folders:
            seen_folders.add(folder)
            print(f"  {folder}")
