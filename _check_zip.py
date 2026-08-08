# -*- coding: utf-8 -*-
import zipfile, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

zf = 'data/exams/gampyeong/2019년 제30회 감정평가사 1차시험 기출문제/2019년 제30회 감정평가사 1차시험 문제지.zip'
with zipfile.ZipFile(zf) as z:
    for name in z.namelist():
        info = z.getinfo(name)
        print(f'{name}  ({info.file_size:,} bytes)')
