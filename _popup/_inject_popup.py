# -*- coding: utf-8 -*-
"""취득세 실무사례집에 '심화 팝업'들을 주입한다.

· POPUPS 의 각 항목: 팝업 id, 본문 조각 파일, 버튼을 붙일 앵커 문구(그 문구가 든 블록 뒤에 버튼), 버튼 문구, 제목.
· 문서 끝(</body> 앞)에 마커 블록(공통 CSS/JS + 모달들)을 넣는다. 재실행 안전(이전 블록·버튼을 지우고 다시 넣는다).
· 대상 문서는 TARGETS 에 있는 것 중 존재하는 전부 — 원본(법제처 작업 폴더)과 읽을것들 사본.
  (읽을것들/_gather.py 가 원본 → 사본으로 복사하므로 원본에 넣어야 다음 '모으기'에서 사라지지 않는다.)

실행: python _inject_popup.py
"""
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = "지방세_취득세_실무사례집.html"
TARGETS = [
    os.path.join(os.path.dirname(HERE), NAME),                       # 원본: law_dashboard_work
    os.path.join(r"C:\python_programs\읽을것들", "06_취득세실무", NAME),  # 읽을것들 사본
]

BEGIN = "<!-- cmp-popup:begin -->"
END = "<!-- cmp-popup:end -->"

# (id, 조각 파일, [앵커 문구...], 버튼 문구, 제목, 부제)
POPUPS = [
    ("cmp", "증여간주_종합비교.html",
     ["6) 2026.1.1. 신설 — 배우자·직계존비속 간 유상거래의 증여 간주.",
      "3) 2026.1.1. 신설 — 저가양수의 증여 간주."],
     "📊 심화 팝업 — 취득세·증여세·양도세 종합비교 (부가세란? · 시나리오 12개 · 창구 판정 순서)",
     "심화 — 배우자·직계존비속 간 저가거래: 취득세·증여세·양도세 종합비교",
     "2026.1.1. 시행 지방세법 제7조 제11항 제4호 단서 · 시행령 제11조의3 기준 · 금액은 예시 가정에 따른 개산"),
    ("val", "시가인정액_평가.html",
     ["까지가 평가기간이므로, 취득 직후에 발생한 매매사례도 시가인정액이 될 수 있다."],
     "📐 심화 팝업 — 시가인정액 평가: 평가기간 계산 · 판단 기준일 · 여러 가액일 때 · 사후 경정 · 재산세와 대비",
     "심화 — 시가인정액 평가: 평가기간·기준일·복수 가액·사후 경정·재산세 대비",
     "지방세법 시행령 제14조 · 시행규칙 제4조의3 현행 기준"),
]

CSS = """
<style id="cmpPopupCss">
.popbtn-row{margin:6px 0 10px}
.popbtn{display:inline-flex;align-items:center;gap:6px;border:1px solid color-mix(in srgb,var(--pc) 45%,transparent);
 background:color-mix(in srgb,var(--pc) 8%,transparent);color:var(--pc);font-weight:800;font-size:13.2px;
 border-radius:9px;padding:6px 13px;cursor:pointer;font-family:inherit;line-height:1.6;text-align:left}
.popbtn:hover{background:color-mix(in srgb,var(--pc) 16%,transparent)}
.popwrap{position:fixed;inset:0;z-index:2147483000;display:flex;align-items:center;justify-content:center;padding:18px}
.popwrap[hidden]{display:none}
.popbg{position:absolute;inset:0;background:rgba(10,12,18,.55);backdrop-filter:blur(2px)}
.popcard{position:relative;width:min(1000px,100%);max-height:calc(100vh - 36px);background:var(--card);color:var(--fg);
 border:1px solid var(--line);border-radius:16px;box-shadow:0 20px 60px rgba(0,0,0,.35);display:flex;flex-direction:column;
 overflow:hidden;--pc:var(--accent)}
.pophead{display:flex;align-items:center;gap:10px;padding:13px 18px;border-bottom:1px solid var(--line);background:var(--side);flex:0 0 auto}
.pophead h2{margin:0;padding:0;border:0;font-size:15.5px;color:var(--fg);line-height:1.4;scroll-margin-top:0}
.pophead .sub{font-size:11.5px;color:var(--faint);font-weight:600}
.pophead .x{margin-left:auto;flex:0 0 auto;border:1px solid var(--line);background:var(--card);color:var(--muted);
 border-radius:9px;width:34px;height:34px;font-size:16px;cursor:pointer;font-family:inherit}
.pophead .x:hover{color:var(--warn);border-color:var(--warn)}
.popbody{overflow:auto;overscroll-behavior:contain;padding:18px 24px 48px;font-size:14.3px;line-height:1.82}
.popbody h3{font-size:16px;margin:32px 0 8px;padding:0 0 6px;border-bottom:2px solid var(--pc);color:var(--pc);
 letter-spacing:-.02em;font-weight:800;scroll-margin-top:10px}
.popbody h3:first-of-type{margin-top:18px}
.popbody p{margin:.8em 0}.popbody li{margin:.35em 0}
.pp-lead{background:var(--box);border-left:3px solid var(--pc);border-radius:0 12px 12px 0;padding:14px 18px;margin:0 0 14px;font-size:14.2px}
.pp-lead>b:first-child{display:block;font-size:12px;letter-spacing:.04em;color:var(--pc);margin-bottom:5px}
.pp-toc{display:flex;flex-wrap:wrap;gap:5px;align-items:center;margin:0 0 10px;padding:10px 12px;border:1px solid var(--line2);border-radius:12px;background:var(--side)}
.pp-toc>b{font-size:11.5px;color:var(--faint);letter-spacing:.04em;margin-right:4px}
.pp-toc a{font-size:12.3px;font-weight:700;color:var(--pc);text-decoration:none;border:1px solid color-mix(in srgb,var(--pc) 30%,transparent);
 border-radius:7px;padding:2px 9px;background:var(--card)}
.pp-toc a:hover{background:color-mix(in srgb,var(--pc) 12%,transparent)}
.ptbl{overflow-x:auto;margin:14px 0;border:1px solid var(--line);border-radius:12px;background:var(--card)}
.ptbl table{font-size:13.3px;line-height:1.65}
.ptbl table.pp-big{font-size:12.8px;min-width:900px}
.ptbl th{white-space:normal}
.pp-mini{font-size:12.4px;color:var(--muted)}
.pp-cites{font-size:13px;color:var(--muted)}
.pp-cites a{color:var(--accent);font-weight:600;text-decoration:none;border-bottom:1px solid color-mix(in srgb,var(--accent) 35%,transparent)}
.pp-cites a:hover{background:var(--chip);border-radius:4px}
.popbody a.pp-law{color:inherit;text-decoration:none;border-bottom:1.5px dotted var(--accent);cursor:pointer}
.popbody a.pp-law:hover{background:var(--chip);border-bottom-style:solid;color:var(--accent)}
.popbody .pp-hint{font-size:11.5px;color:var(--faint);margin:0 0 8px}
html.pop-open{overflow:hidden}
@media(max-width:700px){.popwrap{padding:0}.popcard{width:100%;height:100vh;max-height:100vh;border-radius:0}
 .popbody{padding:14px 14px 60px}.popbtn{font-size:12.6px}}
@media print{.popwrap,.popbtn-row{display:none!important}}
</style>
"""

MODAL = """
<div id="pop-{pid}" class="popwrap" hidden role="dialog" aria-modal="true" aria-labelledby="pop-{pid}-title">
<div class="popbg"></div>
<div class="popcard">
<div class="pophead"><div><h2 id="pop-{pid}-title">{title}</h2>
<div class="sub">{sub}</div></div>
<button type="button" class="x" aria-label="닫기">✕</button></div>
<div class="popbody">
<p class="pp-hint">밑줄 친 조문(예: 지방세법 제7조)을 누르면 떠 있는 법제처 대시보드에서 그 조문이 열립니다(노트 가능). 대시보드가 없으면 새 창으로 엽니다.</p>
{body}
</div>
</div>
</div>
"""

JS = """
<script id="cmpPopupJs">
(function(){
/* 대시보드(6155)나 그 /readables/ 경로에서 열렸으면 같은 서버(터널 주소 포함), 파일로 열었으면 로컬 6155 */
var DASH=(location.port==='6155'||location.pathname.indexOf('/readables/')===0)?'':'http://localhost:6155';
var wraps=document.querySelectorAll('.popwrap'); if(!wraps.length) return;
function setHash(id,on){
 if(!history.replaceState) return;
 var base=location.pathname+location.search;
 if(on) history.replaceState(null,'',base+'#pop-'+id);
 else if(location.hash==='#pop-'+id) history.replaceState(null,'',base);}
wraps.forEach(function(wrap){
 var id=wrap.id.replace(/^pop-/,''), body=wrap.querySelector('.popbody'), xbtn=wrap.querySelector('.x');
 wrap.querySelectorAll('a[href^="DASH/"]').forEach(function(a){
  a.href=DASH+a.getAttribute('href').slice(4); a.target='lawviewer'; a.rel='noopener';
  a.classList.add('lawlink'); /* 본문 스크립트의 클릭 위임(remote_open) 대상에 포함 */});
 function open(){
  wraps.forEach(function(w){if(w!==wrap)w.hidden=true;});
  wrap.hidden=false;document.documentElement.classList.add('pop-open');body.scrollTop=0;setHash(id,true);
  try{xbtn.focus({preventScroll:true});}catch(e){}}
 function close(){wrap.hidden=true;document.documentElement.classList.remove('pop-open');setHash(id,false);}
 document.querySelectorAll('.popbtn[data-pop="'+id+'"]').forEach(function(b){b.addEventListener('click',open);});
 wrap.querySelector('.popbg').addEventListener('click',close);
 xbtn.addEventListener('click',close);
 addEventListener('keydown',function(e){if(e.key==='Escape'&&!wrap.hidden){e.preventDefault();close();}});
 wrap.querySelectorAll('.pp-toc a').forEach(function(a){a.addEventListener('click',function(e){
  e.preventDefault();var t=wrap.querySelector(a.getAttribute('href'));if(t)t.scrollIntoView({behavior:'smooth',block:'start'});});});
 if(location.hash==='#pop-'+id) open();
});
})();
</script>
"""


# ── 조문 인용 자동 링크(법제처 대시보드 /open 딥링크) ────────────────────────
# 별칭 → 대시보드가 해석하는 정식 법령명. 긴 이름부터 매칭.
LAWS = {
    "지방세법": "지방세법", "지법": "지방세법",
    "지방세기본법": "지방세기본법", "지기법": "지방세기본법",
    "지방세특례제한법": "지방세특례제한법", "지특법": "지방세특례제한법",
    "소득세법": "소득세법", "법인세법": "법인세법",
    "상속세 및 증여세법": "상속세 및 증여세법", "상속세및증여세법": "상속세 및 증여세법",
    "상증세법": "상속세 및 증여세법", "상증법": "상속세 및 증여세법",
    "농어촌특별세법": "농어촌특별세법", "농특세법": "농어촌특별세법",
    "민법": "민법", "주택법": "주택법", "공동주택관리법": "공동주택관리법", "민사집행법": "민사집행법",
    "부동산 가격공시에 관한 법률": "부동산 가격공시에 관한 법률", "부동산공시법": "부동산 가격공시에 관한 법률",
    "감정평가 및 감정평가사에 관한 법률": "감정평가 및 감정평가사에 관한 법률",
}
_NAME_ALT = "|".join(re.escape(k) for k in sorted(LAWS, key=len, reverse=True))
CITE_RE = re.compile(
    rf"(?:(?P<name>{_NAME_ALT})(?P<sub1>\s?(?:시행령|시행규칙))?\s?(?P<jo1>(?:제\s?)?\d{{1,4}}\s?조(?:\s?의\s?\d{{1,3}})?)"
    rf"|(?P<anaph>같은\s?법|법)(?P<sub2>\s?(?:시행령|시행규칙))?\s(?P<jo2>제\s?\d{{1,4}}\s?조(?:\s?의\s?\d{{1,3}})?)"
    rf"|(?P<sub3>시행령|시행규칙)\s(?P<jo3>제\s?\d{{1,4}}\s?조(?:\s?의\s?\d{{1,3}})?)"
    rf"|(?P<jo4>제\s?\d{{1,4}}\s?조(?:\s?의\s?\d{{1,3}})?))"
)
_TAG_RE = re.compile(r"(<[^>]+>)")
_BLOCK_RE = re.compile(r"<(p|li|td|th|tr|h[1-6]|div|nav|ul|ol|table)\b")


def _family(law):
    return re.sub(r"\s*(시행령|시행규칙)$", "", law)


def linkify(html, log=None):
    """조각 HTML의 텍스트 노드에서 '○○법 제N조' 인용을 찾아 DASH/open 링크로 감싼다.
    이름 없는 '제N조'는 직전에 해석된 법령을 따른다('법 제N조'는 그 법령의 본법, '시행령 제N조'는 그 시행령)."""
    out, in_a, last = [], False, "지방세법"
    for seg in _TAG_RE.split(html):
        if seg.startswith("<"):
            low = seg.lower()
            if low.startswith("<a ") or low == "<a>":
                in_a = True
            elif low.startswith("</a"):
                in_a = False
            elif _BLOCK_RE.match(low):
                last = "지방세법"      # 블록(문단·항목·셀)이 바뀌면 지시 대상은 기본법으로 돌아간다
            out.append(seg)
            continue
        if in_a or "조" not in seg:
            out.append(seg)
            continue

        def rep(m):
            nonlocal last
            if m.group("name"):
                law = LAWS[m.group("name")] + ((" " + m.group("sub1").strip()) if m.group("sub1") else "")
                jo = m.group("jo1")
            elif m.group("anaph"):
                law = _family(last) + ((" " + m.group("sub2").strip()) if m.group("sub2") else "")
                jo = m.group("jo2")
            elif m.group("sub3"):
                law = _family(last) + " " + m.group("sub3")
                jo = m.group("jo3")
            else:
                law = last
                jo = m.group("jo4")
            jo = re.sub(r"\s+", "", jo)
            if not jo.startswith("제"):
                jo = "제" + jo
            last = law
            if log is not None:
                log.append((m.group(0), law, jo))
            href = "DASH/open?law=" + law + "&jo=" + jo
            # class 'lawlink': 사례집 본문 스크립트의 클릭 위임(/api/remote_open → 떠 있는 대시보드에서 열기,
            # 실패 시 창 열기)이 팝업 안 링크에도 그대로 적용된다.
            return f'<a class="lawlink pp-law" href="{href}" title="{law} {jo} — 법제처 대시보드에서 열기(노트 가능)">{m.group(0)}</a>'

        out.append(CITE_RE.sub(rep, seg))
    return "".join(out)


def btn_html(pid, label):
    return f'<p class="popbtn-row"><button type="button" class="popbtn" data-pop="{pid}">{label}</button></p>'


def inject(doc):
    with io.open(doc, encoding="utf-8", newline="") as f:
        html = f.read()
    nl = "\r\n" if "\r\n" in html else "\n"

    # 이전 주입분 제거
    html = re.sub(re.escape(BEGIN) + r".*?" + re.escape(END) + r"\s*", "", html, flags=re.S)
    html = re.sub(r'\s*<p class="popbtn-row">.*?</p>', "", html, flags=re.S)

    modals, n_btn = [], 0
    for pid, frag_name, anchors, label, title, sub in POPUPS:
        with io.open(os.path.join(HERE, frag_name), encoding="utf-8") as f:
            body = linkify(f.read().strip())
        for anchor in anchors:
            i = html.find(anchor)
            if i < 0:
                print(f"  앵커 없음[{pid}]: {anchor[:30]}")
                continue
            # 앵커가 든 블록(<p> 또는 <div ...>)의 닫는 태그 뒤에 버튼
            start = max(html.rfind("<p", 0, i), html.rfind("<div", 0, i))
            close_tag = "</p>" if html.startswith("<p", start) else "</div>"
            j = html.find(close_tag, i)
            if j < 0:
                continue
            j += len(close_tag)
            html = html[:j] + nl + btn_html(pid, label) + html[j:]
            n_btn += 1
        modals.append(MODAL.format(pid=pid, title=title, sub=sub, body=body))

    block = (BEGIN + CSS + "".join(modals) + JS + nl + END + nl).replace("\n", nl)
    k = html.lower().rfind("</body>")
    html = (html.rstrip() + nl + block) if k < 0 else (html[:k] + block + html[k:])

    with io.open(doc, "w", encoding="utf-8", newline="") as f:
        f.write(html)
    print(f"완료: {doc}  버튼 {n_btn}개, 블록 {len(block):,}자")


def main():
    done = 0
    for doc in TARGETS:
        if os.path.isfile(doc):
            inject(doc)
            done += 1
        else:
            print("대상 없음:", doc)
    return 0 if done else 1


if __name__ == "__main__":
    sys.exit(main())
