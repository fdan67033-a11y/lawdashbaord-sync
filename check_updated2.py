# -*- coding: utf-8 -*-
"""data/exams_updated/ 파일 구조 확인"""
import json, os, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

UPDATED_DIR = "data/exams_updated"

fname = "updated__semu__2016년 세무사 1차 2교시(회계학 개론, 민법) A형 문제입니다__회계학개론,민법(2교시 A형).json"
fpath = os.path.join(UPDATED_DIR, fname)
with open(fpath, encoding="utf-8-sig") as f:
    d = json.load(f)

print(f"타입: {type(d)}")
if isinstance(d, dict):
    print(f"키: {list(d.keys())}")
    meta = d.get("meta", {})
    print(f"meta: {meta}")
    qs = d.get("questions", [])
    print(f"문제수: {len(qs)}")
    if qs:
        print(f"첫 문제 키: {list(qs[0].keys())}")
        print(f"첫 문제: {qs[0]}")
elif isinstance(d, list):
    print(f"리스트 길이: {len(d)}")
    print(f"첫 항목 키: {list(d[0].keys())}")
    print(f"첫 항목: {d[0]}")
