# -*- coding: utf-8 -*-
"""jeonbu_candidates.json -> jeonbu_map.json (확정 매핑표).

신뢰도 모델 + 큐레이션 보정으로 구 지방세법 조문 -> 현행 조문 매핑을 확정한다.
- curated : 사람(LLM) 검증한 핵심/충돌 조문 (confidence=high)
- auto    : 제목완전일치 + 본문유사도로 자동 확정
- review  : 제목충돌/저점수 -> 후보 보존, 검토 필요
- none    : 현행 대응 없음(폐지·통합·이동 추정)
"""
from __future__ import annotations
import io
import json
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
HERE = Path(__file__).resolve().parent
SAMPLES = HERE / "samples"

# 큐레이션 보정(고신뢰): 제목충돌이거나 판례에 자주 인용되는 취득세·세목 핵심 조문.
# 1:N(전부개정으로 분리)도 표현.
CURATED = {
    "제105조": [("지방세법", "제7조", "납세의무자 등")],              # 취득세 납세의무자
    "제106조": [("지방세법", "제9조", "비과세")],                    # 국가 등 비과세
    "제111조": [("지방세법", "제10조", "과세표준")],                 # 취득세 과세표준(+의2~의7로 세분)
    "제112조": [("지방세법", "제11조", "부동산 취득의 세율"),
                ("지방세법", "제12조", "부동산 외 취득의 세율"),
                ("지방세법", "제13조", "과밀억제권역 등 취득 중과")],  # 취득세 세율 → 분리
    "제120조": [("지방세법", "제20조", "신고 및 납부")],             # 취득세 신고납부
    "제183조": [("지방세법", "제107조", "납세의무자")],              # 재산세 납세의무자
    "제196조의2": [("지방세법", "제124조", "자동차의 정의")],         # 자동차세
    "제233조": [("지방세법", "제55조", "담배의 반출신고")],           # 담배소비세
}


def exact_title_cands(cands):
    return [c for c in cands if c.get("title_sim", 0) >= 0.95]


def main():
    src = json.load(open(SAMPLES / "jeonbu_candidates.json", encoding="utf-8"))
    rows_out = []
    stats = {"curated": 0, "auto": 0, "review": 0, "none": 0}

    for r in src["rows"]:
        oa, ot = r["old_art"], r["old_title"]
        cands = r.get("candidates", [])

        if oa in CURATED:
            mapped = [{"law": l, "art": a, "title": t} for (l, a, t) in CURATED[oa]]
            conf, method = "high", "curated"
        elif not cands:
            mapped, conf, method = [], "none", "none"
        else:
            top = cands[0]
            ex = exact_title_cands(cands)
            if top["title_sim"] >= 0.95 and top["body_sim"] >= 0.20 and len(ex) == 1:
                mapped = [{"law": top["law"], "art": top["art"], "title": top["title"]}]
                conf, method = "high", "auto"
            elif top["title_sim"] >= 0.95:
                # 제목완전일치지만 충돌(여러 세목) 또는 본문근거 약함 -> 검토
                mapped = [{"law": c["law"], "art": c["art"], "title": c["title"]}
                          for c in (ex or cands[:3])]
                conf, method = "medium", "review"
            elif top["score"] >= 0.45:
                mapped = [{"law": top["law"], "art": top["art"], "title": top["title"]}]
                conf, method = "low", "review"
            else:
                mapped, conf, method = [{"law": c["law"], "art": c["art"], "title": c["title"]}
                                        for c in cands[:3]], "low", "review"

        key = {"curated": "curated", "auto": "auto"}.get(method)
        if conf == "none":
            stats["none"] += 1
        elif method == "curated":
            stats["curated"] += 1
        elif method == "auto":
            stats["auto"] += 1
        else:
            stats["review"] += 1

        rows_out.append({
            "old_art": oa, "old_title": ot,
            "mapped": mapped, "confidence": conf, "method": method,
            "candidates": cands if method == "review" else [],
        })

    out = {
        "meta": {
            **src["meta"],
            "note": "구 지방세법(2010.3.31 전부개정 직전) -> 현행 조문 매핑. "
                    "confidence high=신뢰/medium·low=검토필요/none=현행대응없음(폐지·이동추정).",
            "stats": stats,
        },
        "rows": rows_out,
    }
    path = SAMPLES.parent / "jeonbu_map.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[완료] -> {path}")
    print("통계:", stats, "| 합계", sum(stats.values()))


if __name__ == "__main__":
    main()
