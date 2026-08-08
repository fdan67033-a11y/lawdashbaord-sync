# -*- coding: utf-8 -*-
"""세무사 2016 1차 2교시 PDF에서 민법(41~80번) 파싱 → questions.json 추가"""
import sys, io, os, json, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import pdfplumber

BASE = os.path.dirname(os.path.abspath(__file__))
QJ = os.path.join(BASE, 'study', 'questions.json')

def extract_minbup_from_pdf(pdf_path, subject_name, start_q=41, end_q=80):
    """PDF에서 start_q~end_q 번 문제 파싱"""
    with pdfplumber.open(pdf_path) as pdf:
        full_text = ''
        for page in pdf.pages:
            t = page.extract_text() or ''
            full_text += '\n' + t

    # 과목 섹션 경계 찾기 (민법 / 행정소송법)
    # 41번부터 시작하도록 분리
    m = re.search(r'(?:민\s*법|행\s*정\s*소\s*송\s*법)\s*\n', full_text)
    if m:
        full_text = full_text[m.start():]
    else:
        # 41번 직전으로 자르기
        m2 = re.search(r'\n41\.', full_text)
        if m2:
            full_text = full_text[m2.start():]

    # 문제 분리: "41. ..." ~ "80. ..." 패턴
    # 선택지: ①②③④⑤ 또는 ① ② 등
    pattern = re.compile(
        r'(\d{1,2})\.\s+([\s\S]*?)(?=\n\d{1,2}\.\s+|\Z)',
        re.MULTILINE
    )

    questions = []
    for m in pattern.finditer(full_text):
        qno = int(m.group(1))
        if qno < start_q or qno > end_q:
            continue
        body = m.group(2).strip()

        # 선택지 분리: ①②③④⑤ 패턴
        choice_pattern = re.compile(r'([①②③④⑤])\s*([\s\S]*?)(?=[①②③④⑤]|\Z)')
        choice_parts = choice_pattern.findall(body)

        # 줄기는 첫 번째 ① 이전
        stem_end = body.find('①')
        if stem_end == -1:
            stem_end = len(body)
        stem = body[:stem_end].strip()

        choices = []
        circle_map = {'①': 1, '②': 2, '③': 3, '④': 4, '⑤': 5}
        for sym, txt in choice_parts:
            choices.append({
                'no': circle_map.get(sym, len(choices)+1),
                'text': txt.strip()
            })

        questions.append({
            'q_no': qno,
            'stem': stem,
            'choices': choices,
        })

    return questions

def make_records(qs, exam, subject, year, round_=53):
    """questions.json 레코드 생성"""
    records = []
    for q in qs:
        # choices를 문자열 리스트로
        c_list = [ch['text'] for ch in q['choices']]
        records.append({
            'exam': exam,
            'subject': subject,
            'year': year,
            'round': round_,
            'q': q['stem'],
            'c': c_list,
            'a': None,   # 정답 미확인
            'e': None,
            's': None,
            'v': True,   # 검증 필요
            'cn': None,
        })
    return records

def main():
    # === 세무사 2016 민법 ===
    pdf_minbup = os.path.join(BASE,
        'data/exams/semu/2016년 세무사 1차 2교시(회계학 개론, 민법) A형 문제입니다',
        '회계학개론,민법(2교시 A형).pdf')

    # === 세무사 2016 행정소송법 ===
    pdf_haengjong = os.path.join(BASE,
        'data/exams/semu/2016년 세무사 1차 2교시(회계학 개론, 행정소송법) A형 문제입니다',
        '회계학개론,행정소송법(2교시 A형).pdf')

    # 기존 questions.json 로드
    with open(QJ, encoding='utf-8') as f:
        existing = json.load(f)
    print(f'기존 문제 수: {len(existing)}')

    # 중복 체크 키
    existing_keys = set()
    for item in existing:
        key = (item.get('exam',''), item.get('subject',''), item.get('year'))
        existing_keys.add(key)

    new_records = []

    # 민법 2016 파싱
    if ('세무사', '민법', 2016) not in existing_keys:
        print('세무사 민법 2016 파싱 중...')
        qs_minbup = extract_minbup_from_pdf(pdf_minbup, '민법')
        print(f'  → {len(qs_minbup)}문항 파싱됨')
        for q in qs_minbup[:3]:
            print(f'  Q{q["q_no"]}: {q["stem"][:60]}')
        recs_m = make_records(qs_minbup, '세무사', '민법', 2016, round_=53)
        new_records.extend(recs_m)
    else:
        print('세무사 민법 2016 이미 존재, 건너뜀')

    # 행정소송법 2016 파싱
    if ('세무사', '행정소송법', 2016) not in existing_keys:
        print('세무사 행정소송법 2016 파싱 중...')
        qs_hj = extract_minbup_from_pdf(pdf_haengjong, '행정소송법')
        print(f'  → {len(qs_hj)}문항 파싱됨')
        for q in qs_hj[:3]:
            print(f'  Q{q["q_no"]}: {q["stem"][:60]}')
        recs_hj = make_records(qs_hj, '세무사', '행정소송법', 2016, round_=53)
        new_records.extend(recs_hj)
    else:
        print('세무사 행정소송법 2016 이미 존재, 건너뜀')

    if not new_records:
        print('추가할 새 문제 없음')
        return

    print(f'\n추가 예정: {len(new_records)}문항')
    print('자동 승인으로 진행...')

    # ID 부여 및 병합
    max_id = max((item.get('id', 0) or 0) for item in existing) if existing else 0
    for i, rec in enumerate(new_records):
        rec['id'] = max_id + i + 1

    combined = existing + new_records

    # 백업 후 저장
    import shutil, datetime
    bak = QJ + '.bak.' + datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    shutil.copy2(QJ, bak)
    print(f'백업: {bak}')

    with open(QJ, 'w', encoding='utf-8') as f:
        json.dump(combined, f, ensure_ascii=False, separators=(',', ':'))
    print(f'저장 완료: {len(combined)}문제 (추가 {len(new_records)})')

if __name__ == '__main__':
    main()
