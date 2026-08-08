# -*- coding: utf-8 -*-
"""olefile로 HWP5 BodyText 텍스트 추출"""
import olefile, zlib, struct, sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

HWP_DIR = 'data/_gamp2019_hwp'

def extract_hwp_text(fpath):
    """HWP5 BodyText/Section* → 텍스트 추출"""
    texts = []
    with olefile.OleFileIO(fpath) as ole:
        # FileHeader에서 압축 여부 확인
        compressed = True
        if ole.exists('FileHeader'):
            header = ole.openstream('FileHeader').read()
            # 31번째 바이트(offset 36) flags
            if len(header) >= 40:
                flags = struct.unpack_from('<I', header, 36)[0]
                compressed = bool(flags & 0x1)

        # BodyText/Section* 순회
        i = 0
        while ole.exists(f'BodyText/Section{i}'):
            data = ole.openstream(f'BodyText/Section{i}').read()
            if compressed:
                try:
                    data = zlib.decompress(data, -15)
                except:
                    pass
            # HWP 레코드 파싱
            pos = 0
            while pos + 4 <= len(data):
                header_word = struct.unpack_from('<I', data, pos)[0]
                rec_type = header_word & 0x3FF
                level = (header_word >> 10) & 0x3FF
                size = (header_word >> 20) & 0xFFF
                pos += 4
                if size == 0xFFF:
                    if pos + 4 > len(data): break
                    size = struct.unpack_from('<I', data, pos)[0]
                    pos += 4
                payload = data[pos:pos+size]
                pos += size
                # PARA_TEXT = 67
                if rec_type == 67 and payload:
                    try:
                        text = payload.decode('utf-16-le', errors='ignore')
                        # 제어 문자 제거 (0x0~0x1F 중 일부)
                        clean = ''.join(c for c in text if c == '\n' or c == ' ' or ord(c) >= 0x20)
                        if clean.strip():
                            texts.append(clean.strip())
                    except:
                        pass
            i += 1
    return texts

for fname in sorted(os.listdir(HWP_DIR)):
    if not fname.endswith('.hwp'):
        continue
    fpath = os.path.join(HWP_DIR, fname)
    print(f"\n{'='*70}")
    print(f"[{fname}]")
    try:
        texts = extract_hwp_text(fpath)
        print(f"  추출된 단락: {len(texts)}개")
        for t in texts[:40]:
            print(f"  {t[:100]}")
    except Exception as e:
        print(f"  오류: {e}")
