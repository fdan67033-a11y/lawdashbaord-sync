from __future__ import annotations

import csv
import hashlib
import html
import json
import os
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlencode, quote
from concurrent.futures import ThreadPoolExecutor

import requests
try:
    from dotenv import load_dotenv
except Exception:  # python-dotenv가 없어도 실행되도록 처리
    def load_dotenv(*args: Any, **kwargs: Any) -> None:
        return None
from flask import Flask, Response, jsonify, redirect, request, send_file, send_from_directory

SCRIPT_DIR = Path(__file__).resolve().parent


def _candidate_dashboard_dirs() -> List[Path]:
    """Find the dashboard folder that owns static/index.html.

    This lets the lightweight patched app run even when the v8 files were copied
    into a version subfolder such as C:\todo_manual_dashboard\law_dashboard_work\v7.
    In that case the original dashboard folder still owns the static folder.
    """
    candidates: List[Path] = []
    raw = [
        SCRIPT_DIR,
        Path.cwd(),
        SCRIPT_DIR.parent,
        Path(r"C:\todo_manual_dashboard\law_dashboard_work\law_dashboard_json_v36_fhd_pdf_preview_cache"),
        Path(r"C:\todo_manual_dashboard\law_dashboard_work\v7"),
        Path(r"C:\todo_manual_dashboard\law_dashboard_work"),
    ]
    for item in raw:
        try:
            p = item.resolve()
        except Exception:
            p = item
        if p not in candidates:
            candidates.append(p)
    work = Path(r"C:\todo_manual_dashboard\law_dashboard_work")
    try:
        if work.exists():
            for child in sorted(work.iterdir(), key=lambda x: x.stat().st_mtime if x.exists() else 0, reverse=True):
                if child.is_dir() and child not in candidates:
                    candidates.append(child)
    except Exception:
        pass
    return candidates


def _resolve_base_dir() -> Path:
    for folder in _candidate_dashboard_dirs():
        try:
            if (folder / "static" / "index.html").exists():
                return folder
        except Exception:
            pass
    return SCRIPT_DIR


BASE_DIR = _resolve_base_dir()
DATA_DIR = BASE_DIR / "data"
CACHE_DIR = DATA_DIR / "cache"
FORMS_DIR = DATA_DIR / "forms"
GIJANG_MANUAL_PATH = BASE_DIR / "gijang_ordinances_manual.json"
DB_PATH = DATA_DIR / "dashboard.db"
POOLS_PATH = DATA_DIR / "law_pools.json"

# 회독·노트 git 동기화 모듈(sync_util.py) — 없거나 실패해도 앱은 동작
import sys as _sys
if str(BASE_DIR) not in _sys.path:
    _sys.path.insert(0, str(BASE_DIR))
try:
    import sync_util
except Exception:
    sync_util = None
UI_STATE_PATH = DATA_DIR / "ui_state.json"
HANJA_DICT_PATH = BASE_DIR / "hanja_dict.json"
DATA_DIR.mkdir(exist_ok=True)
CACHE_DIR.mkdir(exist_ok=True)
FORMS_DIR.mkdir(exist_ok=True)

load_dotenv(BASE_DIR / ".env")

APP_TITLE = "법제처 JSON 업무검색 대시보드 v36.16 v20 API 확장"
LAW_BASE_URL = "https://www.law.go.kr/DRF"
CACHE_TTL_SECONDS = 60 * 60 * 12
CACHE_VERSION = "v20_api_expansion_ua2"
# v20: 검색이 느린 원인은 CPU가 아니라 법제처 API 응답 대기(I/O)입니다.
# 여러 요청을 동시에 보내 대기시간을 줄입니다. (멀티코어 연산이 아닌 동시 I/O)
SEARCH_MAX_WORKERS = min(16, (os.cpu_count() or 4) * 2)

app = Flask(__name__, static_folder=str(BASE_DIR / "static"))
# v20: 검색대상 체크박스가 TARGETS 정의 순서대로 나오도록 JSON 키 정렬을 끕니다.
try:
    app.json.sort_keys = False  # Flask 2.2+
except Exception:
    app.config["JSON_SORT_KEYS"] = False


# 로컬 다른 앱(예: 지방세연구원 뷰어 localhost:8017)에서 gold한자 변환 API를
# 호출할 수 있도록 CORS 허용 + OPTIONS 프리플라이트 처리.
@app.after_request
def _add_cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS, DELETE"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp


@app.route("/api/<path:_any>", methods=["OPTIONS"])
def _cors_preflight(_any):
    return ("", 204)

QUICK_LAWS = [
    "지방세기본법", "지방세기본법 시행령", "지방세기본법 시행규칙",
    "지방세법", "지방세법 시행령", "지방세법 시행규칙",
    "지방세징수법", "지방세징수법 시행령", "지방세징수법 시행규칙",
    "지방세특례제한법", "지방세특례제한법 시행령", "지방세특례제한법 시행규칙",
    "지방세외수입금의 징수 등에 관한 법률", "지방행정제재ㆍ부과금의 징수 등에 관한 법률",
    "부산광역시 기장군 군세 조례", "부산광역시 기장군 군세 감면 조례",
]

QUICK_KEYWORDS = [
    "취득세", "재산세", "자동차세", "등록면허세", "지방소득세", "주민세",
    "과세표준", "납세의무자", "부과제척기간", "가산세", "감면", "환급",
    "징수유예", "체납처분", "압류", "결손처분", "시가표준액", "세율",
    "공유재산", "일상경비", "초과근무", "복무", "여비", "관용차량",
]

TARGETS = {
    "eflaw": "현행법령(시행일)",
    "law": "현행법령(공포일)",
    "admrul": "행정규칙",
    "ordin": "자치법규(전체)",
    "ordin_gijang": "자치법규(기장군)",
    "expc": "법령해석례",
    "prec": "판례",
    # v20 신규 검색대상
    "moisCgmExpc": "행안부 1차해석",
    "ttSpecialDecc": "조세심판원 결정례",
    "decc": "행정심판례(권익위)",
    "detc": "헌재결정례",
    "baiPvcs": "감사원 사전컨설팅",
    "licbyl": "별표서식(법령)",
    "admbyl": "별표서식(행정규칙)",
    "ordinbyl": "별표서식(자치법규)",
}

# 사례형: 조문 구조가 아니라 질의요지/이유/재결요지 등 섹션 구조로 내려오는 대상.
# 상세조회는 lawService JSON을 섹션 단위로 정규화해 표시합니다. (판례는 기존 전용 경로 유지)
CASE_TARGETS = {"expc", "decc", "detc", "moisCgmExpc", "ttSpecialDecc", "baiPvcs"}

# 별표서식형: 목록조회만 제공되고 본문조회가 없습니다.
# 상세보기는 목록 재조회로 파일 다운로드 링크(annexes)를 합성해 표시합니다.
BYL_TARGETS = {"licbyl", "admbyl", "ordinbyl"}

# 기장군 자치법규 직접조회용 지자체코드 (org=부산광역시, sborg=기장군)
# 코드는 법제처 자치법규 목록조회 가이드의 지자체코드 기준이며 2026-06 실측 검증값입니다.
GIJANG_ORG = "6260000"
GIJANG_SBORG = "3400000"


def api_target_of(target: str) -> str:
    if target in ("ordin_gijang",):
        return "ordin"
    return target




def service_target_of(target: str) -> str:
    """lawSearch.do와 lawService.do는 target 사용법이 일부 다릅니다.
    목록검색은 eflaw를 쓰더라도 상세본문 조회는 lawService.do의 law로 조회해야
    조문 본문이 정상적으로 내려옵니다.
    """
    if target == "eflaw":
        return "law"
    return api_target_of(target)

def org_of(target: str) -> str:
    if target == "ordin_gijang":
        return "부산광역시 기장군"
    return ""


def row_matches_target_alias(item: Dict[str, Any], target: str) -> bool:
    if target == "ordin_gijang":
        hay = json.dumps(item, ensure_ascii=False)
        name = str(item.get("name") or "")
        dept = str(item.get("department") or "")
        return "기장군" in hay or name.startswith("부산광역시 기장군") or "기장군" in dept
    return True

DEFAULT_POOLS = {
    "지방세 기본": [
        "지방세법", "지방세법 시행령", "지방세법 시행규칙",
        "지방세기본법", "지방세기본법 시행령", "지방세기본법 시행규칙",
        "지방세징수법", "지방세징수법 시행령", "지방세징수법 시행규칙",
        "지방세특례제한법", "지방세특례제한법 시행령", "지방세특례제한법 시행규칙",
    ],
    "서무·복무·회계": [
        "지방공무원법", "지방공무원 복무규정", "지방자치단체 회계관리에 관한 훈령",
        "지방회계법", "지방회계법 시행령",
        "지방자치단체를 당사자로 하는 계약에 관한 법률",
        "지방자치단체를 당사자로 하는 계약에 관한 법률 시행령",
        "공유재산 및 물품 관리법", "공유재산 및 물품 관리법 시행령",
        "공무원 여비 규정",
    ],
    "재산세 담당": [
        "지방세법", "지방세법 시행령", "지방세법 시행규칙",
        "지방세특례제한법", "지방세특례제한법 시행령",
        "부동산 가격공시에 관한 법률", "부동산 가격공시에 관한 법률 시행령",
        "공간정보의 구축 및 관리 등에 관한 법률", "건축법", "건축법 시행령",
        "국토의 계획 및 이용에 관한 법률", "국토의 계획 및 이용에 관한 법률 시행령",
    ],
}


def init_db() -> None:
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS bookmarks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                law_name TEXT,
                target TEXT,
                law_id TEXT,
                mst TEXT,
                efyd TEXT,
                jo TEXT,
                title TEXT,
                body TEXT,
                source_url TEXT,
                tags TEXT DEFAULT ''
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS notes (
                key TEXT PRIMARY KEY,
                updated_at TEXT NOT NULL,
                note TEXT NOT NULL
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS thread_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                parent_id INTEGER,
                law_name TEXT,
                target TEXT,
                law_id TEXT,
                mst TEXT,
                article TEXT,
                paragraph TEXT,
                ho TEXT,
                mok TEXT,
                unit_level TEXT,
                unit_text TEXT,
                body TEXT NOT NULL
            )
            """
        )
        con.commit()


init_db()

def ensure_note_schema() -> None:
    """확장 노트 기능용 보조 테이블/컬럼을 보장합니다."""
    with sqlite3.connect(DB_PATH) as con:
        try:
            con.execute("ALTER TABLE thread_notes ADD COLUMN title TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass
        for _col, _default in (("source", "me"), ("q", ""), ("imgs", "[]")):
            try:
                con.execute(f"ALTER TABLE thread_notes ADD COLUMN {_col} TEXT DEFAULT '{_default}'")
            except sqlite3.OperationalError:
                pass
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS thread_note_refs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                note_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                law_name TEXT,
                target TEXT,
                law_id TEXT,
                mst TEXT,
                article TEXT,
                paragraph TEXT,
                ho TEXT,
                mok TEXT,
                unit_level TEXT,
                unit_text TEXT,
                FOREIGN KEY(note_id) REFERENCES thread_notes(id) ON DELETE CASCADE
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS thread_note_urls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                note_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                title TEXT,
                url TEXT NOT NULL,
                FOREIGN KEY(note_id) REFERENCES thread_notes(id) ON DELETE CASCADE
            )
            """
        )
        con.commit()


ensure_note_schema()


# ---- 한자(漢字) 루비 변환 사전 (한글→한자는 무료 라이브러리가 없어 직접 큐레이션) ----
_HANJA_SEED_CACHE: Dict[str, Any] = {"mtime": 0.0, "data": {}}


def load_hanja_seed() -> Dict[str, str]:
    """큐레이션 시드 사전(term->漢字)을 파일에서 로드. 파일 변경 시 자동 재로딩."""
    try:
        st = HANJA_DICT_PATH.stat()
    except OSError:
        return {}
    if st.st_mtime != _HANJA_SEED_CACHE["mtime"]:
        try:
            raw = json.loads(HANJA_DICT_PATH.read_text(encoding="utf-8"))
            data = {k: v for k, v in raw.items()
                    if not str(k).startswith("_") and isinstance(v, str) and v}
        except Exception:
            data = {}
        _HANJA_SEED_CACHE["data"] = data
        _HANJA_SEED_CACHE["mtime"] = st.st_mtime
    return dict(_HANJA_SEED_CACHE["data"])


def ensure_hanja_schema() -> None:
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS hanja_overrides (
                term TEXT PRIMARY KEY,
                hanja TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                source TEXT DEFAULT 'user'
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS hanja_law (
                law_key TEXT PRIMARY KEY,
                law_name TEXT,
                data TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        con.commit()


def load_hanja_overrides() -> Dict[str, str]:
    ensure_hanja_schema()
    with sqlite3.connect(DB_PATH) as con:
        rows = con.execute("SELECT term, hanja FROM hanja_overrides").fetchall()
    return {str(r[0]): str(r[1]) for r in rows}


def merged_hanja_dict() -> Dict[str, str]:
    """시드 + 사용자 교정(교정 우선). hanja=''는 '한자 안 붙임'(억제) 표시로 유지."""
    d = load_hanja_seed()
    for term, hanja in load_hanja_overrides().items():
        d[term] = hanja
    return d


ensure_hanja_schema()


def load_pools() -> Dict[str, List[str]]:
    if POOLS_PATH.exists():
        try:
            raw = json.loads(POOLS_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return {str(k): [str(x).strip() for x in v if str(x).strip()] for k, v in raw.items() if isinstance(v, list)}
        except Exception:
            pass
    save_pools(DEFAULT_POOLS)
    return dict(DEFAULT_POOLS)


def save_pools(pools: Dict[str, List[str]]) -> None:
    POOLS_PATH.write_text(json.dumps(pools, ensure_ascii=False, indent=2), encoding="utf-8")


def get_oc() -> str:
    oc = request.args.get("oc") or request.headers.get("X-OPENLAW-OC") or os.getenv("OPENLAW_OC") or ""
    return oc.strip()


def cache_key(endpoint: str, params: Dict[str, Any]) -> Path:
    clean_params = {k: v for k, v in sorted(params.items()) if k.lower() != "oc" and v not in (None, "")}
    raw = CACHE_VERSION + "|" + endpoint + "?" + urlencode(clean_params, doseq=True)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return CACHE_DIR / f"{digest}.json"


def request_law_api(endpoint: str, params: Dict[str, Any], refresh: bool = False) -> Dict[str, Any]:
    oc = params.get("OC") or get_oc()
    if not oc:
        return {"ok": False, "error": "OPEN API 인증키(OC)가 필요합니다. 화면 상단에 입력하거나 .env에 OPENLAW_OC를 설정하세요."}

    params = {k: v for k, v in params.items() if v not in (None, "")}
    params["OC"] = oc
    params.setdefault("type", "JSON")

    ck = cache_key(endpoint, params)
    if not refresh and ck.exists() and time.time() - ck.stat().st_mtime < CACHE_TTL_SECONDS:
        try:
            cached = json.loads(ck.read_text(encoding="utf-8"))
            cached["cached"] = True
            return cached
        except Exception:
            pass

    url = f"{LAW_BASE_URL}/{endpoint}"
    # User-Agent 필수: 비-브라우저 UA로는 law.go.kr이 '부분 법령명' 검색을 검증실패/0건 처리한다
    # (예: query="지방세"→0). 또 동시요청이 많으면 간헐적으로 '사용자 검증 실패'(200 OK, 본문 오류)를
    # 반환하는데, 이를 캐시하면 이후 검색이 계속 0건이 되므로 캐시하지 말고 재시도한다.
    hdrs = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.law.go.kr/"}
    last_err = "알 수 없는 오류"
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, timeout=18, headers=hdrs)
            r.raise_for_status()
            try:
                r.encoding = r.apparent_encoding or r.encoding
            except Exception:
                pass
            text = r.text.strip()
            try:
                data: Any = r.json()
            except Exception:
                data = {"raw": text, "content_type": r.headers.get("content-type", "")}
            if isinstance(data, dict) and ("검증에 실패" in str(data.get("result", "")) or "검증을 위하여" in str(data.get("msg", ""))):
                last_err = str(data.get("result") or data.get("msg") or "사용자 검증 실패")
                time.sleep(0.4 * (attempt + 1))
                continue
            result = {
                "ok": True,
                "cached": False,
                "url": r.url.replace(str(oc), "***"),
                "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "data": data,
            }
            ck.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            return result
        except requests.RequestException as e:
            last_err = str(e)
            time.sleep(0.3 * (attempt + 1))
    return {"ok": False, "error": f"국가법령정보 API 호출 실패: {last_err}"}


def as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def find_key_recursive(obj: Any, key_candidates: Iterable[str]) -> Any:
    candidates = set(key_candidates)
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in candidates:
                return v
        for v in obj.values():
            found = find_key_recursive(v, candidates)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = find_key_recursive(item, candidates)
            if found is not None:
                return found
    return None


def find_all_by_key(obj: Any, key: str) -> List[Any]:
    found: List[Any] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key:
                found.extend(as_list(v))
            else:
                found.extend(find_all_by_key(v, key))
    elif isinstance(obj, list):
        for item in obj:
            found.extend(find_all_by_key(item, key))
    return found


def pick(d: Dict[str, Any], *keys: str, default: str = "") -> str:
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return str(v)
    return default


def normalize_date(s: str) -> str:
    s = str(s or "").strip()
    if re.fullmatch(r"\d{8}", s):
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return s


def normalize_law_name(s: str) -> str:
    return re.sub(r"\s+", "", str(s or "").replace("ㆍ", "·").strip())


def extract_id_from_detail_link(link: str) -> str:
    """상세링크 안의 ID/MST 값을 꺼냅니다.
    법제처 검색목록의 ID가 단순 순번으로 내려오는 경우가 있어 판례/자치법규에서 보정용으로 씁니다.
    """
    link = str(link or "")
    if not link:
        return ""
    try:
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(link).query)
        for k in ("MST", "mst", "ID", "id", "precSeq", "seq"):
            if qs.get(k) and qs[k][0]:
                return str(qs[k][0]).strip()
    except Exception:
        pass
    m = re.search(r"(?:MST|mst|ID|id|precSeq|seq)=([0-9A-Za-z_-]+)", link)
    return m.group(1).strip() if m else ""


def looks_like_row_number(value: str) -> bool:
    v = str(value or "").strip()
    return bool(re.fullmatch(r"\d{1,3}", v))


def patch_item_identifiers(item: Dict[str, Any], target: str) -> Dict[str, Any]:
    """판례/자치법규는 검색목록의 ID가 실제 상세조회 ID가 아닌 경우가 많아 보정합니다."""
    raw = item.get("raw") if isinstance(item.get("raw"), dict) else {}
    link = item.get("detail_link") or pick(raw, "판례상세링크", "자치법규상세링크", "법령상세링크", "상세링크", "링크")
    link_id = extract_id_from_detail_link(str(link or ""))

    if target == "prec":
        seq = pick(raw, "판례일련번호", "판례정보일련번호", "판례MST", "MST", "mst", "일련번호") or link_id
        if seq:
            item["mst"] = seq
            item["law_id"] = seq
        if link:
            item["detail_link"] = str(link)

    if api_target_of(target) == "ordin":
        seq = pick(raw, "자치법규일련번호", "자치법규MST", "MST", "mst", "일련번호") or link_id
        oid = pick(raw, "자치법규ID", "ID", "id")
        if seq and (not item.get("mst") or looks_like_row_number(item.get("mst", ""))):
            item["mst"] = seq
        if oid and (not item.get("law_id") or looks_like_row_number(item.get("law_id", ""))):
            item["law_id"] = oid
        if link:
            item["detail_link"] = str(link)

    # v20: 사례형/별표서식형은 목록의 id가 순번이고 실제 키는 각 일련번호 필드입니다.
    if target in CASE_TARGETS or target in BYL_TARGETS:
        seq = pick(
            raw,
            "행정심판재결례일련번호", "특별행정심판재결례일련번호", "헌재결정례일련번호",
            "법령해석일련번호", "법령해석례일련번호", "감사원사전컨설팅일련번호", "별표일련번호",
        ) or link_id
        if seq:
            if not item.get("mst") or looks_like_row_number(item.get("mst", "")):
                item["mst"] = seq
            if not item.get("law_id") or looks_like_row_number(item.get("law_id", "")):
                item["law_id"] = seq
        if not item.get("detail_link") and link:
            item["detail_link"] = str(link)
    return item


def pick_detail_link(item: Dict[str, Any]) -> str:
    """키 이름이 대상마다 달라서(예: 행정심판례상세링크, 별표법령상세링크 등)
    '상세링크'가 들어간 첫 번째 키 값을 보조로 사용합니다."""
    for k, v in item.items():
        if "상세링크" in str(k) and v not in (None, ""):
            return str(v)
    return ""


def normalize_search(data: Dict[str, Any]) -> Dict[str, Any]:
    root = data.get("LawSearch") or data.get("lawSearch") or data.get("Search") or data
    items = None
    for key in ("law", "Law", "laws", "법령", "admrul", "ordin", "prec", "expc",
                "Detc", "decc", "cgmExpc", "baiPvcs", "licbyl", "admrulbyl", "ordinbyl",
                "oldAndNew", "thdCmp", "lstrm", "result", "items", "item"):
        if isinstance(root, dict) and key in root:
            items = root[key]
            break
    if items is None:
        items = find_key_recursive(root, ["law", "admrul", "ordin", "prec", "expc",
                                          "Detc", "decc", "cgmExpc", "baiPvcs",
                                          "licbyl", "admrulbyl", "ordinbyl", "item"])

    normalized: List[Dict[str, Any]] = []
    for item in as_list(items):
        if not isinstance(item, dict):
            continue
        law_name = pick(item, "법령명한글", "법령명", "행정규칙명", "자치법규명", "판례명", "안건명", "사건명", "의견서명", "별표명", "title")
        # 별표서식(자치법규)의 별표명에는 검색어 강조 HTML 태그가 섞여 내려옵니다.
        # 태그를 공백이 아닌 빈 문자열로 지워 단어가 갈라지지 않게 합니다.
        if "<" in law_name:
            law_name = html.unescape(re.sub(r"<[^>]+>", "", law_name)).strip()
        # 별표서식은 어느 법령 소속인지 제목에 함께 표시합니다.
        byl_parent = pick(item, "관련법령명", "관련행정규칙명", "관련자치법규명")
        if pick(item, "별표명") and byl_parent:
            law_name = f"{law_name} ({byl_parent})"
        normalized.append({
            "raw": item,
            "name": law_name,
            "short_name": pick(item, "법령약칭명", "약칭", default=""),
            "law_id": pick(item, "법령ID", "자치법규ID", "판례일련번호", "판례정보일련번호", "행정규칙일련번호", "법령해석례일련번호",
                           "행정심판재결례일련번호", "특별행정심판재결례일련번호", "헌재결정례일련번호", "법령해석일련번호",
                           "감사원사전컨설팅일련번호", "별표일련번호", "ID", "id", "lawId"),
            "mst": pick(item, "법령일련번호", "MST", "mst", "일련번호", "행정규칙일련번호", "자치법규일련번호", "자치법규MST",
                        "판례일련번호", "판례정보일련번호", "법령해석례일련번호",
                        "행정심판재결례일련번호", "특별행정심판재결례일련번호", "헌재결정례일련번호", "법령해석일련번호",
                        "감사원사전컨설팅일련번호", "별표일련번호"),
            "type": pick(item, "법령구분명", "법종구분", "별표종류", "재결구분명", "사건종류명", "구분", "종류"),
            "department": pick(item, "소관부처명", "소관부처", "부서명", "재결청", "해석기관명", "신청기관명", "전체기관명", "지자체기관명", "기관명", "해석기관"),
            "promulgation_date": normalize_date(pick(item, "공포일자", "발령일자", "선고일자", "해석일자", "회신일자", "의결일자", "종국일자")),
            "promulgation_no": pick(item, "공포번호", "발령번호", "사건번호", "안건번호", "청구번호", "접수번호"),
            "effective_date": normalize_date(pick(item, "시행일자", "시행일", "자치법규시행일자")),
            "revision_type": pick(item, "제개정구분명", "제개정구분"),
            "detail_link": pick(item, "법령상세링크", "판례상세링크", "자치법규상세링크", "상세링크", "링크") or pick_detail_link(item),
            "summary": html_to_text(pick(item, "판례내용", "판결요지", "판시사항", "결정요지", "재결요지", "질의요지", "요지", "내용", "본문", "사건개요", "청구취지", "주문", "이유", "쟁점", default="")),
            "source_name": pick(item, "데이터출처명", "datSrcNm", "자료출처", "출처", default=""),
        })
    if isinstance(root, dict):
        total = pick(root, "totalCnt", "totalCount", "전체건수", default=str(len(normalized)))
        page = pick(root, "page", "현재페이지", default="1")
    else:
        total = str(len(normalized)); page = "1"
    return {"total": total, "page": page, "items": normalized}


def article_number_from_item(item: Dict[str, Any]) -> str:
    no = pick(item, "조문번호", "조번호")
    sub = pick(item, "조문가지번호", "조가지번호")
    if no:
        try:
            n = int(str(no))
            if sub and str(sub) not in ("0", "00"):
                return f"제{n}조의{int(str(sub))}"
            return f"제{n}조"
        except Exception:
            return f"제{no}조"
    return ""


def build_article_text(item: Any) -> str:
    lines: List[str] = []

    def walk(o: Any) -> None:
        if isinstance(o, dict):
            for key in ("조문내용", "조내용", "항내용", "호내용", "목내용", "본문", "내용"):
                v = o.get(key)
                if isinstance(v, str) and v.strip():
                    lines.append(re.sub(r"\s+", " ", v.strip()))
            for v in o.values():
                if isinstance(v, (dict, list)):
                    walk(v)
        elif isinstance(o, list):
            for x in o:
                walk(x)

    walk(item)
    seen = set(); unique = []
    for line in lines:
        if line not in seen:
            seen.add(line); unique.append(line)
    return "\n".join(unique)



def collect_segments(obj: Any, ctx: Dict[str, str], out: List[Dict[str, str]]) -> None:
    if isinstance(obj, dict):
        local = dict(ctx)
        if obj.get("조문번호"):
            local["article"] = article_number_from_item(obj)
        if obj.get("조문제목") or obj.get("조제목"):
            local["article_title"] = pick(obj, "조문제목", "조제목", "제목")
        if obj.get("항번호"):
            local["paragraph"] = pick(obj, "항번호", "항번", "항")
        if obj.get("호번호"):
            local["ho"] = pick(obj, "호번호", "호번", "호")
        if obj.get("목번호"):
            local["mok"] = pick(obj, "목번호", "목번", "목")
        for level, key in (("조", "조문내용"), ("조", "조내용"), ("항", "항내용"), ("호", "호내용"), ("목", "목내용")):
            val = obj.get(key)
            if isinstance(val, str) and val.strip():
                out.append({
                    "level": level,
                    "article": local.get("article", ""),
                    "article_title": local.get("article_title", ""),
                    "paragraph": local.get("paragraph", ""),
                    "ho": local.get("ho", ""),
                    "mok": local.get("mok", ""),
                    "text": re.sub(r"\s+", " ", val.strip()),
                })
        for v in obj.values():
            if isinstance(v, (dict, list)):
                collect_segments(v, local, out)
    elif isinstance(obj, list):
        for x in obj:
            collect_segments(x, ctx, out)


def html_to_text(raw_html: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", str(raw_html or ""))
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|li|tr|h[1-6]|section|article)>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_text_sections(text: str, max_len: int = 900) -> List[str]:
    lines = [ln.strip() for ln in str(text or "").splitlines() if ln.strip()]
    chunks: List[str] = []
    buf = ""
    for line in lines:
        if buf and len(buf) + len(line) > max_len:
            chunks.append(buf.strip())
            buf = line
        else:
            buf = (buf + "\n" + line).strip() if buf else line
    if buf:
        chunks.append(buf.strip())
    return chunks or ([text.strip()] if str(text or "").strip() else [])



def absolutize_law_url(url: str) -> str:
    """법제처 HTML 안의 상대경로를 브라우저에서 열 수 있는 절대경로로 바꿉니다."""
    url = html.unescape(str(url or "").strip())
    if not url:
        return ""
    if url.startswith("http://") or url.startswith("https://"):
        return url
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return "https://www.law.go.kr" + url
    return "https://www.law.go.kr/" + url.lstrip("./")


def extract_first_iframe_src(raw_html: str) -> str:
    """판례 HTML은 본문 대신 iframe만 내려오는 경우가 있어 iframe src를 따로 추출합니다.

    v20 수정: 법제처 응답이 src = "..." 처럼 등호 주변에 공백을 넣는 경우가 있어
    공백 허용으로 바꾸고, iframe이 없으면 hidden input(id="url")의 원문 뷰어 주소를
    보조로 사용합니다. (국세법령정보시스템 출처 판례가 이 형태)"""
    raw = str(raw_html or "")
    m = re.search(r"<iframe[^>]+src\s*=\s*[\"']([^\"']+)[\"']", raw, re.I | re.S)
    if not m:
        m = re.search(r"id\s*=\s*[\"']url[\"'][^>]*value\s*=\s*[\"']([^\"']+)[\"']", raw, re.I | re.S)
    if not m:
        return ""
    return absolutize_law_url(m.group(1))


def normalize_prec_html_detail(raw_html: str, law_id: str = "", mst: str = "", law_name: str = "") -> Dict[str, Any]:
    """판례 HTML 전용 정규화.

    국세청·조세 계열 판례는 lawService HTML 응답이 실제 본문 텍스트가 아니라 iframe 껍데기인
    경우가 많으므로, 텍스트 추출에 실패해도 iframe을 본문창에 직접 표시할 수 있게 보관합니다.
    """
    raw = str(raw_html or "")
    text = html_to_text(raw)
    iframe_src = extract_first_iframe_src(raw)
    title = law_name or ""
    m = re.search(r"<title[^>]*>(.*?)</title>", raw, re.I | re.S)
    if m:
        got = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", m.group(1)))).strip()
        if got and not any(b in got for b in ("Error", "XML", "오류")):
            title = title or got
    if not title:
        for line in text.splitlines()[:12]:
            if line.strip() and "iframe" not in line.lower():
                title = line.strip()[:120]
                break
    title = title or "판례"
    body = text.strip()
    if not body and iframe_src:
        body = "판례 원문 HTML을 iframe으로 표시합니다."
    split_sections = split_prec_inline_labeled_text(body)
    if split_sections:
        articles = []
        for label, txt in split_sections:
            seg = {"level": "판례", "article": label, "article_title": title, "paragraph": "", "ho": "", "mok": "", "text": txt}
            articles.append({"number": label, "jo": "", "title": label, "effective_date": "", "changed": "", "body": txt, "segments": [seg], "raw": {label: txt}})
        segments = [seg for a in articles for seg in a.get("segments", [])]
    else:
        seg = {"level": "판례", "article": "판례", "article_title": title, "paragraph": "", "ho": "", "mok": "", "text": body}
        articles = [{"number": "판례", "jo": "", "title": title, "effective_date": "", "changed": "", "body": body, "segments": [seg], "raw": {"본문": body}}]
        segments = [seg]
    normalized = {
        "metadata": {"law_name": title, "law_id": law_id, "mst": mst, "department": "", "effective_date": "", "promulgation_date": "", "revision_type": ""},
        "articles": articles,
        "segments": segments,
        "addenda_count": 0,
        "annexes": [],
        "raw": {"html_text": text, "html_raw": raw, "iframe_src": iframe_src},
        "render_type": "prec_html_frame" if iframe_src else "prec_html_text",
    }
    return add_prec_missing_order_notice(add_prec_original_url(normalized, mst or law_id, title))


def _compact_for_compare(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", str(text or ""), flags=re.UNICODE)


def is_meaningful_prec_detail(normalized: Dict[str, Any], law_name: str = "") -> bool:
    """판례 HTML이 제목/요약만 반복되는 경우를 걸러냅니다.

    lawService.do?target=prec&type=HTML 은 정상 응답이어도 일부 자료에서
    제목 또는 검색결과 요약 수준의 텍스트만 내려오는 경우가 있습니다. 이때 바로
    본문으로 확정하지 않고 JSON/XML 보조 조회를 시도하기 위한 판별 함수입니다.
    """
    raw = normalized.get("raw", {}) if isinstance(normalized, dict) else {}
    text = str(raw.get("html_text") or "")
    html_raw = str(raw.get("html_raw") or "")
    iframe_src = str(raw.get("iframe_src") or "")
    if iframe_src:
        return True
    probe = text + "\n" + html_raw[:2000]
    bad_words = ("일치하는 판례가 없습니다", "XML 파싱중 오류", "사용자 정보 검증에 실패", "Error")
    if any(b in probe for b in bad_words):
        return False
    compact = _compact_for_compare(text)
    title_compact = _compact_for_compare(law_name)
    if title_compact:
        compact_without_title = compact.replace(title_compact, "")
    else:
        compact_without_title = compact
    # 판례 본문으로 볼 수 있는 전형적 표지어들입니다. 국세청/조세심판 자료까지 포함합니다.
    markers = (
        "판시사항", "판결요지", "판례내용", "참조조문", "참조판례", "주문", "이유", "원고", "피고",
        "처분개요", "청구주장", "처분청", "판단", "심리및판단", "결정요지", "세목", "판결유형", "사건번호",
        "직전소송사건번호", "제1심", "항소", "상고", "청구인", "피청구인"
    )
    if any(m in text for m in markers):
        return True
    # 제목을 제외하고도 충분한 문장이 남아야 본문으로 인정합니다.
    if len(compact_without_title) >= 180:
        return True
    if len(compact) >= 700:
        return True
    return False


def has_meaningful_prec_json(normalized: Dict[str, Any]) -> bool:
    if not isinstance(normalized, dict):
        return False
    arts = normalized.get("articles") or []
    # v20 수정: '주문 항목 없음' 안내 카드는 앱이 덧붙인 문구라 본문 판정에서 제외합니다.
    # (안내문에 '주문'·'이유' 표지어가 들어 있어 오류 응답까지 본문으로 오인하던 버그)
    text = "\n".join(
        str(a.get("body", ""))
        for a in arts
        if isinstance(a, dict) and str(a.get("number") or "") != "주문 항목 없음"
    )
    if "일치하는 판례가 없습니다" in text:
        return False
    compact = _compact_for_compare(text)
    # 사건명/사건번호만 내려온 경우는 제외하고, 실제 내용성 있는 경우만 인정합니다.
    return len(compact) >= 80 and any(k in text for k in ("판례내용", "판시사항", "판결요지", "주문", "이유", "요지", "처분", "판단", "원고", "피고", "세목", "사건번호"))

def normalize_html_detail(raw_html: str, target: str, law_id: str = "", mst: str = "") -> Dict[str, Any]:
    text = html_to_text(raw_html)
    title = ""
    m = re.search(r"<title[^>]*>(.*?)</title>", str(raw_html or ""), re.I | re.S)
    if m:
        title = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", m.group(1)))).strip()
    if not title:
        for line in text.splitlines()[:8]:
            if line.strip():
                title = line.strip()[:80]
                break
    label = "판례" if api_target_of(target) == "prec" else TARGETS.get(target, target)
    articles: List[Dict[str, Any]] = []
    for idx, chunk in enumerate(split_text_sections(text), start=1):
        number = label if idx == 1 else f"{label} {idx}"
        seg = {"level": label, "article": number, "article_title": title if idx == 1 else "", "paragraph": "", "ho": "", "mok": "", "text": chunk}
        articles.append({
            "number": number,
            "jo": "",
            "title": title if idx == 1 else "",
            "effective_date": "",
            "changed": "",
            "body": chunk,
            "segments": [seg],
            "raw": {"본문": chunk},
        })
    segments = [seg for a in articles for seg in a.get("segments", [])]
    return {
        "metadata": {"law_name": title, "law_id": law_id, "mst": mst, "department": "", "effective_date": "", "promulgation_date": "", "revision_type": ""},
        "articles": articles,
        "segments": segments,
        "addenda_count": 0,
        "annexes": [],
        "raw": {"html_text": text},
        "render_type": "html_text",
    }




PREC_INLINE_LABELS = (
    "심급", "세목", "주문", "이유", "판시사항", "판결요지", "결정요지", "요지",
    "참조조문", "참조판례", "처분개요", "청구주장", "처분청의견", "심리및판단",
    "심리 및 판단", "판단", "사실관계", "쟁점", "관련법령", "결론",
    # v20: 헌재 전문 등은 [주 문]/[이 유]처럼 글자 사이 공백이 들어간 표지를 씁니다.
    "주 문", "이 유", "결 론", "사건개요", "청구취지", "심판대상조문"
)


def split_prec_inline_labeled_text(text: str) -> List[Tuple[str, str]]:
    """판례내용 한 필드 안에 들어 있는 [주문]·[이유] 등을 별도 섹션으로 분리합니다.

    법제처 판례 본문 API의 response field는 주문/이유를 별도 필드로 항상 주는 구조가 아니라
    `판례내용` 한 항목 안에 `[주문] ... [이유] ...` 식으로 섞어 주는 경우가 많습니다.
    대시보드에서는 이 내부 표지를 읽어 사용자가 주문/이유를 따로 확인할 수 있게 쪼갭니다.
    """
    clean = html_to_text(str(text or ""))
    clean = re.sub(r"\s+", " ", clean).strip()
    if not clean:
        return []
    labels = sorted(PREC_INLINE_LABELS, key=len, reverse=True)
    label_pat = "|".join(re.escape(x) for x in labels)
    # [주문], 【주문】, <주문>, 주문: 형태를 모두 허용합니다.
    pat = re.compile(rf"(?:[\[【<]\s*({label_pat})\s*[\]】>]|\b({label_pat})\s*[:：])")
    matches = list(pat.finditer(clean))
    if not matches:
        return []
    sections: List[Tuple[str, str]] = []
    prefix = clean[:matches[0].start()].strip(" -·;；,，")
    if prefix:
        sections.append(("판례내용 앞부분", prefix))
    for idx, m in enumerate(matches):
        label = (m.group(1) or m.group(2) or "").strip()
        start = m.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(clean)
        body = clean[start:end].strip(" -·;；,，")
        if body:
            sections.append((label, body))
    # 같은 라벨이 여러 번 나올 때 구분합니다.
    counts: Dict[str, int] = {}
    out: List[Tuple[str, str]] = []
    for label, body in sections:
        counts[label] = counts.get(label, 0) + 1
        shown = label if counts[label] == 1 else f"{label} {counts[label]}"
        out.append((shown, body))
    return out


def append_prec_section(chunks: List[Tuple[str, str]], label: str, value: Any, *, split_inline: bool = False) -> None:
    txt = html_to_text(str(value or ""))
    txt = re.sub(r"\s+", " ", txt).strip()
    if not txt:
        return
    if split_inline:
        split = split_prec_inline_labeled_text(txt)
        if split:
            # 원래 필드명은 요약표지로 남기지 않고 내부 [주문]/[이유] 섹션을 우선 표시합니다.
            chunks.extend(split)
            return
    chunks.append((label, txt))


def prec_has_order_section(normalized: Dict[str, Any]) -> bool:
    """정규화된 판례 본문 안에 주문 섹션이 실제로 있는지 확인합니다."""
    articles = normalized.get("articles", []) if isinstance(normalized, dict) else []
    for article in articles or []:
        title = str(article.get("title") or article.get("number") or "").strip()
        title_compact = re.sub(r"\s+", "", title)
        if title_compact.startswith("주문"):
            return True
        body = str(article.get("body") or "")
        # 아직 분리되지 않은 원문 카드에 [주문]·주문: 표지가 남아 있는 경우도 주문 존재로 봅니다.
        if re.search(r"(?:[\[【<]\s*주문\s*[\]】>]|\b주문\s*[:：])", body):
            return True
    return False


def add_prec_missing_order_notice(normalized: Dict[str, Any]) -> Dict[str, Any]:
    """판례 API 제공 본문에 주문 항목이 없으면 안내 카드를 추가합니다.

    법제처 판례 자료는 자료원별로 `주문`이 별도 필드로 내려오지 않거나,
    `판례내용` 안에도 [주문] 표지가 없는 경우가 있습니다. 이런 항목은 앱 오류로
    보이지 않도록 별도 안내를 표시합니다.
    """
    if not isinstance(normalized, dict):
        return normalized
    render_type = str(normalized.get("render_type") or "")
    if not render_type.startswith("prec"):
        return normalized
    # iframe 원문은 브라우저가 법제처 원문을 직접 보여주는 형태라 내부 섹션 유무를 앱에서 단정하지 않습니다.
    if render_type == "prec_html_frame":
        return normalized
    articles = normalized.setdefault("articles", [])
    if not articles or prec_has_order_section(normalized):
        return normalized
    if any("주문 항목 없음" in str(a.get("title") or a.get("body") or "") for a in articles):
        return normalized
    title = str(normalized.get("metadata", {}).get("law_name") or "판례")
    text = (
        "API 제공 본문에 주문 항목 없음. "
        "이 판례는 법제처 API가 주문을 별도 항목으로 제공하지 않거나, "
        "제공 본문에 [주문] 표지가 포함되어 있지 않은 항목입니다. "
        "필요한 경우 상단의 [판례 원문] 또는 [API HTML]을 확인해 주세요."
    )
    seg = {"level": "안내", "article": "주문 항목 없음", "article_title": title, "paragraph": "", "ho": "", "mok": "", "text": text}
    notice = {"number": "주문 항목 없음", "jo": "", "title": "주문 항목 없음", "effective_date": "", "changed": "", "body": text, "segments": [seg], "raw": {"안내": text}}
    articles.append(notice)
    normalized["segments"] = [seg for a in articles for seg in a.get("segments", [])]
    raw = normalized.setdefault("raw", {})
    if isinstance(raw, dict):
        raw["missing_order_notice"] = True
    return normalized


def add_prec_original_url(normalized: Dict[str, Any], detail_id: str = "", law_name: str = "") -> Dict[str, Any]:
    raw = normalized.setdefault("raw", {}) if isinstance(normalized, dict) else {}
    if not isinstance(raw, dict):
        return normalized
    did = str(detail_id or normalized.get("metadata", {}).get("mst") or normalized.get("metadata", {}).get("law_id") or "").strip()
    if did:
        raw.setdefault("prec_info_url", f"https://www.law.go.kr/LSW/precInfoP.do?precSeq={did}")
        raw.setdefault("prec_service_html_url", f"https://www.law.go.kr/DRF/lawService.do?OC={get_oc()}&target=prec&ID={did}&type=HTML")
    if law_name:
        raw.setdefault("prec_search_url", "https://www.law.go.kr/LSW/precSc.do?menuId=1&subMenuId=15&query=" + urlencode({"": law_name})[1:])
    return normalized

def normalize_prec_json_detail(data: Dict[str, Any], law_id: str = "", mst: str = "") -> Dict[str, Any]:
    """판례 JSON 응답을 사건명/판시사항/판결요지/주문/이유 등 섹션으로 표시합니다."""
    root = data.get("PrecService") or data.get("precService") or data.get("판례") or data
    if not isinstance(root, dict):
        root = {}
    title = pick(root, "판례명", "사건명", "title") or pick(root, "사건번호", default="판례")
    section_keys = [
        ("사건명", "사건명"), ("사건번호", "사건번호"), ("선고일자", "선고일자"), ("법원명", "법원"),
        ("데이터출처명", "데이터출처"), ("세목", "세목"), ("판결유형", "판결유형"),
        ("판시사항", "판시사항"), ("판결요지", "판결요지"), ("결정요지", "결정요지"), ("요지", "요지"),
        ("참조조문", "참조조문"), ("참조판례", "참조판례"),
        ("판례내용", "판례내용"), ("전문", "전문"), ("주문", "주문"), ("이유", "이유"), ("내용", "내용"), ("본문", "본문"),
    ]
    chunks: List[Tuple[str, str]] = []
    for key, label in section_keys:
        val = root.get(key)
        if val not in (None, ""):
            append_prec_section(chunks, label, val, split_inline=(key in ("판례내용", "전문", "내용", "본문")))
    # API/자료원별로 필드명이 조금씩 달라서, 명시 키 외에도 내용성 있는 필드는 보조로 표시합니다.
    used_keys = {k for k, _ in section_keys}
    for key, val in list(root.items()):
        if key in used_keys or val in (None, ""):
            continue
        if isinstance(val, (dict, list)):
            continue
        key_s = str(key)
        if any(token in key_s for token in ("내용", "요지", "사유", "판단", "주장", "주문", "이유")):
            append_prec_section(chunks, key_s, val, split_inline=True)
    if not chunks:
        raw = json.dumps(root, ensure_ascii=False, indent=2)
        if raw.strip() and raw.strip() != "{}":
            chunks.append(("판례", raw))
    articles: List[Dict[str, Any]] = []
    for idx, (label, txt) in enumerate(chunks, start=1):
        number = label
        seg = {"level": "판례", "article": number, "article_title": title, "paragraph": "", "ho": "", "mok": "", "text": txt}
        articles.append({"number": number, "jo": "", "title": label, "effective_date": "", "changed": "", "body": txt, "segments": [seg], "raw": {label: txt}})
    segments = [seg for a in articles for seg in a.get("segments", [])]
    normalized = {
        "metadata": {"law_name": title, "law_id": law_id, "mst": mst, "department": "", "effective_date": "", "promulgation_date": normalize_date(pick(root, "선고일자")), "revision_type": ""},
        "articles": articles,
        "segments": segments,
        "addenda_count": 0,
        "annexes": [],
        "raw": root,
        "render_type": "prec_json",
    }
    return add_prec_missing_order_notice(add_prec_original_url(normalized, mst or law_id, title))


# v20: 사례형(법령해석례·행정심판례·헌재결정례·1차해석·조세심판원·사전컨설팅) 공용 섹션 정규화.
# lawService JSON 응답의 루트 키가 대상마다 다릅니다(실측: ExpcService, PrecService(행정심판례),
# DetcService, CgmExpcService, SpecialDeccService, BaiPvcsService).
CASE_SERVICE_ROOT_KEYS = (
    "ExpcService", "DetcService", "CgmExpcService", "SpecialDeccService",
    "BaiPvcsService", "DeccService", "PrecService",
)

CASE_META_KEYS = [
    ("사건명", "사건명"), ("안건명", "안건명"), ("의견서명", "의견서명"),
    ("사건번호", "사건번호"), ("청구번호", "청구번호"), ("안건번호", "안건번호"), ("접수번호", "접수번호"),
    ("재결청", "재결청"), ("처분청", "처분청"), ("법원명", "법원"),
    ("해석기관명", "해석기관"), ("질의기관명", "질의기관"), ("신청기관명", "신청기관"),
    ("의결일자", "의결일자"), ("종국일자", "종국일자"), ("해석일자", "해석일자"),
    ("회신일자", "회신일자"), ("선고일자", "선고일자"), ("재결일자", "재결일자"),
    ("사건종류명", "사건종류"), ("재결구분명", "재결구분"), ("재결례유형명", "재결례유형"),
]

CASE_BODY_KEYS = [
    ("질의요지", "질의요지"), ("회답", "회답"), ("개요", "개요"), ("사건개요", "사건개요"),
    ("청구취지", "청구취지"), ("주문", "주문"), ("판시사항", "판시사항"), ("판결요지", "판결요지"),
    ("결정요지", "결정요지"), ("재결요지", "재결요지"), ("요지", "요지"),
    ("판단기준", "판단기준"), ("종합의견", "종합의견"), ("검토결과", "검토결과"),
    ("이유", "이유"), ("전문", "전문"), ("판례내용", "판례내용"), ("내용", "내용"), ("본문", "본문"),
    ("관련법령", "관련법령"), ("참조조문", "참조조문"), ("참조판례", "참조판례"), ("참조결정", "참조결정"),
]


def _clean_case_text(value: Any) -> str:
    # 감사원 사전컨설팅 본문에는 [[[MEMO]]] 같은 내부 마커가 섞여 내려옵니다.
    txt = str(value or "").replace("[[[MEMO]]]", "\n")
    txt = html_to_text(txt)
    return txt.strip()


def normalize_case_json_detail(data: Dict[str, Any], target: str, law_id: str = "", mst: str = "") -> Dict[str, Any]:
    """사례형 JSON 응답을 질의요지/이유/재결요지 등 섹션 카드로 정규화합니다."""
    root: Any = None
    for key in CASE_SERVICE_ROOT_KEYS:
        if isinstance(data, dict) and isinstance(data.get(key), dict):
            root = data[key]
            break
    if root is None and isinstance(data, dict):
        # 루트 키를 모르는 경우: 단일 dict 값이 있으면 그것을 본문으로 봅니다.
        dict_values = [v for v in data.values() if isinstance(v, dict)]
        root = dict_values[0] if len(dict_values) == 1 else data
    if not isinstance(root, dict):
        root = {}

    label = TARGETS.get(target, target)
    title = pick(root, "사건명", "안건명", "의견서명", "판례명", "title") or pick(root, "사건번호", "청구번호", "안건번호", default=label)

    chunks: List[Tuple[str, str]] = []
    seen_sig = set()

    def push(shown_label: str, value: Any, split_inline: bool = False) -> None:
        txt = _clean_case_text(value)
        txt = re.sub(r"[ \t]+", " ", txt).strip()
        if not txt:
            return
        candidates: List[Tuple[str, str]] = []
        if split_inline:
            split = split_prec_inline_labeled_text(txt)
            if split:
                candidates = split
        if not candidates:
            candidates = [(shown_label, txt)]
        for lab, body in candidates:
            sig = re.sub(r"\s+", "", lab + body)[:300]
            if sig in seen_sig:
                continue
            seen_sig.add(sig)
            chunks.append((lab, body))

    meta_lines = []
    for key, lab in CASE_META_KEYS:
        val = _clean_case_text(root.get(key))
        if val:
            meta_lines.append(f"{lab}: {val}")
    if meta_lines:
        chunks.append(("개요 정보", "\n".join(meta_lines)))
        seen_sig.add(re.sub(r"\s+", "", "개요 정보" + "\n".join(meta_lines))[:300])

    for key, lab in CASE_BODY_KEYS:
        push(lab, root.get(key), split_inline=(key in ("전문", "판례내용", "내용", "본문")))

    # 명시 키 외에도 내용성 있는 문자열 필드는 보조로 표시합니다.
    used = {k for k, _ in CASE_META_KEYS} | {k for k, _ in CASE_BODY_KEYS}
    for key, val in list(root.items()):
        if key in used or isinstance(val, (dict, list)) or val in (None, ""):
            continue
        key_s = str(key)
        # 일련번호·코드·링크류 메타 필드는 본문으로 잡지 않습니다.
        if any(bad in key_s for bad in ("일련번호", "코드", "링크", "기준일시", "번호")):
            continue
        if re.fullmatch(r"[\d.\-/\s]*", str(val or "")):
            continue
        if any(tok in key_s for tok in ("내용", "요지", "사유", "판단", "주장", "의견", "회신", "질의", "개요", "이유", "결과")):
            push(key_s, val, split_inline=True)

    if not chunks:
        raw_dump = json.dumps(root, ensure_ascii=False, indent=2)
        if raw_dump.strip() and raw_dump.strip() != "{}":
            chunks.append((label, raw_dump))

    articles: List[Dict[str, Any]] = []
    for lab, txt in chunks:
        seg = {"level": label, "article": lab, "article_title": title, "paragraph": "", "ho": "", "mok": "", "text": txt}
        articles.append({"number": lab, "jo": "", "title": lab, "effective_date": "", "changed": "", "body": txt, "segments": [seg], "raw": {lab: txt}})
    segments = [seg for a in articles for seg in a.get("segments", [])]
    return {
        "metadata": {
            "law_name": title,
            "law_id": law_id,
            "mst": mst,
            "department": pick(root, "재결청", "해석기관명", "법원명", "신청기관명"),
            "effective_date": "",
            "promulgation_date": normalize_date(pick(root, "의결일자", "종국일자", "해석일자", "회신일자", "선고일자")),
            "revision_type": "",
        },
        "articles": articles,
        "segments": segments,
        "addenda_count": 0,
        "annexes": [],
        "raw": root,
        "render_type": "case_json",
    }


def has_meaningful_case_json(normalized: Dict[str, Any]) -> bool:
    if not isinstance(normalized, dict):
        return False
    arts = normalized.get("articles") or []
    body = "\n".join(str(a.get("body", "")) for a in arts if isinstance(a, dict) and str(a.get("number")) != "개요 정보")
    return len(_compact_for_compare(body)) >= 60


def normalize_detail(data: Dict[str, Any]) -> Dict[str, Any]:
    root = data.get("법령") or data.get("Law") or data.get("law") or data
    metadata = {
        "law_name": pick(root if isinstance(root, dict) else {}, "법령명_한글", "한글법령명", "법령명", "자치법규명") or str(find_key_recursive(root, ("법령명_한글", "법령명한글", "한글법령명", "법령명", "자치법규명")) or ""),
        "law_id": pick(root if isinstance(root, dict) else {}, "법령ID", "자치법규ID", "ID"),
        "mst": pick(root if isinstance(root, dict) else {}, "법령일련번호", "자치법규일련번호", "자치법규MST", "MST"),
        "department": pick(root if isinstance(root, dict) else {}, "소관부처", "소관부처명", "부서명"),
        "effective_date": normalize_date(pick(root if isinstance(root, dict) else {}, "시행일자", "시행일")),
        "promulgation_date": normalize_date(pick(root if isinstance(root, dict) else {}, "공포일자", "발령일자")),
        "revision_type": pick(root if isinstance(root, dict) else {}, "제개정구분", "제개정구분명"),
    }

    article_units = find_all_by_key(root, "조문단위")
    if not article_units and isinstance(root, dict):
        article_units = find_all_by_key(root, "조문")

    articles: List[Dict[str, Any]] = []
    for unit in article_units:
        if not isinstance(unit, dict):
            continue
        # v20: 조문여부=전문은 편/장/절 제목(예 " 제1장 총칙")이라 조문번호를 매기면 안 됩니다.
        if pick(unit, "조문여부") == "전문":
            cont = re.sub(r"\s+", " ", build_article_text(unit) or pick(unit, "조문내용") or "").strip()
            if not cont:
                continue
            if re.search(r"제\s*\d+\s*절", cont):
                kind = "section"
            elif re.search(r"제\s*\d+\s*(편|장|관)", cont):
                kind = "chapter"
            else:
                kind = "header"
            articles.append({"number": "", "jo": "", "title": cont, "is_header": True, "kind": kind,
                             "effective_date": "", "changed": "", "body": "", "segments": [], "raw": unit})
            continue
        jo_raw = pick(unit, "조문번호", "조번호")
        gaji_raw = pick(unit, "조문가지번호", "조가지번호")
        try:
            jo_code = f"{int(jo_raw):04d}{int(gaji_raw or 0):02d}" if jo_raw else ""
        except Exception:
            jo_code = str(jo_raw or "")
        title = pick(unit, "조문제목", "조제목", "제목")
        number = article_number_from_item(unit)
        body = build_article_text(unit)
        segments: List[Dict[str, str]] = []
        collect_segments(unit, {"article": number, "article_title": title}, segments)
        if not segments and body:
            segments = [{"level": "조", "article": number, "article_title": title, "paragraph": "", "ho": "", "mok": "", "text": body}]
        articles.append({
            "number": number,
            "jo": jo_code,
            "title": title,
            "effective_date": normalize_date(pick(unit, "조문시행일자", "조문시행일자문자열")),
            "changed": pick(unit, "조문변경여부"),
            "body": body,
            "segments": segments,
            "raw": unit,
        })

    addenda = find_all_by_key(root, "부칙단위")
    annexes = find_all_by_key(root, "별표단위")
    annex_list: List[Dict[str, str]] = []
    for a in annexes:
        if isinstance(a, dict):
            annex_list.append({
                "title": pick(a, "별표제목", "별표제목문자열", "별표첨부파일명", "제목"),
                "hwp": pick(a, "별표서식파일링크", "별표HWP파일링크", "별표파일링크", "별표서식파일명", "별표HWP파일명", "별표파일명", "hwp"),
                "pdf": pick(a, "별표서식PDF파일링크", "별표PDF파일링크", "별표서식PDF파일명", "별표PDF파일명", "pdf"),
                "body": pick(a, "별표내용"),
                "file_name": pick(a, "별표첨부파일명", "파일명"),
            })
    all_segments: List[Dict[str, str]] = []
    for a in articles:
        all_segments.extend(a.get("segments", []))
    return {"metadata": metadata, "articles": articles, "segments": all_segments, "addenda_count": len(addenda), "annexes": annex_list, "raw": root}


def _admrul_flat_text(v: Any) -> str:
    """행정규칙의 조문내용·별표내용은 문자열/리스트/중첩리스트가 섞여 내려옵니다.
    줄 단위로 평탄화해 하나의 본문 텍스트로 만듭니다."""
    if isinstance(v, (list, tuple)):
        return "\n".join(_admrul_flat_text(x) for x in v if x not in (None, ""))
    return str(v or "").rstrip()


_HANG_BREAK_RE = re.compile(r"[ \t]*(?=[①-⑳㉑-㉟㊱-㊿])")


def _admrul_hang_break(text: str) -> str:
    """행정규칙 조문은 항(①②…)이 한 줄에 붙어 내려오므로,
    항 기호 앞에서 줄을 바꿔 읽기 쉽게 만듭니다(첫 항 포함)."""
    out = _HANG_BREAK_RE.sub("\n", text)
    return re.sub(r"\n{2,}", "\n", out).strip()


def normalize_admrul_detail(data: Dict[str, Any]) -> Dict[str, Any]:
    """행정규칙(훈령·예규) 상세 JSON 정규화.
    AdmRulService에는 법령의 조문단위가 없고 '조문내용' 문자열 목록과
    별표단위만 내려오므로, 제n조 표제 기준으로 articles를 만들고
    별표는 level='별표' 세그먼트(리더에서 고정폭 글꼴 표시)로 붙입니다."""
    root = data.get("AdmRulService") if isinstance(data.get("AdmRulService"), dict) else data
    if not isinstance(root, dict):
        root = {}
    basic = root.get("행정규칙기본정보") if isinstance(root.get("행정규칙기본정보"), dict) else {}
    metadata = {
        "law_name": pick(basic, "행정규칙명", "행정규칙명한글"),
        "effective_date": normalize_date(pick(basic, "시행일자", "발령일자")),
        "revision_type": pick(basic, "제개정구분명", "제개정구분", "행정규칙종류"),
        "department": pick(basic, "소관부처명", "담당부서기관명", "발령기관명"),
    }

    articles: List[Dict[str, Any]] = []

    def _push_header(title: str) -> None:
        articles.append({"number": "", "jo": "", "title": title, "effective_date": "",
                         "changed": "", "body": "", "segments": [], "is_header": True})

    def _push_article(number: str, title: str, text: str, level: str = "조") -> None:
        articles.append({
            "number": number, "jo": "", "title": title, "effective_date": "", "changed": "",
            "body": text,
            "segments": [{"level": level, "article": number, "paragraph": "", "ho": "", "mok": "", "text": text}],
        })

    jo_items = root.get("조문내용")
    if isinstance(jo_items, str):
        jo_items = [jo_items]
    art_re = re.compile(r"^\s*(제\d+조(?:의\d+)?)\s*(?:\(([^)]*)\))?")
    hdr_re = re.compile(r"^\s*제\d+(?:장|절|관|편)\b")
    for item in (jo_items or []):
        text = _admrul_flat_text(item).strip()
        if not text:
            continue
        m = art_re.match(text)
        if m:
            _push_article(m.group(1), m.group(2) or "", _admrul_hang_break(text))
        elif hdr_re.match(text) and len(text) < 60:
            _push_header(text)
        elif articles and not articles[-1].get("is_header"):
            # 조문 표제 없이 이어지는 줄은 직전 조문에 붙입니다.
            articles[-1]["body"] += "\n" + _admrul_hang_break(text)
            if articles[-1]["segments"]:
                articles[-1]["segments"][0]["text"] = articles[-1]["body"]
        else:
            _push_header(text)

    # 부칙: 여러 건이면 건별로 나눠 붙입니다.
    buchick = root.get("부칙")
    if isinstance(buchick, dict):
        bodies = buchick.get("부칙내용")
        if isinstance(bodies, str):
            bodies = [bodies]
        for b in (bodies or []):
            text = _admrul_flat_text(b).strip()
            if text:
                _push_article("부칙", "", _admrul_hang_break(text))

    # 별표: 본문 아래에 별표 단위로 붙입니다.
    annex_list: List[Dict[str, str]] = []
    annexes = find_all_by_key(root, "별표단위")
    if annexes:
        _push_header("별  표")
    for a in annexes:
        if not isinstance(a, dict):
            continue
        no_raw = re.sub(r"\D", "", pick(a, "별표번호")) or "0"
        gaji = re.sub(r"\D", "", pick(a, "별표가지번호")) or "0"
        label = "별표 " + str(int(no_raw)) + ("의" + str(int(gaji)) if int(gaji) else "")
        title = pick(a, "별표제목", "별표제목문자열", "별표첨부파일명", "제목")
        text = _admrul_flat_text(a.get("별표내용")).strip()
        # 법제처 변환 단계에서 깨진 특수문자 보정: '??'는 도장 자리, 한글 사이 '?'는 가운뎃점으로 추정 표시
        text = text.replace("??", "㊞")
        text = re.sub(r"(?<=[가-힣])\?(?=[가-힣])", "ㆍ", text)
        pdf = pick(a, "별표서식PDF파일링크", "별표PDF파일링크")
        hwp = pick(a, "별표서식파일링크", "별표HWP파일링크", "별표파일링크")
        if pdf.startswith("/"):
            pdf = "https://www.law.go.kr" + pdf
        if hwp.startswith("/"):
            hwp = "https://www.law.go.kr" + hwp
        _push_article("[" + label + "]", title, text or "(별표 본문 없음 — 서식 파일 참조)", level="별표")
        # 서식 원본(법제처 PDF/HWP) 링크 — 리더에서 버튼으로 표시합니다.
        articles[-1]["annex_pdf"] = pdf
        articles[-1]["annex_hwp"] = hwp
        annex_list.append({
            "title": title,
            "hwp": hwp,
            "pdf": pdf,
            "body": "",
            "file_name": pick(a, "별표첨부파일명", "파일명"),
        })

    all_segments2: List[Dict[str, str]] = []
    for a in articles:
        all_segments2.extend(a.get("segments", []))
    return {"metadata": metadata, "articles": articles, "segments": all_segments2,
            "addenda_count": 0, "annexes": annex_list, "raw": root}


def split_terms(query: str) -> List[str]:
    # 공백은 OR 검색 기준입니다. 따옴표 구문까지는 지원하지 않고, 입력 토큰을 그대로 완전일치 단어로 봅니다.
    return [t for t in re.split(r"\s+", str(query or "").strip()) if t]


def _term_pattern(term: str) -> re.Pattern[str]:
    # 한글/영문/숫자 안쪽 부분문자열은 제외합니다.
    # 예: 자동차 -> 자동차세 불일치, 자동차 과세 -> '자동차' 단어가 따로 있으면 일치
    escaped = re.escape(str(term or "").strip())
    return re.compile(rf"(?<![0-9A-Za-z가-힣_]){escaped}(?![0-9A-Za-z가-힣_])", re.IGNORECASE)


def contains_any_exact_term(text: str, terms: List[str]) -> bool:
    if not terms:
        return True
    text = re.sub(r"\s+", " ", str(text or ""))
    return any(_term_pattern(term).search(text) for term in terms if term)


def contains_terms(text: str, terms: List[str]) -> bool:
    # 기존 이름은 유지하되, 본문검색 기준은 '공백 OR + 완전일치 단어'로 변경합니다.
    return contains_any_exact_term(text, terms)



def load_gijang_manual_ordinances() -> List[Dict[str, Any]]:
    """ELIS 기장군 자치법규 목록을 붙여넣어 만든 수동 목록입니다.
    법제처/ELIS 검색 API가 기장군 목록을 안정적으로 주지 않을 때 목록 검색용으로 사용합니다.
    """
    if not GIJANG_MANUAL_PATH.exists():
        return []
    try:
        data = json.loads(GIJANG_MANUAL_PATH.read_text("utf-8"))
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return [x for x in data if isinstance(x, dict) and str(x.get("name", "")).strip()]


def manual_key_for_gijang_item(idx: int, item: Dict[str, Any]) -> str:
    sig = f"{idx}|{item.get('name','')}|{item.get('department','')}|{item.get('effective_date','')}"
    return "manual-gijang-" + hashlib.sha1(sig.encode("utf-8", "ignore")).hexdigest()[:12]


def manual_gijang_item(idx: int, item: Dict[str, Any]) -> Dict[str, Any]:
    name = str(item.get("name", "")).strip()
    dept = str(item.get("department", "")).strip()
    date = str(item.get("effective_date", "")).strip()
    section = str(item.get("section", "")).strip()
    subsection = str(item.get("subsection", "")).strip()
    key = manual_key_for_gijang_item(idx, item)
    return {
        "name": name,
        "law_id": key,
        "mst": "",
        "effective_date": date,
        "department": dept,
        "target": "ordin_gijang",
        "api_target": "ordin",
        "target_label": TARGETS.get("ordin_gijang", "자치법규(기장군)"),
        "manual": True,
        "manual_key": key,
        "section": section,
        "subsection": subsection,
        "source_url": "https://www.elis.go.kr/alrpop/locgovAlrPopup?ctpvCd=26&sggCd=710",
    }


def _manual_gijang_match_text(row: Dict[str, Any]) -> str:
    return " ".join(str(row.get(k, "")) for k in ("name", "department", "section", "subsection", "effective_date"))


def _manual_query_match(text: str, terms: List[str]) -> bool:
    if not terms:
        return True
    # 1차는 본문검색 기준과 같은 완전일치 단어, 2차는 제목 목록 검색 편의를 위한 느슨한 포함 검색입니다.
    if contains_any_exact_term(text, terms):
        return True
    squashed = re.sub(r"\s+", "", text)
    return any(re.sub(r"\s+", "", t) in squashed for t in terms if t)


def search_gijang_manual(query: str, search: str = "1", display: str = "100", page: str = "1") -> Dict[str, Any]:
    terms = split_terms(query)
    rows = []
    for idx, raw in enumerate(load_gijang_manual_ordinances()):
        item = manual_gijang_item(idx, raw)
        hay = _manual_gijang_match_text(item)
        if not _manual_query_match(hay, terms):
            continue
        if search == "2":
            item["matches"] = [{
                "article_number": "",
                "article_title": "수동 기장군 자치법규 목록",
                "jo": "",
                "path": "수동목록",
                "kind": "title",
                "text": f"{item['name']} / {item.get('department','')} / 제·개정일 {item.get('effective_date','')}",
                "full_text": hay,
            }]
            item["article_count"] = 0
        rows.append(item)
    try:
        disp = max(1, min(500, int(display or 100)))
    except Exception:
        disp = 100
    try:
        pg = max(1, int(page or 1))
    except Exception:
        pg = 1
    start = (pg - 1) * disp
    sliced = rows[start:start+disp]
    return {
        "ok": True,
        "manual": True,
        "normalized": {"items": sliced, "total": len(rows)},
        "data": {"manual_count": len(rows), "page": pg, "display": disp},
    }


def get_gijang_manual_by_key_or_name(key: str = "", name: str = "") -> Optional[Dict[str, Any]]:
    wanted_key = str(key or "").strip()
    wanted_name = normalize_law_name(name)
    for idx, raw in enumerate(load_gijang_manual_ordinances()):
        item = manual_gijang_item(idx, raw)
        if wanted_key and item.get("manual_key") == wanted_key:
            return item
        if wanted_key and item.get("law_id") == wanted_key:
            return item
        if wanted_name and normalize_law_name(item.get("name", "")) == wanted_name:
            return item
    return None


def manual_gijang_placeholder_detail(item: Dict[str, Any]) -> Dict[str, Any]:
    name = item.get("name", "기장군 자치법규")
    dept = item.get("department", "")
    date = item.get("effective_date", "")
    section = item.get("section", "")
    subsection = item.get("subsection", "")
    url = item.get("source_url", "https://www.elis.go.kr/alrpop/locgovAlrPopup?ctpvCd=26&sggCd=710")
    text = (
        "이 항목은 ELIS 기장군 자치법규 목록을 수동으로 등록한 자료입니다. "
        "법제처/ELIS API에서 상세 ID가 안정적으로 내려오지 않으면 본문은 자동 표시되지 않을 수 있습니다.\n\n"
        f"법규명: {name}\n소관부서: {dept}\n편/장: {section} / {subsection}\n제·개정일: {date}\n원문 확인: {url}"
    )
    seg = {"article": "", "paragraph": "", "ho": "", "mok": "", "level": "수동목록", "text": text}
    return {
        "metadata": {"law_name": name, "target": "ordin_gijang", "law_id": item.get("law_id", ""), "mst": "", "department": dept, "effective_date": date},
        "articles": [{"number": "", "title": "수동 등록 기장군 자치법규", "body": text, "segments": [seg]}],
        "segments": [seg],
        "addenda_count": 0,
        "annexes": [],
        "raw": item,
    }

def content_kind(key: str) -> str:
    return {
        "조문내용": "조문",
        "항내용": "항",
        "호내용": "호",
        "목내용": "목",
    }.get(key, key)


def number_hint(obj: Dict[str, Any], kind: str) -> str:
    if kind == "조문":
        no = article_number_from_item(obj)
        title = pick(obj, "조문제목", "제목")
        return f"{no} {title}".strip()
    if kind == "항":
        return pick(obj, "항번호", "항번", "항")
    if kind == "호":
        return pick(obj, "호번호", "호번", "호")
    if kind == "목":
        return pick(obj, "목번호", "목번", "목")
    return ""


def clip_text(text: str, terms: List[str], max_len: int = 420) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(text) <= max_len:
        return text
    positions = [text.find(t) for t in terms if t and text.find(t) >= 0]
    start = max(0, (min(positions) if positions else 0) - 90)
    end = min(len(text), start + max_len)
    return ("…" if start > 0 else "") + text[start:end] + ("…" if end < len(text) else "")


def article_fragments(article: Dict[str, Any], query: str, max_hits: int = 8) -> List[Dict[str, str]]:
    terms = split_terms(query)
    raw = article.get("raw") or {}
    base = f"{article.get('number', '')} {article.get('title', '')}".strip()
    hits: List[Dict[str, str]] = []
    seen = set()

    def walk(obj: Any, path: List[str]) -> None:
        if len(hits) >= max_hits:
            return
        if isinstance(obj, dict):
            for key in ("조문내용", "항내용", "호내용", "목내용"):
                val = obj.get(key)
                if isinstance(val, str) and val.strip() and contains_terms(val, terms):
                    kind = content_kind(key)
                    no = number_hint(obj, kind)
                    label_parts = [p for p in path if p]
                    label = " > ".join(label_parts + [kind + (f" {no}" if no else "")])
                    text = clip_text(val, terms)
                    sig = re.sub(r"\s+", "", label + text)[:180]
                    if sig not in seen:
                        seen.add(sig)
                        hits.append({"path": label or base or kind, "kind": kind, "text": text, "full_text": re.sub(r"\s+", " ", val.strip())})
            next_path = path
            if any(k in obj for k in ("조문번호", "조문제목")):
                art_label = f"{article_number_from_item(obj)} {pick(obj, '조문제목', '제목')}".strip()
                next_path = [art_label] if art_label else path
            for v in obj.values():
                if isinstance(v, (dict, list)):
                    walk(v, next_path)
        elif isinstance(obj, list):
            for x in obj:
                walk(x, path)

    walk(raw, [base] if base else [])
    if not hits and contains_terms(article.get("body", ""), terms):
        hits.append({"path": base or "조문", "kind": "조문", "text": clip_text(article.get("body", ""), terms), "full_text": re.sub(r"\s+", " ", str(article.get("body", "")).strip())})
    return hits[:max_hits]



def prec_source_sections_from_item(item: Dict[str, Any]) -> List[Tuple[str, str]]:
    """판례 목록조회 응답 안에 이미 내려온 판결요지/판례내용을 상세조회 보조 본문으로 사용합니다.
    일부 판례는 lawService HTML 상세가 제목·요약만 반환하므로 목록 필드가 더 실용적인 경우가 있습니다.
    """
    raw = item.get("raw") if isinstance(item.get("raw"), dict) else {}
    sections: List[Tuple[str, str]] = []
    meta_keys = [
        ("사건명", "사건명"), ("사건번호", "사건번호"), ("선고일자", "선고일자"),
        ("법원명", "법원"), ("데이터출처명", "데이터출처"), ("세목", "세목"), ("판결유형", "판결유형"),
    ]
    body_keys = [
        ("판시사항", "판시사항"), ("판결요지", "판결요지"), ("결정요지", "결정요지"), ("요지", "요지"),
        ("판례내용", "판례내용"), ("내용", "내용"), ("본문", "본문"), ("전문", "전문"),
        ("주문", "주문"), ("이유", "이유"), ("처분개요", "처분개요"), ("청구주장", "청구주장"),
        ("심리및판단", "심리 및 판단"), ("판단", "판단"), ("참조조문", "참조조문"), ("참조판례", "참조판례"),
    ]
    seen = set()
    for key, label in meta_keys + body_keys:
        val = raw.get(key)
        if val in (None, ""):
            continue
        txt = html_to_text(str(val))
        txt = re.sub(r"\s+", " ", txt).strip()
        if not txt:
            continue
        split = split_prec_inline_labeled_text(txt) if key in ("판례내용", "전문", "내용", "본문") else []
        candidates = split if split else [(label, txt)]
        for shown_label, shown_txt in candidates:
            sig = re.sub(r"\s+", "", shown_label + shown_txt)[:300]
            if sig in seen:
                continue
            seen.add(sig)
            sections.append((shown_label, shown_txt))
    # normalize_search에서 별도 추출한 요약도 보조로 사용합니다.
    summary = str(item.get("summary") or "").strip()
    if summary:
        sig = re.sub(r"\s+", "", summary)[:300]
        if sig not in seen:
            sections.append(("목록 제공 내용", summary))
    return sections


def prec_matches_from_source_item(item: Dict[str, Any], query: str, max_hits: int = 8) -> List[Dict[str, str]]:
    terms = split_terms(query)
    hits: List[Dict[str, str]] = []
    for label, txt in prec_source_sections_from_item(item):
        if contains_terms(label + " " + txt, terms):
            hits.append({
                "article_number": label,
                "article_title": str(item.get("name") or ""),
                "jo": "",
                "path": label,
                "kind": "판례",
                "text": clip_text(txt, terms),
                "full_text": re.sub(r"\s+", " ", txt.strip()),
            })
            if len(hits) >= max_hits:
                break
    return hits

def case_matches_from_source_item(item: Dict[str, Any], query: str, max_hits: int = 8) -> List[Dict[str, str]]:
    """v20: 사례형 목록 응답의 텍스트 필드(요지·사건명 등)에서 본문검색 매칭을 만듭니다."""
    terms = split_terms(query)
    raw = item.get("raw") if isinstance(item.get("raw"), dict) else {}
    hits: List[Dict[str, str]] = []
    seen = set()
    fields: List[Tuple[str, str]] = []
    for key, val in raw.items():
        if isinstance(val, (dict, list)) or val in (None, ""):
            continue
        txt = _clean_case_text(val)
        if len(txt) < 2 or "상세링크" in str(key):
            continue
        fields.append((str(key), txt))
    summary = str(item.get("summary") or "").strip()
    if summary:
        fields.append(("목록 제공 내용", summary))
    for label, txt in fields:
        if not contains_terms(label + " " + txt, terms):
            continue
        sig = re.sub(r"\s+", "", label + txt)[:200]
        if sig in seen:
            continue
        seen.add(sig)
        hits.append({
            "article_number": label,
            "article_title": str(item.get("name") or ""),
            "jo": "",
            "path": label,
            "kind": "사례",
            "text": clip_text(txt, terms),
            "full_text": re.sub(r"\s+", " ", txt.strip()),
        })
        if len(hits) >= max_hits:
            break
    return hits


def enrich_item_with_matches(item: Dict[str, Any], target: str, query: str, refresh: bool = False) -> Dict[str, Any]:
    # v20: 별표서식형은 상세조회가 곧 목록 재조회라 항목별 enrich 호출이 낭비입니다.
    # 목록 텍스트 기반으로 즉시 매칭을 만들고 끝냅니다.
    if target in BYL_TARGETS:
        item = dict(item)
        item["matches"] = case_matches_from_source_item(item, query)
        item["article_count"] = 0
        return item
    detail = get_detail_payload(target, item.get("law_id", ""), item.get("mst", ""), item.get("effective_date", ""), "", refresh)
    item = dict(item)
    if not detail.get("ok"):
        item["matches"] = []
        item["match_error"] = detail.get("error", "상세조회 실패")
        return item
    normalized = detail.get("normalized", {})
    matches = []
    for art in normalized.get("articles", []):
        for frag in article_fragments(art, query, max_hits=8):
            matches.append({
                "article_number": art.get("number", ""),
                "article_title": art.get("title", ""),
                "jo": art.get("jo", ""),
                "path": frag.get("path", ""),
                "kind": frag.get("kind", ""),
                "text": frag.get("text", ""),
                "full_text": frag.get("full_text", ""),
            })
            if len(matches) >= 8:
                break
        if len(matches) >= 8:
            break
    if target == "prec" and not matches:
        matches = prec_matches_from_source_item(item, query)
    # v20: 사례형도 상세 매칭이 비면 목록 필드 기반 매칭으로 보조합니다.
    if target in CASE_TARGETS and not matches:
        matches = case_matches_from_source_item(item, query)
    item["matches"] = matches
    item["detail_meta"] = normalized.get("metadata", {})
    item["article_count"] = len(normalized.get("articles", []))
    return item



def parse_xml_to_dict(text: str) -> Any:
    """법제처 XML 응답을 간단 dict/list 구조로 변환합니다."""
    try:
        import xml.etree.ElementTree as ET
        root_el = ET.fromstring(text.encode("utf-8"))
    except Exception:
        return {"raw": text}

    def conv(el):
        children = list(el)
        if not children:
            return (el.text or "").strip()
        d: Dict[str, Any] = {}
        for child in children:
            val = conv(child)
            if child.tag in d:
                if not isinstance(d[child.tag], list):
                    d[child.tag] = [d[child.tag]]
                d[child.tag].append(val)
            else:
                d[child.tag] = val
        txt = (el.text or "").strip()
        if txt:
            d["text"] = txt
        return d

    return {root_el.tag: conv(root_el)}


def has_article_text(normalized: Dict[str, Any]) -> bool:
    for a in normalized.get("articles", []) or []:
        if str(a.get("body", "")).strip():
            return True
        for s in a.get("segments", []) or []:
            if str(s.get("text", "")).strip():
                return True
    return False

# ---------------------------------------------------------------------------
# v20: 국세법령정보시스템(taxlaw.nts.go.kr) 위임 판례의 전문을 텍스트로 가져오기
# 법제처 API가 본문을 주지 않는 국세청 출처 판례는 precInfoP.do가 taxlaw로
# 리다이렉트되고, 그 화면의 action.do(ASIQTB002PR01)가 요지·재판경과·본문 HTML·
# 관련문서를 모두 돌려줍니다. (2026-06 실측 검증)
# ---------------------------------------------------------------------------

NTS_META_KEY_SKIP = re.compile(
    r"^(mateStat|frsRgt|lstAlt|searchCondition|searchKeyword|searchUseYn|pageIndex|pageSize|firstIndex|lastIndex|recordCount)"
)

NTS_BODY_HEADINGS = ("주문", "이유", "청구취지", "청구원인", "범죄사실", "항소취지", "상고취지", "판결요지", "결론", "별지")


def _nts_row_text(item: Dict[str, Any]) -> str:
    """NTS 목록성 항목(재판경과/관련문서)에서 표시할 한국어 텍스트만 추립니다."""
    parts: List[str] = []
    for k, v in item.items():
        if not isinstance(v, str) or not v.strip():
            continue
        if NTS_META_KEY_SKIP.match(str(k)) or "MaagCl" in str(k) or "MaagUser" in str(k) or "MaagPgm" in str(k):
            continue
        val = v.strip()
        if len(val) > 400 or re.fullmatch(r"\d{14,}", val):
            continue
        parts.append(val)
    seen = set()
    out: List[str] = []
    for p in parts:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return " · ".join(out)


def fetch_nts_taxlaw_case(prec_seq: str, refresh: bool = False) -> Optional[Dict[str, Any]]:
    """precSeq → ntstDcmId 해석 후 국세법령정보시스템 문서 데이터를 받아옵니다(캐시)."""
    prec_seq = str(prec_seq or "").strip()
    if not prec_seq or not prec_seq.isdigit():
        return None
    ck = cache_key("taxlaw_case", {"precSeq": prec_seq})
    if not refresh and ck.exists() and time.time() - ck.stat().st_mtime < CACHE_TTL_SECONDS:
        try:
            cached = json.loads(ck.read_text("utf-8"))
            if isinstance(cached, dict) and cached.get("root"):
                return cached
        except Exception:
            pass
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(
            f"https://www.law.go.kr/LSW/precInfoP.do?precSeq={prec_seq}&mode=0",
            headers=headers, timeout=18, allow_redirects=False,
        )
        loc = str(r.headers.get("Location") or "")
        if "taxlaw.nts.go.kr" not in loc:
            return None
        m = re.search(r"ntstDcmId=(\d+)", loc)
        if not m:
            return None
        doc_id = m.group(1)
        resp = requests.post(
            "https://taxlaw.nts.go.kr/action.do",
            data={
                "actionId": "ASIQTB002PR01",
                "paramData": json.dumps({"dcmDVO": {"ntstDcmId": doc_id}}, ensure_ascii=False),
            },
            headers=headers, timeout=18,
        )
        resp.raise_for_status()
        payload = resp.json()
        if str(payload.get("status")) != "SUCCESS":
            return None
        root = (payload.get("data") or {}).get("ASIQTB002PR01") or {}
        if not isinstance(root, dict) or not isinstance(root.get("dcmDVO"), dict):
            return None
        result = {"doc_id": doc_id, "root": root}
        try:
            ck.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
        return result
    except Exception:
        return None


def _split_nts_body_sections(text: str) -> List[Tuple[str, str]]:
    """판결문 전문을 '주 문'·'이 유' 같은 단독 표제 줄 기준으로 섹션 분리합니다."""
    lines = [ln.rstrip() for ln in str(text or "").splitlines()]
    sections: List[Tuple[str, str]] = []
    cur_label = "판결문"
    cur: List[str] = []
    for ln in lines:
        stripped = ln.strip()
        compact = re.sub(r"[\s\d.\-:：]+", "", stripped)
        if compact in NTS_BODY_HEADINGS and len(stripped) <= 12:
            if "\n".join(cur).strip():
                sections.append((cur_label, "\n".join(cur).strip()))
            cur_label = re.sub(r"\s+", " ", stripped)
            cur = []
        else:
            cur.append(ln)
    if "\n".join(cur).strip():
        sections.append((cur_label, "\n".join(cur).strip()))
    return [(label, txt) for label, txt in sections if txt.strip()]


def build_nts_case_detail(prec_seq: str, law_id: str, mst: str, law_name: str, refresh: bool = False) -> Optional[Dict[str, Any]]:
    """NTS 문서 데이터를 대시보드 표준 섹션 카드(한 스크롤)로 정규화합니다."""
    fetched = fetch_nts_taxlaw_case(prec_seq, refresh)
    if not fetched:
        return None
    root = fetched.get("root") or {}
    d = root.get("dcmDVO") or {}
    title = html_to_text(str(d.get("ntstDcmTtl") or "")) or (law_name or "판례")
    case_no = str(d.get("ntstDcmDscmCntn") or "").strip()

    chunks: List[Tuple[str, str]] = []
    meta_lines = [x for x in (
        (f"사건번호: {case_no}" if case_no else ""),
        "출처: 국세법령정보시스템(국세청) — 전문을 대시보드 안에 표시합니다.",
    ) if x]
    if meta_lines:
        chunks.append(("개요 정보", "\n".join(meta_lines)))

    gist = html_to_text(str(d.get("ntstDcmGistCntn") or "")).strip()
    if gist:
        chunks.append(("요지", gist))

    tril = [t for t in (_nts_row_text(x) for x in as_list(root.get("trilPsagList")) if isinstance(x, dict)) if t]
    if tril:
        chunks.append(("재판경과", "\n".join(f"- {t}" for t in tril)))

    body_html = ""
    for x in as_list(root.get("dcmHwpEditorDVOList")):
        if isinstance(x, dict) and str(x.get("dcmFleByte") or "").strip():
            body_html = str(x.get("dcmFleByte"))
            break
    if body_html:
        body_text = html_to_text(body_html)
        for label, txt in _split_nts_body_sections(body_text):
            chunks.append((label, txt))

    rltn: List[str] = []
    for key in ("dcmRltnStttList", "dcmRltnStttMatrList", "dcmRfrnPrtsList", "dcmQutPrtsList"):
        for x in as_list(root.get(key)):
            if isinstance(x, dict):
                t = _nts_row_text(x)
                if t and t not in rltn:
                    rltn.append(t)
    if rltn:
        chunks.append(("관련 법령·유사문서", "\n".join(f"- {t}" for t in rltn)))

    # 본문성 섹션이 하나도 없으면 실패로 보고 iframe 표시로 돌려보냅니다.
    has_body = any(label != "개요 정보" and len(_compact_for_compare(txt)) > 40 for label, txt in chunks)
    if not has_body:
        return None

    articles: List[Dict[str, Any]] = []
    for label, txt in chunks:
        seg = {"level": "판례", "article": label, "article_title": title, "paragraph": "", "ho": "", "mok": "", "text": txt}
        articles.append({"number": label, "jo": "", "title": label, "effective_date": "", "changed": "", "body": txt, "segments": [seg], "raw": {label: txt}})
    normalized = {
        "metadata": {
            "law_name": title,
            "law_id": law_id or prec_seq,
            "mst": mst or prec_seq,
            "department": "국세법령정보시스템",
            "effective_date": "",
            "promulgation_date": "",
            "revision_type": "",
        },
        "articles": articles,
        "segments": [s for a in articles for s in a.get("segments", [])],
        "addenda_count": 0,
        "annexes": [],
        "raw": {"nts_doc_id": fetched.get("doc_id", ""), "source": "taxlaw.nts.go.kr"},
        "render_type": "prec_nts_text",
    }
    return add_prec_original_url(normalized, prec_seq, title)


# ---------------------------------------------------------------------------
# v20: 법령 본문 조문 간 상호참조 링크 (법제처 화면이 그려주는 인용 하이퍼링크)
# 법제처 본문 뷰어(lsInfoR.do)는 조문 안의 「법령명」·제N조 인용마다 고유 ID
# (lsJoLnkSeq)를 박아 줍니다. 그 ID를 lsLinkCommonInfo.do로 해석하면 대상 법령의
# lsiSeq(=MST)와 조문을 알 수 있어, 클릭 시 우리 창에 정확히 열 수 있습니다.
# (2026-06 실측 검증: efYd 필수, lsiSeq=MST 동일 체계)
# ---------------------------------------------------------------------------

LAWGO_WEB_HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.law.go.kr/"}


def jo_anchor_to_article_number(anchor: str) -> str:
    """법제처 조문 앵커(J3:0, J10:2)를 우리 조문번호 표기(제3조, 제10조의2)로 변환."""
    m = re.match(r"J(\d+):(\d+)", str(anchor or ""))
    if not m:
        return ""
    jo, gaji = int(m.group(1)), int(m.group(2))
    return f"제{jo}조의{gaji}" if gaji else f"제{jo}조"


def fetch_lawgo_article_links(lsiseq: str, efyd: str, refresh: bool = False) -> Dict[str, List[Dict[str, str]]]:
    """현행법령 본문(lsInfoR.do)을 받아 조문별 인용 링크 목록을 추출합니다.
    반환: {"제3조": [{"text":"「지방세기본법」","seq":"...","type":"ALLJO"}, ...], ...}"""
    lsiseq = re.sub(r"\D", "", str(lsiseq or ""))
    efyd = re.sub(r"\D", "", str(efyd or ""))
    if not lsiseq or len(efyd) != 8:
        return {}
    ck = cache_key("lawgo_links", {"lsiSeq": lsiseq, "efYd": efyd})
    if not refresh and ck.exists() and time.time() - ck.stat().st_mtime < CACHE_TTL_SECONDS:
        try:
            cached = json.loads(ck.read_text("utf-8"))
            if isinstance(cached, dict):
                return cached
        except Exception:
            pass
    url = (
        "https://www.law.go.kr/LSW/lsInfoR.do"
        f"?lsiSeq={lsiseq}&efYd={efyd}&efYn=Y&chrClsCd=010202&nwJoYnInfo=Y&ancYnChk=0&netPrivateYn=N"
    )
    # law.go.kr 본문 뷰어는 간헐적으로 SSL EOF/연결 오류를 낸다. 빈 결과(링크 0개)가 detail에
    # 들어가면 그 법령은 인용링크가 안 뜨므로, 일시 오류는 최대 3회 재시도한다.
    html_text = ""
    for attempt in range(3):
        try:
            r = requests.get(url, headers=LAWGO_WEB_HEADERS, timeout=20)
            r.raise_for_status()
            try:
                r.encoding = r.apparent_encoding or r.encoding
            except Exception:
                pass
            html_text = r.text
            break
        except Exception:
            time.sleep(0.5 * (attempt + 1))
    if not html_text or "fncLsLawPop" not in html_text:
        return {}
    anchors = [(m.group(1), m.start()) for m in re.finditer(r'<a\s+name="(J\d+:\d+)"', html_text)]
    result: Dict[str, List[Dict[str, str]]] = {}
    link_re = re.compile(r"fncLsLawPop\('(\d+)','(\w+)'[^>]*>([^<]+)</a>")
    for i, (anchor, pos) in enumerate(anchors):
        end = anchors[i + 1][1] if i + 1 < len(anchors) else len(html_text)
        art_num = jo_anchor_to_article_number(anchor)
        if not art_num:
            continue
        seg = html_text[pos:end]
        links: List[Dict[str, str]] = []
        seen = set()
        for lm in link_re.finditer(seg):
            seq, typ, text = lm.group(1), lm.group(2), re.sub(r"\s+", " ", html.unescape(lm.group(3))).strip()
            if not text or not seq:
                continue
            key = (text, seq)
            if key in seen:
                continue
            seen.add(key)
            links.append({"text": text, "seq": seq, "type": typ})
        if links:
            result.setdefault(art_num, []).extend(links)
    try:
        ck.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    return result


def resolve_lawgo_ref_target(seq: str, refresh: bool = False) -> Dict[str, Any]:
    """인용 링크 ID(lsJoLnkSeq)를 대상 법령 lsiSeq(=MST)·법령명·조문으로 해석합니다."""
    seq = re.sub(r"\D", "", str(seq or ""))
    if not seq:
        return {"ok": False, "error": "링크 ID가 없습니다."}
    ck = cache_key("lawgo_ref", {"seq": seq})
    if not refresh and ck.exists() and time.time() - ck.stat().st_mtime < CACHE_TTL_SECONDS:
        try:
            cached = json.loads(ck.read_text("utf-8"))
            if isinstance(cached, dict) and cached.get("ok"):
                return cached
        except Exception:
            pass
    try:
        r = requests.get(
            f"https://www.law.go.kr/LSW/lsLinkCommonInfo.do?lsJoLnkSeq={seq}",
            headers=LAWGO_WEB_HEADERS, timeout=20,
        )
        r.raise_for_status()
        try:
            r.encoding = r.apparent_encoding or r.encoding
        except Exception:
            pass
        html_text = r.text
    except Exception as e:
        return {"ok": False, "error": f"링크 해석 실패: {e}"}
    def _law_name_from_title() -> str:
        # 페이지 제목 형식: "법령 > 본문 > <법령명> | 국가법령정보센터"
        mt = re.search(r"<title[^>]*>([^<]+)</title>", html_text)
        if not mt:
            return ""
        head = html.unescape(mt.group(1)).split("|")[0]
        parts = re.split(r"[>＞]", head)
        nm = parts[-1].strip() if parts else ""
        return "" if nm in ("법령", "본문", "국가법령정보센터") else nm

    m_lsi = re.search(r"lsInfoP\.do\?lsiSeq=(\d+)", html_text)
    if not m_lsi:
        # ALLJO(법령 전체)·상대참조("같은 법" 등)는 lsiSeq가 응답에 없습니다.
        # 제목에서 대상 법령명만 뽑아 프론트가 검색으로 열도록 합니다.
        nm = _law_name_from_title()
        if nm:
            res = {"ok": True, "by_name": True, "lsiseq": "", "mst": "", "target": "law", "law_name": nm, "jo": ""}
            try:
                ck.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
            except Exception:
                pass
            return res
        return {"ok": False, "error": "대상 법령을 찾지 못했습니다."}
    target_lsi = m_lsi.group(1)
    m_name = re.search(r"<h1[^>]*>\s*([^<]{2,40})\s*</h1>", html_text)
    law_name = html.unescape(m_name.group(1)).strip() if m_name else ""
    if not law_name or "국가법령정보" in law_name:
        law_name = _law_name_from_title() or law_name
    m_jo = re.search(r'name="(J\d+:\d+)"', html_text)
    jo = jo_anchor_to_article_number(m_jo.group(1)) if m_jo else ""
    result = {
        "ok": True,
        "lsiseq": target_lsi,
        "mst": target_lsi,
        "target": "law",
        "law_name": law_name,
        "jo": jo,
    }
    try:
        ck.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    return result


def attach_lawgo_links(normalized: Dict[str, Any], mst: str, efyd: str, refresh: bool = False) -> bool:
    """정규화된 법령 상세의 각 조문에 인용 링크 목록을 붙입니다. 성공 시 True."""
    if not isinstance(normalized, dict):
        return False
    links_map = fetch_lawgo_article_links(mst, efyd, refresh)
    if not links_map:
        return False
    attached = 0
    for art in normalized.get("articles", []):
        if not isinstance(art, dict):
            continue
        key = str(art.get("number") or "")
        if key in links_map:
            art["links"] = links_map[key]
            attached += 1
    if attached:
        normalized["has_ref_links"] = True
    return attached > 0


# ---------------------------------------------------------------------------
# v20: 자치법규(조례) 조문 인용 링크
# 조례 본문 뷰어(ordinInfoR.do)도 fncOrdinLawPop('법령ID','분류','구분','조문번호',...)
# 형태로 인용 링크를 박아 줍니다. 법령(lsInfoR)과 달리 파라미터에 대상 법령ID·조문이
# 직접 들어 있어 별도 해석 호출이 필요 없습니다. (2026-06 실측)
#   분류: 010101=법령, 010103=자치법규 / 구분: 012601=법령전체, 012602=조문
#   조문번호 4자리(0032=제32조). 우리 ordin JSON 파싱은 조문을 1개로 합쳐버려서,
#   조례는 ordinInfoR 본문을 조문별로 파싱해 카드+링크를 함께 만듭니다.
# ---------------------------------------------------------------------------

def fetch_ordin_linked_articles(ordin_seq: str, refresh: bool = False) -> List[Dict[str, Any]]:
    """조례 본문(ordinInfoR.do)을 조문별 카드로 파싱하고 인용 링크를 붙입니다."""
    ordin_seq = re.sub(r"\D", "", str(ordin_seq or ""))
    if not ordin_seq:
        return []
    ck = cache_key("ordin_links", {"ordinSeq": ordin_seq})
    if not refresh and ck.exists() and time.time() - ck.stat().st_mtime < CACHE_TTL_SECONDS:
        try:
            cached = json.loads(ck.read_text("utf-8"))
            if isinstance(cached, list):
                return cached
        except Exception:
            pass
    url = f"https://www.law.go.kr/LSW/ordinInfoR.do?ordinSeq={ordin_seq}&chrClsCd=010202&gubun=ELIS"
    try:
        r = requests.get(url, headers=LAWGO_WEB_HEADERS, timeout=20)
        r.raise_for_status()
        try:
            r.encoding = r.apparent_encoding or r.encoding
        except Exception:
            pass
        html_text = r.text
    except Exception:
        return []
    if 'name="J' not in html_text:
        return []
    anchors = [(m.group(1), m.start()) for m in re.finditer(r'<a\s+name="(J\d+:\d+)"', html_text)]
    link_re = re.compile(r"fncOrdinLawPop\('(\d+)','(\d+)','(\d+)','(\d+)','(\d+)','(\d+)'[^>]*>([^<]+)</a>")
    articles: List[Dict[str, Any]] = []
    for i, (anchor, pos) in enumerate(anchors):
        end = anchors[i + 1][1] if i + 1 < len(anchors) else len(html_text)
        seg = html_text[pos:end]
        # 부칙(ar)·별표(arArea) 영역이 같은 구간에 섞이면 잘라냅니다.
        ar = re.search(r'<a\s+name="ar', seg)
        if ar:
            seg = seg[:ar.start()]
        num = jo_anchor_to_article_number(anchor)
        if not num:
            continue
        body = html_to_text(seg)
        if not body:
            continue
        tm = re.match(rf"{re.escape(num)}\s*(?:의\d+)?\s*\(([^)]{{1,40}})\)", body)
        title = tm.group(1).strip() if tm else ""
        links: List[Dict[str, Any]] = []
        seen = set()
        for lm in link_re.finditer(seg):
            lawid, clscd, gubun, jono = lm.group(1), lm.group(2), lm.group(3), lm.group(4)
            text = re.sub(r"\s+", " ", html.unescape(lm.group(7))).strip()
            if not text:
                continue
            jo = ""
            if gubun == "012602" and jono and jono != "0000":
                try:
                    jo = f"제{int(jono)}조"
                except Exception:
                    jo = ""
            key = (text, lawid, jo)
            if key in seen:
                continue
            seen.add(key)
            links.append({
                "text": text,
                "law_id": lawid,
                "is_ordin": clscd == "010103",
                "jo": jo,
                "type": "ALL" if gubun == "012601" else "JO",
            })
        seg_obj = {"level": "조", "article": num, "article_title": title, "paragraph": "", "ho": "", "mok": "", "text": body}
        articles.append({
            "number": num, "jo": "", "title": title, "effective_date": "", "changed": "",
            "body": body, "segments": [seg_obj], "raw": {}, "links": links,
        })
    try:
        ck.write_text(json.dumps(articles, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    return articles


def get_ordin_linked_detail(mst: str, law_name: str, refresh: bool = False) -> Optional[Dict[str, Any]]:
    """조례 상세를 ordinInfoR 기반(조문별 카드 + 인용 링크)으로 구성합니다."""
    articles = fetch_ordin_linked_articles(mst, refresh)
    if not articles:
        return None
    normalized = {
        "metadata": {
            "law_name": law_name or "자치법규",
            "law_id": "",
            "mst": str(mst or ""),
            "department": "",
            "effective_date": "",
            "promulgation_date": "",
            "revision_type": "",
        },
        "articles": articles,
        "segments": [s for a in articles for s in a.get("segments", [])],
        "addenda_count": 0,
        "annexes": [],
        "raw": {},
        "has_ref_links": True,
        "render_type": "ordin_linked",
    }
    return normalized


def get_byl_detail(target: str, law_id: str, mst: str, law_name: str, refresh: bool = False) -> Dict[str, Any]:
    """별표서식형 상세보기. 본문조회 API가 없어 목록조회를 재호출해
    같은 별표일련번호 항목의 파일 다운로드 링크를 annexes로 합성합니다."""
    wanted = str(law_id or mst or "").strip()
    q = str(law_name or "").strip()
    # normalize_search가 만든 "별표명 (관련법령명)" 표기에서 별표명만 검색어로 씁니다.
    if q.endswith(")") and " (" in q:
        q = q[: q.rfind(" (")].strip()
    if not q and not wanted:
        return {"ok": False, "error": "별표·서식 상세를 찾을 검색 정보가 없습니다."}
    result = request_law_api("lawSearch.do", {"target": target, "type": "JSON", "query": q, "display": "100", "OC": get_oc()}, refresh=refresh)
    if not result.get("ok"):
        return result
    norm = normalize_search(result.get("data", {}))
    items = norm.get("items", [])
    exact = [x for x in items if wanted and str((x.get("raw") or {}).get("별표일련번호", "")).strip() == wanted]
    matched = exact or items
    if not matched:
        return {"ok": False, "error": "별표·서식 정보를 다시 찾지 못했습니다. 같은 이름으로 재검색해 주세요."}

    label = TARGETS.get(target, target)
    annexes: List[Dict[str, str]] = []
    lines: List[str] = []
    for x in matched[:30]:
        raw = x.get("raw") if isinstance(x.get("raw"), dict) else {}
        title_txt = html_to_text(pick(raw, "별표명")) or str(x.get("name") or "")
        kind = pick(raw, "별표종류")
        no = pick(raw, "별표번호")
        parent = pick(raw, "관련법령명", "관련행정규칙명", "관련자치법규명")
        org_nm = pick(raw, "소관부처명", "전체기관명", "지자체기관명")
        shown = " ".join(t for t in ((f"[{kind}]" if kind else ""), title_txt, (f"({parent})" if parent else "")) if t).strip()
        annexes.append({
            "title": shown or title_txt,
            "hwp": pick(raw, "별표서식파일링크"),
            "pdf": pick(raw, "별표서식PDF파일링크"),
            "body": "",
            "file_name": title_txt,
        })
        lines.append(" · ".join(t for t in (title_txt, (f"종류 {kind}" if kind else ""), (f"번호 {no}" if no else ""), parent, org_nm) if t))

    head_name = str(matched[0].get("name") or q or label)
    text = (
        f"{label} 검색 항목입니다. 별표·서식은 본문조회 API가 없어 파일 다운로드 링크로 표시합니다.\n"
        "아래 '별표·별지서식 다운로드' 목록에서 PDF 미리보기 또는 HWP 원본을 받을 수 있습니다."
        + ("\n\n" + "\n".join(f"- {ln}" for ln in lines) if lines else "")
    )
    seg = {"level": label, "article": label, "article_title": head_name, "paragraph": "", "ho": "", "mok": "", "text": text}
    normalized = {
        "metadata": {
            "law_name": head_name,
            "law_id": law_id,
            "mst": mst,
            "department": str(matched[0].get("department") or ""),
            "effective_date": str(matched[0].get("effective_date") or ""),
            "promulgation_date": str(matched[0].get("promulgation_date") or ""),
            "revision_type": "",
        },
        "articles": [{"number": label, "jo": "", "title": head_name, "effective_date": "", "changed": "", "body": text, "segments": [seg], "raw": {label: text}}],
        "segments": [seg],
        "addenda_count": 0,
        "annexes": annexes,
        "raw": {"items": [x.get("raw") for x in matched[:30]]},
        "render_type": "byl_list",
    }
    return {"ok": True, "normalized": normalized, "data": result.get("data", {})}


def get_detail_payload(target: str, law_id: str, mst: str, efyd: str, jo: str, refresh: bool = False, law_name: str = "") -> Dict[str, Any]:
    # 상세본문 조회에서는 eflaw가 아니라 law를 사용해야 합니다.
    api_target = service_target_of(target)

    # v20: 별표서식형은 본문조회 API가 없으므로 목록 기반으로 합성합니다.
    if target in BYL_TARGETS:
        return get_byl_detail(target, law_id, mst, law_name, refresh)

    # v20: 사례형은 lawService JSON을 섹션 카드로 정규화하고, 비어 있으면 HTML로 보조합니다.
    if target in CASE_TARGETS:
        candidates: List[str] = []
        for x in (law_id, mst):
            x = str(x or "").strip()
            if x and x not in candidates and not looks_like_row_number(x):
                candidates.append(x)
        for x in (law_id, mst):
            x = str(x or "").strip()
            if x and x not in candidates:
                candidates.append(x)
        if not candidates:
            return {"ok": False, "error": f"{TARGETS.get(target, target)} 상세조회용 일련번호를 찾지 못했습니다. 캐시 새로고침 후 다시 검색해 주세요."}
        last_result: Dict[str, Any] = {"ok": False, "error": f"{TARGETS.get(target, target)} 본문 조회 실패"}
        for detail_id in candidates:
            result = request_law_api("lawService.do", {"target": target, "type": "JSON", "ID": detail_id, "OC": get_oc()}, refresh=refresh)
            if result.get("ok"):
                data = result.get("data", {})
                normalized = normalize_case_json_detail(data if isinstance(data, dict) else {}, target, law_id or detail_id, mst)
                result["normalized"] = normalized
                last_result = result
                if has_meaningful_case_json(normalized):
                    return result
            else:
                last_result = result
            html_result = request_law_api("lawService.do", {"target": target, "type": "HTML", "ID": detail_id, "OC": get_oc()}, refresh=refresh)
            if html_result.get("ok"):
                data = html_result.get("data", {})
                raw = data.get("raw", "") if isinstance(data, dict) else str(data or "")
                if raw and not re.search(r"일치하는 [^<>{}\n]{0,30}없습니다|사용자 정보 검증에 실패|XML 파싱중 오류", str(raw)[:2000]):
                    normalized = normalize_html_detail(str(raw), target, law_id, mst)
                    if has_article_text(normalized):
                        html_result["normalized"] = normalized
                        # JSON 섹션이 이미 있으면 그것을 유지하고, 없을 때만 HTML 본문을 채택합니다.
                        if not (last_result.get("ok") and has_meaningful_case_json(last_result.get("normalized", {}))):
                            last_result = html_result
                            return last_result
        if last_result.get("ok") and "normalized" not in last_result:
            data = last_result.get("data", {})
            raw_text = json.dumps(data, ensure_ascii=False, indent=2) if isinstance(data, (dict, list)) else str(data or "")
            last_result["normalized"] = normalize_html_detail(raw_text, target, law_id, mst)
        return last_result

    # v20: API 직접조회 항목은 실제 자치법규 ID/MST가 있으므로 일반 경로로 보냅니다.
    # 수동 키이거나 ID가 전혀 없을 때만 수동 목록 조회를 시도합니다.
    _gijang_has_real_id = any(
        str(x or "").strip() and not str(x or "").strip().startswith("manual-gijang-")
        for x in (law_id, mst)
    )
    if target == "ordin_gijang" and not _gijang_has_real_id and (str(law_id or "").startswith("manual-gijang-") or law_name):
        manual_item = get_gijang_manual_by_key_or_name(law_id, law_name)
        if manual_item:
            # 우선 같은 제목으로 법제처 자치법규 상세 ID를 찾아보고, 실패하면 수동목록 안내문을 표시합니다.
            try:
                lookup = search_one_target("ordin", manual_item.get("name", ""), "1", "10", "1", refresh)
                candidates = lookup.get("normalized", {}).get("items", []) if lookup.get("ok") else []
                wanted = normalize_law_name(manual_item.get("name", ""))
                for cand in candidates:
                    if normalize_law_name(cand.get("name", "")) != wanted:
                        continue
                    cid, cmst = cand.get("law_id", ""), cand.get("mst", "")
                    if cid or cmst:
                        found = get_detail_payload("ordin", cid, cmst, cand.get("effective_date", ""), jo, refresh)
                        if found.get("ok") and has_article_text(found.get("normalized", {})):
                            return found
            except Exception:
                pass
            return {"ok": True, "normalized": manual_gijang_placeholder_detail(manual_item), "manual": True}

    # 판례는 법령 조문 JSON과 구조가 다릅니다.
    # 기본은 공식 문서의 HTML 조회를 따르되, HTML이 제목/검색요약만 내려오면
    # 예전 패치처럼 JSON/XML 보조 조회까지 시도합니다.
    if api_target == "prec":
        candidates: List[str] = []
        for x in (mst, law_id):
            x = str(x or "").strip()
            if x and x not in candidates and not looks_like_row_number(x):
                candidates.append(x)
        for x in (mst, law_id):
            x = str(x or "").strip()
            if x and x not in candidates:
                candidates.append(x)
        if not candidates:
            return {"ok": False, "error": "판례 상세조회용 판례일련번호를 찾지 못했습니다. 캐시 새로고침 후 다시 검색해 주세요."}

        last_result: Dict[str, Any] = {"ok": False, "error": "판례 본문 조회 실패"}
        best_html_result: Optional[Dict[str, Any]] = None
        best_frame_result: Optional[Dict[str, Any]] = None

        for detail_id in candidates:
            html_trials = [
                {"target": "prec", "type": "HTML", "ID": detail_id, "LM": law_name, "mobileYn": "Y", "OC": get_oc()},
                {"target": "prec", "type": "HTML", "ID": detail_id, "mobileYn": "Y", "OC": get_oc()},
                {"target": "prec", "type": "HTML", "ID": detail_id, "LM": law_name, "OC": get_oc()},
                {"target": "prec", "type": "HTML", "ID": detail_id, "OC": get_oc()},
            ]
            for params in html_trials:
                result = request_law_api("lawService.do", params, refresh=refresh)
                last_result = result
                if not result.get("ok"):
                    continue
                raw = result.get("data", {}).get("raw", "") if isinstance(result.get("data"), dict) else ""
                if not raw:
                    continue
                normalized = normalize_prec_html_detail(raw, detail_id, mst, law_name)
                result["normalized"] = normalized
                if is_meaningful_prec_detail(normalized, law_name):
                    # v20: iframe 껍데기(원문 뷰어 위임형)는 바로 확정하지 않고 보관만 합니다.
                    # 대법원 등 JSON 본문이 있는 판례는 복사/노트연결이 되는 텍스트 섹션이 우선이고,
                    # JSON/XML에도 본문이 없을 때만 원문 뷰어 iframe을 씁니다.
                    if str(normalized.get("render_type") or "") == "prec_html_frame":
                        if best_frame_result is None:
                            best_frame_result = result
                        continue
                    return result
                # 제목만 있는 HTML이라도 최후 fallback으로는 보관합니다.
                if best_html_result is None:
                    best_html_result = result

            # HTML이 제목만 내려오는 자료가 있어 JSON/XML도 보조로 시도합니다.
            # 국세청 판례는 HTML만 가능하지만, 대법원/일부 자료는 JSON/XML에서 판례내용 필드가 더 잘 내려옵니다.
            for fmt in ("JSON", "XML"):
                params = {"target": "prec", "type": fmt, "ID": detail_id, "OC": get_oc()}
                result = request_law_api("lawService.do", params, refresh=refresh)
                last_result = result
                if not result.get("ok"):
                    continue
                data = result.get("data", {})
                if isinstance(data, dict) and "raw" in data and fmt == "XML":
                    data = parse_xml_to_dict(str(data.get("raw", "")))
                normalized = normalize_prec_json_detail(data if isinstance(data, dict) else {}, detail_id, mst)
                result["normalized"] = normalized
                if has_meaningful_prec_json(normalized):
                    return result

        if best_frame_result is not None:
            # v20: 국세법령정보시스템 위임 판례는 원문 데이터를 직접 받아
            # 한 스크롤 텍스트 섹션(요지·재판경과·주문·이유·관련문서)으로 표시합니다.
            frame_norm = best_frame_result.get("normalized", {}) if isinstance(best_frame_result, dict) else {}
            frame_src = str((frame_norm.get("raw") or {}).get("iframe_src") or "")
            m_seq = re.search(r"precSeq=(\d+)", frame_src)
            nts_seq = m_seq.group(1) if m_seq else (candidates[0] if candidates else "")
            nts_norm = build_nts_case_detail(nts_seq, law_id, mst, law_name, refresh)
            if nts_norm:
                return {"ok": True, "normalized": nts_norm, "source": "nts_taxlaw", "data": {}}
            # 추출에 실패하면 기존처럼 원문 뷰어 iframe을 표시합니다.
            return best_frame_result

        if best_html_result is not None:
            # 제목만 반복되는 경우임을 화면에서 알 수 있도록 메시지를 덧붙입니다.
            norm = best_html_result.get("normalized", {})
            if isinstance(norm, dict) and norm.get("articles"):
                msg = "\n\n[안내] 법제처 판례 HTML 상세조회가 현재 제목/요약 수준만 반환했습니다. 캐시 새로고침 후 다시 시도하거나, '여기에 열기'의 원문 새 탭을 확인해 주세요."
                try:
                    norm["articles"][0]["body"] = (norm["articles"][0].get("body") or "") + msg
                    norm["articles"][0]["segments"][0]["text"] = (norm["articles"][0]["segments"][0].get("text") or "") + msg
                except Exception:
                    pass
            return best_html_result
        if last_result.get("ok"):
            last_result["normalized"] = normalize_prec_html_detail("판례 본문을 찾지 못했습니다. 검색결과의 판례일련번호가 잘못 내려왔거나 법제처 HTML 본문 응답이 비어 있습니다.", law_id, mst, law_name)
        return last_result

    # v20: 자치법규는 ordinInfoR 본문을 조문별로 파싱해 인용 링크까지 함께 표시합니다.
    # (우리 ordin JSON 파싱은 조문을 1개로 합쳐버리고 인용 링크도 없습니다.)
    if api_target == "ordin" and mst:
        ord_norm = get_ordin_linked_detail(mst, law_name, refresh)
        if ord_norm and has_article_text(ord_norm):
            return {"ok": True, "normalized": ord_norm, "source": "ordinInfoR"}

    # 자치법규는 응답 필드명이 법령과 다릅니다.
    # JSON에서 조문이 비면 XML/HTML 방식으로 한 번 더 받아 원문이라도 표시합니다.
    trial_params = [{
        "target": api_target,
        "type": "JSON",
        "ID": law_id,
        "MST": mst,
        "efYd": re.sub(r"\D", "", efyd) if efyd else "",
        "JO": jo,
        "OC": get_oc(),
    }]
    if api_target == "ordin":
        # 목록 결과에 ID/MST 중 하나만 유효하게 내려오는 사례가 있어 분리 재시도합니다.
        trial_params.extend([
            {"target": api_target, "type": "JSON", "MST": mst, "OC": get_oc()},
            {"target": api_target, "type": "JSON", "ID": law_id, "OC": get_oc()},
            {"target": api_target, "type": "XML", "MST": mst, "OC": get_oc()},
            {"target": api_target, "type": "XML", "ID": law_id, "OC": get_oc()},
            {"target": api_target, "type": "HTML", "MST": mst, "OC": get_oc()},
            {"target": api_target, "type": "HTML", "ID": law_id, "OC": get_oc()},
        ])

    last_result: Dict[str, Any] = {"ok": False, "error": "상세 조회 실패"}
    for params in trial_params:
        # 빈 ID/MST 조합은 호출하지 않습니다.
        if api_target == "ordin" and not (params.get("ID") or params.get("MST")):
            continue
        result = request_law_api("lawService.do", params, refresh=refresh)
        last_result = result
        if not result.get("ok"):
            continue
        data = result.get("data", {})
        # lawService가 오류 HTML/스크립트(JSON 래핑)를 돌려주는 경우가 있습니다.
        # 이때는 본문으로 표시하지 않고 다음 fallback 조회를 시도합니다.
        raw_probe = ""
        if isinstance(data, dict):
            raw_probe = json.dumps(data, ensure_ascii=False)[:2000]
        else:
            raw_probe = str(data)[:2000]
        if any(bad in raw_probe for bad in ("XML 파싱중 오류", "Error", "일치하는 법령이 없습니다", "일치하는 자치법규가 없습니다")) and not ("조문내용" in raw_probe or "조내용" in raw_probe):
            last_result = result
            continue
        if isinstance(data, dict) and "raw" in data and str(params.get("type", "")).upper() == "XML":
            data = parse_xml_to_dict(str(data.get("raw", "")))
        if isinstance(data, dict) and "raw" in data and str(params.get("type", "")).upper() == "HTML":
            result["normalized"] = normalize_html_detail(str(data.get("raw", "")), target, law_id, mst)
        else:
            if api_target == "admrul":
                # v20.1: 행정규칙은 조문단위가 없어 일반 정규화가 실패하고
                # 원본 JSON 덤프로 떨어지던 문제를 전용 정규화로 해결합니다.
                result["normalized"] = normalize_admrul_detail(data if isinstance(data, dict) else {})
                if not has_article_text(result["normalized"]):
                    result["normalized"] = normalize_detail(data if isinstance(data, dict) else {})
            else:
                result["normalized"] = normalize_detail(data if isinstance(data, dict) else {})
        if has_article_text(result["normalized"]):
            return result
        # 별표만 있더라도 마지막 fallback용으로 보관합니다.
        last_result = result

    if last_result.get("ok"):
        data = last_result.get("data", {})
        raw_text = json.dumps(data, ensure_ascii=False, indent=2) if isinstance(data, (dict, list)) else str(data or "")
        last_result["normalized"] = normalize_html_detail(raw_text, target, law_id, mst)
    return last_result


def search_gijang_api(query: str, search: str, display: str, page: str, refresh: bool) -> Dict[str, Any]:
    """v20: 기장군 자치법규를 법제처 API org/sborg 코드로 직접 조회합니다.
    검색어를 비우면 기장군 전체 목록(API 기본 query=*)을 받습니다."""
    params = {
        "target": "ordin",
        "type": "JSON",
        "query": query,
        "search": search,
        "display": display,
        "page": page,
        "org": GIJANG_ORG,
        "sborg": GIJANG_SBORG,
        "efYd": request.args.get("efyd", ""),
        "OC": get_oc(),
    }
    result = request_law_api("lawSearch.do", params, refresh=refresh)
    if not result.get("ok"):
        return result
    result["normalized"] = normalize_search(result.get("data", {}))
    items = []
    for item in result["normalized"].get("items", []):
        item["target"] = "ordin_gijang"
        item["api_target"] = "ordin"
        item["target_label"] = TARGETS.get("ordin_gijang", "자치법규(기장군)")
        item = patch_item_identifiers(item, "ordin_gijang")
        items.append(item)
    result["normalized"]["items"] = items
    return result


def search_one_target(target: str, query: str, search: str, display: str, page: str, refresh: bool) -> Dict[str, Any]:
    if target == "ordin_gijang":
        # v20: API 직접조회를 우선하고, API 장애 시에만 기존 수동 목록으로 대체합니다.
        result = search_gijang_api(query, search, display, page, refresh)
        if result.get("ok"):
            return result
        fallback = search_gijang_manual(query, search, display, page)
        fallback["api_error"] = result.get("error", "")
        return fallback
    api_target = api_target_of(target)
    query_for_api = query
    params = {
        "target": api_target,
        "type": "JSON",
        "query": query_for_api,
        "search": search,
        "display": display,
        "page": page,
        "sort": request.args.get("sort", "efdes" if api_target in ("eflaw", "law") else ""),
        "nw": request.args.get("nw", "3") if api_target == "eflaw" else "",
        # v20: 시행일/공포일 범위 검색은 자치법규 목록조회도 지원합니다(가이드 확인).
        "efYd": request.args.get("efyd", "") if api_target in ("eflaw", "ordin") else "",
        "ancYd": request.args.get("ancyd", "") if api_target in ("eflaw", "ordin") else "",
        "date": request.args.get("date", "") if api_target == "eflaw" else "",
        "org": request.args.get("org", org_of(target)),
        "OC": get_oc(),
    }
    result = request_law_api("lawSearch.do", params, refresh=refresh)
    if not result.get("ok"):
        return result
    result["normalized"] = normalize_search(result.get("data", {}))
    filtered_items = []
    for item in result["normalized"].get("items", []):
        if not row_matches_target_alias(item, target):
            continue
        item["target"] = target
        item["api_target"] = api_target
        item["target_label"] = TARGETS.get(target, target)
        item = patch_item_identifiers(item, target)
        filtered_items.append(item)
    result["normalized"]["items"] = filtered_items
    return result


def title_lookup_in_target(target: str, law_name: str, refresh: bool = False) -> List[Dict[str, Any]]:
    result = search_one_target(target, law_name, "1", "10", "1", refresh)
    if not result.get("ok"):
        return []
    items = result.get("normalized", {}).get("items", [])
    wanted = normalize_law_name(law_name)
    exact = [x for x in items if normalize_law_name(x.get("name", "")) == wanted]
    if exact:
        return exact[:2]
    loose = [x for x in items if wanted in normalize_law_name(x.get("name", "")) or normalize_law_name(x.get("name", "")) in wanted]
    return (loose or items)[:2]


def interleave_rows_by_target(rows: List[Dict[str, Any]], targets: List[str]) -> List[Dict[str, Any]]:
    """v20: 여러 검색대상을 함께 선택했을 때 첫 대상이 결과 상위를 독식하지 않도록
    대상별로 한 건씩 번갈아 배치합니다."""
    if len(targets) <= 1 or not rows:
        return rows
    by_target: Dict[str, List[Dict[str, Any]]] = {}
    order: List[str] = []
    for r in rows:
        t = str(r.get("target", ""))
        if t not in by_target:
            by_target[t] = []
            order.append(t)
        by_target[t].append(r)
    queues = [by_target[t] for t in order]
    interleaved: List[Dict[str, Any]] = []
    while any(queues):
        for q_list in queues:
            if q_list:
                interleaved.append(q_list.pop(0))
    return interleaved


def pool_search(pools: Dict[str, List[str]], pool_name: str, targets: List[str], query: str, search: str, limit: int, refresh: bool) -> Dict[str, Any]:
    laws = pools.get(pool_name, [])
    rows: List[Dict[str, Any]] = []
    errors: List[str] = []
    seen = set()
    terms = split_terms(query)
    for law_name in laws:
        if len(rows) >= limit:
            break
        if search == "1" and terms and not any(t in law_name for t in terms):
            # 제목검색은 풀 이름 자체에 검색어가 들어간 경우 중심으로 표시
            continue
        for target in targets:
            if len(rows) >= limit:
                break
            try:
                candidates = title_lookup_in_target(target, law_name, refresh)
                for item in candidates:
                    sig = (item.get("target"), item.get("law_id"), item.get("mst"), item.get("name"))
                    if sig in seen:
                        continue
                    seen.add(sig)
                    item = dict(item)
                    item["pool_law"] = law_name
                    if search == "2":
                        item = enrich_item_with_matches(item, target, query, refresh)
                        if not item.get("matches"):
                            continue
                    rows.append(item)
                    if len(rows) >= limit:
                        break
            except Exception as e:
                errors.append(f"{law_name}/{TARGETS.get(target, target)}: {e}")
    return {"ok": True, "mode": "pool", "pool": pool_name, "items": rows, "count": len(rows), "errors": errors}



LAW_LIGHT_FONT_CONTROL_INJECTION_MARKER = "__LAW_LIGHT_TARGET_FONT_ZOOM_V12__"


def inject_law_light_font_zoom(html_text: str) -> str:
    """가벼운 Ctrl+휠 전용 글자 크기 조절 스크립트를 index.html에 삽입합니다.

    v8 핵심:
    - MutationObserver / 주기적 전역 스캔 / 툴바 없음
    - Ctrl+휠이 발생한 가장 가까운 스크롤 패널에만 글자 크기 적용
    - 조문 클릭으로 내부 내용이 다시 그려져도 스크롤 패널 루트의 CSS 변수는 유지
    - 하이라이트 hover/selected 상태에서만 글자색을 검정으로 보정
    """
    html_text = re.sub(
        r"\n?<!--\s*__LAW_DETAIL_FONT_ZOOM_V\d+__\s*-->\s*<style[^>]*>.*?</script>\s*",
        "\n",
        html_text,
        count=0,
        flags=re.IGNORECASE | re.DOTALL,
    )
    html_text = re.sub(
        r"\n?<!--\s*__LAW_DETAIL_PANEL_FONT_ZOOM_V\d+__\s*-->\s*<style[^>]*>.*?</script>\s*",
        "\n",
        html_text,
        count=0,
        flags=re.IGNORECASE | re.DOTALL,
    )
    html_text = re.sub(
        r"\n?<!--\s*__LAW_LIGHT_TARGET_FONT_ZOOM_V\d+__\s*-->\s*<style[^>]*>.*?</script>\s*",
        "\n",
        html_text,
        count=0,
        flags=re.IGNORECASE | re.DOTALL,
    )

    injection = r'''
<!-- __LAW_LIGHT_TARGET_FONT_ZOOM_V12__ -->
<style id="law-light-target-font-zoom-style-v12">
  .law-panel-font-zoom-toolbar,
  .gpt-font-zoom-toolbar,
  #law-detail-panel-font-zoom-style-v3,
  #law-detail-panel-font-zoom-style-v4,
  #law-detail-panel-font-zoom-style-v5,
  #law-detail-panel-font-zoom-style-v6,
  #law-detail-panel-font-zoom-style-v7 {
    display: none !important;
    visibility: hidden !important;
    pointer-events: none !important;
  }

  [data-gpt-lite-font-panel="1"] {
    --gpt-lite-font-size: 16px;
  }

  [data-gpt-lite-font-panel="1"] :where(
    div, span, p, li, td, th, article, section, pre, blockquote, strong, em, small, a
  ) {
    font-size: var(--gpt-lite-font-size) !important;
    line-height: calc(var(--gpt-lite-font-size) * 1.7) !important;
  }

  [data-gpt-lite-font-panel="1"] :where(button, input, textarea, select, option, label) {
    font-size: revert !important;
    line-height: revert !important;
  }

  /* 예전 스크립트가 붙였던 강제 검정 속성 무력화: 평소에는 원래 다크모드 글자색 유지 */
  [data-gpt-font-contrast="dark"],
  [data-gpt-font-contrast="light"] {
    color: inherit !important;
    text-shadow: inherit !important;
  }

  /* v12: 다크모드 hover 보정 범위를 조문(.unit) 단위로만 제한합니다.
     이전처럼 [class*=article]:hover 전체를 잡지 않으므로, 조 위에 마우스를 올려도
     articleWrap 전체 글자가 검정으로 바뀌지 않습니다. */
  [data-gpt-font-contrast="dark"],
  [data-gpt-font-contrast="light"] {
    color: inherit !important;
    text-shadow: inherit !important;
  }

  body.grayDark [data-gpt-lite-font-panel="1"] .articleWrap:hover,
  body.grayDark [data-gpt-lite-font-panel="1"] .article:hover {
    color: var(--text) !important;
  }

  body.grayDark [data-gpt-lite-font-panel="1"] .unit:not(.selected):hover {
    background: #434a54 !important;
    border-color: #667085 !important;
    color: #eef1f5 !important;
    box-shadow: none !important;
  }

  body.grayDark [data-gpt-lite-font-panel="1"] .unit:not(.selected):hover > :not(.unitActions):not(.copyUnit):not(.linkBtn),
  body.grayDark [data-gpt-lite-font-panel="1"] .unit:not(.selected):hover .unitLabel {
    color: inherit !important;
    text-shadow: none !important;
  }

  body.grayDark [data-gpt-lite-font-panel="1"] .unit:not(.selected):hover mark,
  body.grayDark [data-gpt-lite-font-panel="1"] mark {
    background: #ffe766 !important;
    color: #111827 !important;
    text-shadow: none !important;
  }

  body.grayDark [data-gpt-lite-font-panel="1"] .unit.selected,
  body.grayDark [data-gpt-lite-font-panel="1"] .unit.selected > :not(.unitActions):not(.copyUnit):not(.linkBtn) {
    background: #dcecff !important;
    color: #111827 !important;
    border-color: #9fc4ff !important;
    text-shadow: none !important;
  }

  body.grayDark [data-gpt-lite-font-panel="1"] .unit.selected .unitLabel,
  body.grayDark [data-gpt-lite-font-panel="1"] .unit.selected mark {
    color: #111827 !important;
    text-shadow: none !important;
  }
</style>
<script id="law-light-target-font-zoom-script-v12">
(function () {
  const MARK = "__LAW_LIGHT_TARGET_FONT_ZOOM_V12__";
  if (window[MARK]) return;
  window[MARK] = true;

  const DEFAULT_SIZE = 16;
  const MIN_SIZE = 12;
  const MAX_SIZE = 34;
  const STEP = 1;
  const panelSizes = new Map();

  function clamp(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return DEFAULT_SIZE;
    return Math.max(MIN_SIZE, Math.min(MAX_SIZE, n));
  }

  function visible(el) {
    if (!el || !el.isConnected || el.nodeType !== 1) return false;
    const r = el.getBoundingClientRect();
    if (r.width < 80 || r.height < 60) return false;
    const s = getComputedStyle(el);
    return s.display !== "none" && s.visibility !== "hidden" && Number(s.opacity || 1) !== 0;
  }

  function isScrollable(el) {
    if (!visible(el)) return false;
    const s = getComputedStyle(el);
    const overflow = String(s.overflowY || "") + " " + String(s.overflowX || "");
    return /auto|scroll|overlay/i.test(overflow) || el.scrollHeight > el.clientHeight + 60 || el.scrollWidth > el.clientWidth + 60;
  }

  function textOf(el) {
    return ((el && (el.innerText || el.textContent)) || "").replace(/\s+/g, " ").trim();
  }

  function isBadPanel(el) {
    const cls = String(el.id || "") + " " + String(el.className || "");
    const txt = textOf(el).slice(0, 220);
    return /(toolbar|header|footer|note|memo|bookmark|modal|popup|tooltip|관련\s*노트|노트|메모)/i.test(cls + " " + txt);
  }

  function nearestPanel(start) {
    let el = start && start.nodeType === 1 ? start : (start ? start.parentElement : null);
    let best = null;
    let steps = 0;
    while (el && el !== document.body && steps < 12) {
      if (isScrollable(el) && !isBadPanel(el)) {
        const r = el.getBoundingClientRect();
        if (r.width >= 140 && r.height >= 100) {
          best = el;
          break;
        }
      }
      el = el.parentElement;
      steps += 1;
    }
    return best;
  }

  function panelKey(panel) {
    const r = panel.getBoundingClientRect();
    const left = Math.round(r.left / 25) * 25;
    const top = Math.round(r.top / 25) * 25;
    const width = Math.round(r.width / 50) * 50;
    const height = Math.round(r.height / 50) * 50;
    return [left, top, width, height].join(":");
  }

  function cleanupOldToolbars() {
    try {
      document.querySelectorAll(".law-panel-font-zoom-toolbar, .gpt-font-zoom-toolbar").forEach(function (el) {
        el.remove();
      });
      document.querySelectorAll("[data-gpt-font-contrast]").forEach(function (el) {
        el.removeAttribute("data-gpt-font-contrast");
      });
    } catch (e) {}
  }

  function applySize(panel, size) {
    if (!panel) return;
    const safeSize = clamp(size);
    panel.setAttribute("data-gpt-lite-font-panel", "1");
    panel.style.setProperty("--gpt-lite-font-size", safeSize + "px");
    panel.__gptLiteFontSize = safeSize;
    panelSizes.set(panelKey(panel), safeSize);
  }

  function restoreKnownSize(panel) {
    if (!panel) return;
    const key = panelKey(panel);
    const saved = panel.__gptLiteFontSize || panelSizes.get(key);
    if (saved) applySize(panel, saved);
  }

  document.addEventListener("wheel", function (event) {
    if (!event.ctrlKey) return;
    const panel = nearestPanel(event.target);
    if (!panel) return;
    event.preventDefault();
    event.stopPropagation();
    cleanupOldToolbars();
    const current = clamp(panel.__gptLiteFontSize || panelSizes.get(panelKey(panel)) || DEFAULT_SIZE);
    applySize(panel, current + (event.deltaY < 0 ? STEP : -STEP));
  }, { passive: false, capture: true });

  document.addEventListener("pointerover", function (event) {
    const panel = nearestPanel(event.target);
    if (panel) restoreKnownSize(panel);
  }, { passive: true, capture: true });

  document.addEventListener("click", function (event) {
    const panel = nearestPanel(event.target);
    if (!panel) return;
    restoreKnownSize(panel);
    // 조문 클릭 직후 내부 내용만 다시 렌더링될 때 패널 CSS 변수를 즉시 재확인한다.
    requestAnimationFrame(function () { restoreKnownSize(panel); cleanupOldToolbars(); });
    setTimeout(function () { restoreKnownSize(panel); cleanupOldToolbars(); }, 80);
    setTimeout(function () { restoreKnownSize(panel); cleanupOldToolbars(); }, 250);
  }, { passive: true, capture: true });

  document.addEventListener("DOMContentLoaded", function () {
    cleanupOldToolbars();
    setTimeout(cleanupOldToolbars, 500);
    setTimeout(cleanupOldToolbars, 1500);
  });
})();
</script>
'''
    if re.search(r"</body\s*>", html_text, flags=re.IGNORECASE):
        return re.sub(r"</body\s*>", lambda m: injection + m.group(0), html_text, count=1, flags=re.IGNORECASE)
    return html_text + injection


def _find_index_html_for_light_zoom() -> Optional[Path]:
    # v20 전용 프론트가 있으면 우선 사용하고, 없으면 기존 static을 그대로 씁니다.
    for folder in _candidate_dashboard_dirs():
        for sub in ("static_v20", "static"):
            try:
                candidate = folder / sub / "index.html"
                if candidate.exists():
                    return candidate
            except Exception:
                pass
    return None


def _index_missing_response() -> Response:
    tried = []
    for folder in _candidate_dashboard_dirs():
        try:
            tried.append(str(folder / "static" / "index.html"))
        except Exception:
            pass
    body = (
        "<h2>static/index.html not found</h2>"
        "<p>현재 실행 폴더에 static 폴더가 없거나, 원래 대시보드 폴더를 찾지 못했습니다.</p>"
        "<p>가장 쉬운 해결: v8.1 파일을 원래 대시보드 폴더에 넣거나, 원래 폴더의 static 폴더를 현재 폴더로 복사하세요.</p>"
        "<pre>" + html.escape("\n".join(tried)) + "</pre>"
    )
    return Response(body, status=500, mimetype="text/html; charset=utf-8")


@app.route('/static/<path:filename>')
def static_files(filename: str) -> Response:
    return send_from_directory(BASE_DIR / "static", filename)


# ── 읽을것들(HTML 자료) 폰 열람 (2026-08-11) ─────────────────────────────
# 읽을것들 폴더는 GitHub(study-apps-Private / iljeong-sync readables)로 동기화되므로,
# 여기서 서빙하면 폰(Tailscale)에서 항상 최신 자료를 본다. ?m=1 이면 모바일 가독화 쉼 주입.
READABLES_BASES = [Path(r"C:\python_programs\읽을것들"),
                   Path(r"C:\todo_manual_dashboard\읽을것들")]

def _readables_base() -> Optional[Path]:
    for b in READABLES_BASES:
        if b.exists():
            return b
    return None

def _readables_resolve(rel: str) -> Optional[Path]:
    base = _readables_base()
    if base is None:
        return None
    rel = (rel or "").replace("\\", "/").strip("/")
    try:
        target = (base / rel).resolve() if rel else base.resolve()
        baser = base.resolve()
        if target != baser and baser not in target.parents:
            return None                     # 경로 탈출 차단
        return target
    except Exception:
        return None

_MOBILE_SHIM = """
<meta name="viewport" content="width=device-width,initial-scale=1" data-mshim="1">
<style data-mshim="1">
html{-webkit-text-size-adjust:100%}
body{max-width:100vw!important;overflow-x:hidden!important;margin:0 auto!important;
  padding:12px 14px calc(70px + env(safe-area-inset-bottom)) !important;box-sizing:border-box;
  font-size:var(--mshim-fs,16.5px)!important;line-height:1.85!important}
body *{box-sizing:border-box}
img,svg,video,canvas,iframe{max-width:100%!important;height:auto!important}
pre{white-space:pre-wrap!important;word-break:break-word;max-width:100%!important}
a,code{overflow-wrap:anywhere;word-break:break-all}
div,main,article,section,aside,nav,header,footer{width:auto!important;min-width:0!important;float:none!important;max-width:100%!important}
/* 표: 스크롤 래퍼(.mshimTw) 안에서는 원래 폭 유지 + 가로 스와이프 */
.mshimTw{overflow-x:auto!important;max-width:100%!important;-webkit-overflow-scrolling:touch;margin:10px 0}
.mshimTw table{width:max-content!important;max-width:none!important;display:table!important}
.mshimTw td,.mshimTw th{white-space:nowrap;padding:6px 10px}
.mshimTw td.mshimWide,.mshimTw th.mshimWide{white-space:normal!important;min-width:250px;max-width:75vw}
/* 사이드바(색인): 평소 숨김 → ☰ 목차 버튼으로 전체화면 오버레이 */
[data-mshim-sb]{display:none!important}
body.mshim-sb-open [data-mshim-sb]{display:block!important;position:fixed!important;inset:0!important;
  width:100vw!important;max-width:100vw!important;height:100vh!important;max-height:100vh!important;
  overflow:auto!important;background:#fff!important;color:#1a1d26!important;z-index:2147482999!important;
  padding:64px 20px 40px!important;font-size:16px!important;line-height:2!important}
body.mshim-sb-open [data-mshim-sb] a{display:block;padding:4px 0}
</style>
<script data-mshim="1">
(function(){
function fix(){
  var vw=window.innerWidth;
  /* 1) 표 → 스크롤 래퍼, 긴 셀은 줄바꿈 허용 */
  document.querySelectorAll('table').forEach(function(t){
    if(t.closest('.mshimTw')||t.closest('[data-mshim]'))return;
    var w=document.createElement('div');w.className='mshimTw';
    t.parentNode.insertBefore(w,t);w.appendChild(t);
    t.querySelectorAll('td,th').forEach(function(c){
      if((c.textContent||'').trim().length>55)c.classList.add('mshimWide');
    });
  });
  /* 2) 2단 이상 그리드/가로 플렉스 레이아웃 → 1단 세로 */
  document.querySelectorAll('body *').forEach(function(el){
    if(el.closest('[data-mshim]')||el.classList.contains('mshimTw'))return;
    var cs;try{cs=getComputedStyle(el);}catch(e){return;}
    if(cs.display==='grid'){
      var cols=(cs.gridTemplateColumns||'').split(' ').filter(function(x){return x&&x!=='none'});
      if(cols.length>1)el.style.setProperty('display','block','important');
    }else if(cs.display==='flex'&&cs.flexDirection.indexOf('row')===0){
      var kids=el.children.length,r=el.getBoundingClientRect();
      if(kids>1&&r.width>vw*0.9&&el.querySelector('table,article,section,h2,p'))
        el.style.setProperty('flex-direction','column','important');
    }
  });
  /* 3) 색인 사이드바 감지 → ☰ 목차 오버레이로 변환 */
  var sb=null;
  document.querySelectorAll('body *').forEach(function(el){
    if(sb||el.closest('[data-mshim]'))return;
    var cs;try{cs=getComputedStyle(el);}catch(e){return;}
    var r=el.getBoundingClientRect();
    if((cs.position==='fixed'||cs.position==='sticky')&&r.height>window.innerHeight*0.45&&
       r.width>90&&r.width<vw*0.85&&el.querySelectorAll('a').length>=3)sb=el;
  });
  if(!sb){
    var cands=document.querySelectorAll('nav,aside,[class*="sidebar"],[class*="sideNav"],[class*="side-nav"],[id*="sidebar"],[id*="toc"],[class*="toc"],[class*="index"]');
    for(var i=0;i<cands.length;i++){
      var c=cands[i];if(c.closest('[data-mshim]'))continue;
      var rr=c.getBoundingClientRect(),cc;try{cc=getComputedStyle(c);}catch(e){continue;}
      var anchors=c.querySelectorAll('a[href^="#"]').length||c.querySelectorAll('a').length;
      /* 자체 반응형이 모바일에서 숨겨버린 색인(display:none)도 목차로 되살린다 */
      if(anchors>=4&&((rr.height>260&&rr.width<vw*0.9)||cc.display==='none')){sb=c;break;}
    }
  }
  if(sb){
    sb.setAttribute('data-mshim-sb','1');
    var btn=document.createElement('button');
    btn.setAttribute('data-mshim','1');btn.textContent='\\u2630 \\ubaa9\\ucc28';
    btn.style.cssText='position:fixed;left:12px;top:calc(env(safe-area-inset-top) + 10px);z-index:2147483000;height:40px;border-radius:20px;border:0;background:#3b47c4;color:#fff;font-weight:700;font-size:13.5px;padding:0 14px;box-shadow:0 4px 12px rgba(0,0,0,.3)';
    btn.onclick=function(){document.body.classList.toggle('mshim-sb-open');};
    document.body.appendChild(btn);
    sb.addEventListener('click',function(e){
      if(e.target.closest('a'))setTimeout(function(){document.body.classList.remove('mshim-sb-open');},80);
    });
  }
  /* 4) 남은 가로 넘침 요소 개별 봉합 */
  setTimeout(function(){
    var lim=document.documentElement.clientWidth+2;
    document.querySelectorAll('body *').forEach(function(el){
      if(el.closest('.mshimTw')||el.closest('[data-mshim]'))return;
      if(el.scrollWidth>lim&&el.clientWidth>lim-4){
        el.style.setProperty('max-width','100%','important');
        el.style.setProperty('overflow-x','auto','important');
      }
    });
  },120);
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',fix);else fix();
})();
</script>
<button data-mshim="1" onclick="history.back()" style="position:fixed;left:12px;bottom:calc(12px + env(safe-area-inset-bottom));z-index:2147483000;height:46px;border-radius:23px;border:0;background:#1d2452;color:#fff;font-weight:800;font-size:14px;padding:0 16px;box-shadow:0 4px 12px rgba(0,0,0,.3)">← 목록</button>
<div data-mshim="1" style="position:fixed;right:12px;bottom:calc(12px + env(safe-area-inset-bottom));z-index:2147483000;display:flex;gap:8px">
<button onclick="(function(){var r=document.documentElement,v=parseFloat(getComputedStyle(r).getPropertyValue('--mshim-fs'))||16.5;r.style.setProperty('--mshim-fs',Math.max(13,v-1.5)+'px')})()" style="width:46px;height:46px;border-radius:50%;border:0;background:#3b47c4;color:#fff;font-weight:800;font-size:15px;box-shadow:0 4px 12px rgba(0,0,0,.3)">A-</button>
<button onclick="(function(){var r=document.documentElement,v=parseFloat(getComputedStyle(r).getPropertyValue('--mshim-fs'))||16.5;r.style.setProperty('--mshim-fs',Math.min(26,v+1.5)+'px')})()" style="width:46px;height:46px;border-radius:50%;border:0;background:#3b47c4;color:#fff;font-weight:800;font-size:15px;box-shadow:0 4px 12px rgba(0,0,0,.3)">A+</button>
</div>
"""

_READ_TITLE_CACHE: Dict[str, Tuple[float, str]] = {}   # rel -> (mtime, title)

def _readable_title(p: Path, rel: str) -> str:
    """HTML의 <title>에서 제목 추출(캐시). 없으면 파일명."""
    try:
        mt = p.stat().st_mtime
        hit = _READ_TITLE_CACHE.get(rel)
        if hit and hit[0] == mt:
            return hit[1]
        title = ""
        if p.suffix.lower() in (".html", ".htm"):
            head = p.read_text(encoding="utf-8", errors="replace")[:8192]
            m = re.search(r"<title[^>]*>(.*?)</title>", head, re.I | re.S)
            if m:
                title = html.unescape(re.sub(r"\s+", " ", m.group(1))).strip()
        if not title:
            title = re.sub(r"\.(html?|pdf|md)$", "", p.name, flags=re.I)
        _READ_TITLE_CACHE[rel] = (mt, title)
        return title
    except Exception:
        return p.name

# 글자크기 위젯 — 읽을것들/_gather.py 의 FONT_WIDGET 과 동일본.
# (한쪽만 고치면 파일 자체 위젯과 서버 주입분이 어긋나 두 개가 겹쳐 보인다)
_ZOOM_WIDGET = r"""<!-- font-size-widget v2: 폰 터치 대응(40px 버튼) · 브라우저 줌과 무관 · 페이지별 저장 -->
<script>
(function(){
if(window.__fontWidget)return;window.__fontWidget=1;
var KEY='pageZoom:'+location.host+location.pathname;
function load(){try{return parseFloat(localStorage.getItem(KEY))||1;}catch(e){return 1;}}
function save(v){try{localStorage.setItem(KEY,v);}catch(e){}}
var z=load(),disp,box,base=0;
var useZoom=!!(window.CSS&&CSS.supports&&CSS.supports('zoom','1.5'));
function clamp(v){return Math.min(3,Math.max(0.5,Math.round(v*100)/100));}
function apply(){
 var b=document.body;if(!b)return;
 if(useZoom){b.style.zoom=z;}
 else{if(!base)base=parseFloat(getComputedStyle(b).fontSize)||16;b.style.fontSize=(base*z).toFixed(2)+'px';}
 save(z);if(disp)disp.textContent=Math.round(z*100)+'%';}
function nudge(d){z=clamp(z+d);apply();}
function ui(){
 box=document.createElement('div');
 box.setAttribute('role','group');box.setAttribute('aria-label','글자 크기');
 box.style.cssText='position:fixed;right:calc(10px + env(safe-area-inset-right,0px));'
  +'bottom:calc(10px + env(safe-area-inset-bottom,0px));z-index:2147483647;display:flex;gap:2px;'
  +'align-items:center;background:rgba(20,22,30,.9);border:1px solid rgba(255,255,255,.28);'
  +'border-radius:24px;padding:3px 5px;font:14px/1 "Segoe UI",system-ui,sans-serif;color:#eee;'
  +'user-select:none;-webkit-user-select:none;touch-action:manipulation;box-shadow:0 2px 10px rgba(0,0,0,.35)';
 function btn(t,f,ttl){
  var e=document.createElement('button');
  e.type='button';e.textContent=t;e.title=ttl;e.setAttribute('aria-label',ttl);
  e.style.cssText='background:none;border:none;color:#eee;font:inherit;font-size:20px;width:40px;'
   +'height:40px;line-height:40px;cursor:pointer;padding:0;border-radius:20px;touch-action:manipulation;'
   +'-webkit-tap-highlight-color:rgba(255,255,255,.25)';
  e.addEventListener('click',function(ev){ev.preventDefault();f();});
  return e;}
 box.appendChild(btn('\u2212',function(){nudge(-0.1);},'글자 작게'));
 disp=document.createElement('button');
 disp.type='button';disp.title='기본 크기(100%)로';disp.setAttribute('aria-label','기본 크기로');
 disp.style.cssText='background:none;border:none;color:#eee;font:inherit;min-width:48px;height:40px;'
  +'text-align:center;cursor:pointer;padding:0;touch-action:manipulation';
 disp.addEventListener('click',function(ev){ev.preventDefault();z=1;apply();});
 box.appendChild(disp);
 box.appendChild(btn('\uFF0B',function(){nudge(0.1);},'글자 크게'));
 // 마우스가 있는 기기에서만 옅게 — 폰(hover 없음)에서는 항상 또렷하게 보인다
 if(window.matchMedia&&matchMedia('(hover:hover)').matches){
  box.style.opacity='.35';box.style.transition='opacity .15s';
  box.addEventListener('mouseenter',function(){box.style.opacity='1';});
  box.addEventListener('mouseleave',function(){box.style.opacity='.35';});}
 // body 확대의 영향을 받지 않도록 <html> 에 붙인다 (역-zoom 보정 불필요)
 (document.documentElement||document.body).appendChild(box);
 apply();}
addEventListener('wheel',function(e){if(!e.ctrlKey)return;e.preventDefault();nudge(e.deltaY<0?0.1:-0.1);},{passive:false});
addEventListener('keydown',function(e){if(!e.ctrlKey||e.altKey)return;
 if(e.key==='='||e.key==='+'){e.preventDefault();nudge(0.1);}
 else if(e.key==='-'){e.preventDefault();nudge(-0.1);}
 else if(e.key==='0'){e.preventDefault();z=1;apply();}});
if(document.body)ui();else addEventListener('DOMContentLoaded',ui);
})();
</script>
"""


@app.route("/readables_index")
def readables_index() -> Response:
    """읽을것들 전체 목록(제목 나열) — 요청 시마다 폴더를 읽어 생성하므로 항상 최신.
    폰 판례리더의 📚 자료 탭이 이 페이지를 연다. PC 브라우저에서도 그대로 보기 좋게."""
    base = _readables_base()
    if base is None:
        return Response("<h1>읽을것들 폴더 없음</h1>", status=404, mimetype="text/html; charset=utf-8")

    groups: List[Tuple[str, List[Dict[str, Any]]]] = []
    all_items: List[Dict[str, Any]] = []

    def collect(d: Path, relroot: str) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        try:
            entries = sorted(d.iterdir(), key=lambda x: (x.is_file(), x.name))
        except Exception:
            return items
        for e in entries:
            n = e.name
            if n.startswith(".") or n.startswith("_") or n.endswith((".py", ".bat")):
                continue
            rel = (relroot + "/" + n) if relroot else n
            if e.is_dir():
                items += collect(e, rel)
            elif e.suffix.lower() in (".html", ".htm", ".pdf", ".md"):
                if n.lower() in ("index.html", "readme.md"):
                    continue
                st = e.stat()
                sub = relroot.split("/", 1)[1] if "/" in relroot else ""
                items.append({"rel": rel, "name": n, "title": _readable_title(e, rel),
                              "sub": sub, "size": st.st_size, "mtime": st.st_mtime,
                              "kind": e.suffix.lower().lstrip(".")})
        return items

    try:
        for e in sorted(base.iterdir(), key=lambda x: (x.is_file(), x.name)):
            n = e.name
            if e.is_dir() and not n.startswith((".", "_")):
                items = collect(e, n)
                if items:
                    groups.append((n, items))
                    all_items += items
    except Exception:
        pass

    def hsize(v: int) -> str:
        return "%.1f MB" % (v / 1048576) if v >= 1048576 else "%d KB" % max(1, round(v / 1024))

    def card(it: Dict[str, Any]) -> str:
        href = "/readables/" + "/".join(urlencode({"": s})[1:] for s in it["rel"].split("/"))
        if it["kind"] in ("html", "htm"):
            href += "?m=1"
        sub = f'<span class="sub">{html.escape(it["sub"])}</span>' if it["sub"] else ""
        return (f'<a class="card" href="{href}" data-hay="{html.escape((it["title"] + " " + it["rel"]).lower())}">'
                f'<div class="t">{html.escape(it["title"])}</div>'
                f'<div class="m">{sub}<span class="k k-{it["kind"]}">{it["kind"].upper()}</span>'
                f'<span>{hsize(it["size"])}</span><span>{datetime.fromtimestamp(it["mtime"]).strftime("%Y-%m-%d")}</span></div></a>')

    recent = sorted(all_items, key=lambda x: -x["mtime"])[:8]
    parts: List[str] = []
    parts.append("""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>읽을것들 목록</title>
<link rel="manifest" href="/readables_manifest.json">
<link rel="apple-touch-icon" href="/static/m_icons/read_192.png">
<meta name="theme-color" content="#0f8a66"><style>
:root{--bg:#f4f5f8;--card:#fff;--ink:#1a1d26;--dim:#6a7183;--line:#e5e7ee;--acc:#3b47c4;--acc-soft:#eceffc}
@media (prefers-color-scheme:dark){:root{--bg:#15171d;--card:#1e2129;--ink:#e8eaf0;--dim:#98a0b3;--line:#30343f;--acc:#8b95f2;--acc-soft:#272c45}}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{margin:0;background:var(--bg);color:var(--ink);font-family:'Pretendard',-apple-system,'Noto Sans KR','Malgun Gothic',sans-serif;
  font-size:16px;line-height:1.7;padding:0 0 60px}
.head{background:linear-gradient(135deg,#1d2452,#3b47c4);color:#fff;padding:calc(env(safe-area-inset-top) + 22px) 18px 18px}
.head h1{margin:0;font-size:21px}.head .mini{opacity:.85;font-size:12.5px;margin-top:3px}
.wrap{max-width:820px;margin:0 auto;padding:0 14px}
#q{width:100%;font-size:16px;padding:12px 15px;border-radius:13px;border:1.5px solid var(--line);
  background:var(--card);color:var(--ink);outline:none;margin:14px 0 4px}
h2{font-size:14px;color:var(--dim);font-weight:800;margin:22px 2px 6px;letter-spacing:.3px}
.card{display:block;background:var(--card);border:1px solid var(--line);border-radius:15px;padding:13px 16px;
  margin:9px 0;text-decoration:none;color:inherit}
.card:active{transform:scale(.985)}
.card .t{font-weight:700;font-size:16px;line-height:1.5;word-break:keep-all}
.card .m{color:var(--dim);font-size:12.5px;margin-top:4px;display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.sub{background:var(--acc-soft);color:var(--acc);border-radius:6px;padding:0 7px;font-weight:700}
.k{border-radius:6px;padding:0 6px;font-weight:800;font-size:11px}
.k-html,.k-htm{background:#e9f7f1;color:#0f8a66}.k-pdf{background:#fdecec;color:#c0392b}.k-md{background:#fdf3e0;color:#b45309}
@media (prefers-color-scheme:dark){.k-html,.k-htm{background:#1f3229;color:#4cc9a4}.k-pdf{background:#3a2424;color:#e08b84}.k-md{background:#33291a;color:#e5a558}}
.none{color:var(--dim);text-align:center;padding:30px 0;display:none}
</style></head><body>
<div class="head"><h1>📚 읽을것들</h1><div class="mini">열 때마다 자동 갱신 · 문서를 열면 폰 가독화가 적용됩니다</div></div>
<div class="wrap">
<input id="q" placeholder="제목으로 거르기…" oninput="flt(this.value)">
<div class="none" id="none">일치하는 문서가 없습니다</div>""")
    parts.append("<h2>🕘 최근 갱신</h2>" + "".join(card(x) for x in recent))
    for gname, items in groups:
        disp = re.sub(r"^\d+_", "", gname)
        parts.append(f"<h2>{html.escape(disp)} · {len(items)}</h2>")
        parts.append("".join(card(x) for x in sorted(items, key=lambda x: (x["sub"], x["name"]))))
    parts.append("""</div><script>
function flt(q){q=(q||'').trim().toLowerCase();let n=0;
document.querySelectorAll('.card').forEach(c=>{const on=!q||(c.dataset.hay||'').indexOf(q)>=0;c.style.display=on?'':'none';if(on)n++;});
document.querySelectorAll('h2').forEach(h=>{let el=h.nextElementSibling,any=false;
while(el&&el.classList&&el.classList.contains('card')){if(el.style.display!=='none')any=true;el=el.nextElementSibling;}
h.style.display=any?'':'none';});
document.getElementById('none').style.display=n?'none':'block';}
</script>""" + _ZOOM_WIDGET + """</body></html>""")
    resp = Response("".join(parts), mimetype="text/html; charset=utf-8")
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.route("/api/readables_list")
def api_readables_list() -> Response:
    rel = request.args.get("path", "")
    target = _readables_resolve(rel)
    if target is None or not target.is_dir():
        return jsonify({"ok": False, "error": "폴더 없음"}), 404
    dirs: List[Dict[str, Any]] = []
    files: List[Dict[str, Any]] = []
    try:
        for e in sorted(target.iterdir(), key=lambda x: (x.is_file(), x.name)):
            n = e.name
            if n.startswith(".") or n.startswith("_") or n.endswith((".py", ".bat")):
                continue
            if e.is_dir():
                try:
                    cnt = sum(1 for c in e.iterdir()
                              if c.is_dir() or c.suffix.lower() in (".html", ".htm", ".pdf", ".md"))
                except Exception:
                    cnt = 0
                dirs.append({"name": n, "count": cnt})
            elif e.suffix.lower() in (".html", ".htm", ".pdf", ".md"):
                st = e.stat()
                files.append({"name": n, "size": st.st_size,
                              "mtime": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d")})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
    return jsonify({"ok": True, "path": rel, "dirs": dirs, "files": files})

@app.route("/readables/<path:relpath>")
def readables_file(relpath: str) -> Response:
    target = _readables_resolve(relpath)
    if target is None or not target.is_file():
        return Response("<h1>파일 없음</h1>", status=404, mimetype="text/html; charset=utf-8")
    if target.suffix.lower() in (".html", ".htm") and request.args.get("m") == "1":
        try:
            txt = target.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return send_file(str(target))
        shim = _MOBILE_SHIM
        if re.search(r'name=["\']viewport["\']', txt, re.I):
            shim = shim.replace('<meta name="viewport" content="width=device-width,initial-scale=1" data-mshim="1">', "")
        low = txt.lower()
        i = low.find("</head>")
        if i >= 0:
            out = txt[:i] + shim + txt[i:]
        else:
            j = low.find("<body")
            if j >= 0:
                k = low.find(">", j)
                out = txt[:k + 1] + shim + txt[k + 1:] if k >= 0 else shim + txt
            else:
                out = shim + txt
        resp = Response(out, mimetype="text/html; charset=utf-8")
        resp.headers["Cache-Control"] = "no-store"
        return resp
    if target.suffix.lower() in (".html", ".htm"):
        # PC 열람: 페이지 독립 줌 위젯 주입 (파일 원본은 건드리지 않음)
        try:
            txt = target.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return send_file(str(target))
        if "__fontWidget" not in txt and "__zoomWidget" not in txt:
            low = txt.lower()
            i = low.rfind("</body>")
            txt = txt[:i] + _ZOOM_WIDGET + txt[i:] if i >= 0 else txt + _ZOOM_WIDGET
        resp = Response(txt, mimetype="text/html; charset=utf-8")
        resp.headers["Cache-Control"] = "no-store"
        return resp
    return send_file(str(target))


# ── PWA 매니페스트 (폰 홈 화면에 '앱 설치' 지원, 2026-08-11) ──
def _manifest(name, short, start, theme, icon_prefix):
    return jsonify({
        "name": name, "short_name": short, "start_url": start, "scope": "/",
        "display": "standalone", "background_color": "#f4f5f8", "theme_color": theme,
        "icons": [{"src": f"/static/m_icons/{icon_prefix}_192.png", "sizes": "192x192", "type": "image/png"},
                  {"src": f"/static/m_icons/{icon_prefix}_512.png", "sizes": "512x512", "type": "image/png"}],
    })

@app.route("/m_manifest.json")
def m_manifest() -> Response:
    return _manifest("판례 리더", "판례리더", "/m", "#1d2452", "prec")

@app.route("/readables_manifest.json")
def readables_manifest() -> Response:
    return _manifest("읽을것들 리더", "읽을것들", "/readables_index", "#0f8a66", "read")


@app.route("/m")
def mobile_page() -> Response:
    """폰 전용 판례 리더 (2026-08-09). Tailscale로 폰에서 http://<PC주소>:6155/m 접속."""
    p = BASE_DIR / "static_v20" / "mobile.html"
    if not p.exists():
        return Response("<h1>mobile.html 없음</h1>", status=404, mimetype="text/html; charset=utf-8")
    resp = Response(p.read_text(encoding="utf-8"), mimetype="text/html; charset=utf-8")
    resp.headers["Cache-Control"] = "no-store, no-cache, max-age=0, must-revalidate"
    return resp


def _serve_light_zoom_index() -> Response:
    index_path = _find_index_html_for_light_zoom()
    if not index_path:
        return _index_missing_response()
    try:
        html_text = index_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        html_text = index_path.read_text(encoding="utf-8-sig")
    resp = Response(inject_law_light_font_zoom(html_text), mimetype="text/html; charset=utf-8")
    resp.headers["Cache-Control"] = "no-store, no-cache, max-age=0, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp

@app.route("/")
@app.route("/index.html")
def index() -> Response:
    return _serve_light_zoom_index()


@app.route("/open")
def open_deeplink():
    """외부 문서(학습 HTML 리더 등)용 범용 딥링크. 노트를 남길 수 있도록
    law.go.kr 대신 대시보드 뷰어로 연다.
      /open?law=지방세법&jo=제20조   → 현행법령을 컴팩트 창으로 열고 해당 조문으로 점프
      /open?case=2013두2778          → 판례DB에서 사건번호를 찾아 판례 본문을 연다
    해석 실패 시에만 law.go.kr로 폴백한다."""
    case = (request.args.get("case") or "").strip()
    law = (request.args.get("law") or "").strip()
    jo = (request.args.get("jo") or "").strip()
    row = None
    if case:
        con = _prec_con()
        if con is not None:
            try:
                norm = case.replace(" ", "")
                r = con.execute(
                    "SELECT prec_id, case_no, case_name FROM precedent "
                    "WHERE REPLACE(case_no,' ','') LIKE ? ORDER BY decided DESC LIMIT 1",
                    (f"%{norm}%",),
                ).fetchone()
                if r is not None:
                    row = {"target": "prec", "law_id": r["prec_id"], "mst": r["prec_id"],
                           "name": f"{r['case_no']} {r['case_name'] or ''}".strip(),
                           "target_label": "판례"}
            finally:
                con.close()
        if row is None:
            return redirect("https://www.law.go.kr/precSc.do?menuId=7&subMenuId=47&query=" + quote(case))
    elif law:
        result = search_one_target("eflaw", law, "1", "15", "1", False)
        items = ((result.get("normalized") or {}).get("items") or []) if result.get("ok") else []
        best = None
        for it in items:
            if str(it.get("name") or "").replace(" ", "") == law.replace(" ", ""):
                best = it
                break
        best = best or (items[0] if items else None)
        if best is not None:
            row = {"target": best.get("target") or "eflaw", "law_id": str(best.get("law_id") or ""),
                   "mst": str(best.get("mst") or ""), "name": best.get("name") or law,
                   "effective_date": str(best.get("effective_date") or ""),
                   "target_label": best.get("target_label") or "현행법령"}
            if jo:
                row["match"] = {"article_number": jo}
        else:
            return redirect("https://www.law.go.kr/" + quote("법령") + "/" + quote(law)
                            + (("/" + quote(jo)) if jo else ""))
    if row is None:
        return redirect("/")
    return redirect("/?openrow=" + quote(json.dumps(row, ensure_ascii=False)))


@app.route("/api/config")
def api_config() -> Response:
    return jsonify({
        "app_title": APP_TITLE,
        "has_env_oc": bool(os.getenv("OPENLAW_OC")),
        "targets": TARGETS,
        "case_targets": sorted(CASE_TARGETS | {"prec"}),
        "byl_targets": sorted(BYL_TARGETS),
        "quick_laws": QUICK_LAWS,
        "quick_keywords": QUICK_KEYWORDS,
        "pools": load_pools(),
    })


# ---------------------------------------------------------------------------
# 판례 ↔ 현행 조문 연결 인덱스 (scraper/build_prec_index.py 가 생성한 prec_index.db)
# ---------------------------------------------------------------------------
PREC_INDEX_DB = DATA_DIR / "prec_index.db"


def _prec_con() -> Optional[sqlite3.Connection]:
    if not PREC_INDEX_DB.exists():
        return None
    con = sqlite3.connect(PREC_INDEX_DB)
    con.row_factory = sqlite3.Row
    return con


def _norm_article(s: str) -> str:
    m = re.search(r"제?\s*(\d+)\s*조(?:\s*의\s*(\d+))?", s or "")
    if m:
        return "제" + m.group(1) + "조" + ("의" + m.group(2) if m.group(2) else "")
    return (s or "").strip()


def _match_prec_law(con: sqlite3.Connection, law_name: str) -> str:
    target = normalize_law_name(law_name or "")
    laws = [r["law"] for r in con.execute("SELECT DISTINCT law FROM article_meta")]
    for lw in laws:
        if normalize_law_name(lw) == target:
            return lw
    for lw in laws:  # 부분일치(예: '지방세법(시행일)')
        if lw and lw in (law_name or ""):
            return lw
    return ""


def _prec_row(r: sqlite3.Row) -> Dict[str, Any]:
    return {
        "prec_id": r["prec_id"], "case_name": r["case_name"], "case_no": r["case_no"],
        "court": r["court"], "decided": r["decided"], "ptype": r["ptype"],
        "summary": r["summary"], "link": r["link"], "art": r["art"],
        "is_old": r["is_old"], "via_old_art": r["via_old_art"], "confidence": r["confidence"],
    }


_PREC_SELECT = (
    "SELECT ap.art AS art, ap.is_old, ap.via_old_art, ap.confidence, "
    "p.prec_id, p.case_name, p.case_no, p.court, p.decided, p.ptype, p.summary, p.link "
    "FROM article_prec ap JOIN precedent p ON p.prec_id=ap.prec_id WHERE "
)


@app.route("/api/article_precedents")
def api_article_precedents() -> Response:
    """현행 조문 1개에 연결된 판례를 직접/근접/관련 3단으로 반환(최신 선고일 순)."""
    con = _prec_con()
    if con is None:
        return jsonify({"ok": True, "available": False, "direct": [], "near": [], "related": []})
    law = _match_prec_law(con, request.args.get("law", ""))
    art = _norm_article(request.args.get("art", ""))
    out: Dict[str, Any] = {"ok": True, "available": True, "law": law, "art": art,
                           "direct": [], "near": [], "related": []}
    if not law or not art:
        con.close()
        return jsonify(out)
    meta = con.execute("SELECT semok, seq FROM article_meta WHERE law=? AND art=?", (law, art)).fetchone()
    out["direct"] = [_prec_row(r) for r in
                     con.execute(_PREC_SELECT + "ap.law=? AND ap.art=? ORDER BY p.decided DESC", (law, art))]
    if meta is not None:
        semok, seq = meta["semok"], meta["seq"]
        out["semok"] = semok
        near_q = ("ap.law=? AND ap.art!=? AND ap.art IN "
                  "(SELECT art FROM article_meta WHERE law=? AND semok=? AND ABS(seq-?)<=2) "
                  "ORDER BY p.decided DESC")
        out["near"] = [_prec_row(r) for r in
                       con.execute(_PREC_SELECT + near_q, (law, art, law, semok, seq))]
        rel_q = ("ap.law=? AND ap.art!=? AND ap.art IN "
                 "(SELECT art FROM article_meta WHERE law=? AND semok=? AND ABS(seq-?)>2) "
                 "ORDER BY p.decided DESC")
        out["related"] = [_prec_row(r) for r in
                          con.execute(_PREC_SELECT + rel_q, (law, art, law, semok, seq))]
    con.close()
    out["counts"] = {k: len(out[k]) for k in ("direct", "near", "related")}
    return jsonify(out)


@app.route("/api/article_prec_counts")
def api_article_prec_counts() -> Response:
    """법령 1개의 조문별 직접 판례 수(인라인 ⚖ 배지용)."""
    con = _prec_con()
    if con is None:
        return jsonify({"ok": True, "available": False, "counts": {}})
    law = _match_prec_law(con, request.args.get("law", ""))
    counts: Dict[str, int] = {}
    if law:
        for r in con.execute(
                "SELECT art, COUNT(DISTINCT prec_id) c FROM article_prec WHERE law=? GROUP BY art", (law,)):
            counts[r["art"]] = r["c"]
    con.close()
    return jsonify({"ok": True, "available": True, "law": law, "counts": counts})


# ---------------------------------------------------------------------------
# olta(질의응답+지방세상담) ↔ 조문 연결 (build_olta_index.py 가 만든 article_olta/olta_post)
# ---------------------------------------------------------------------------
# 크롤 텍스트는 get_text("\n") 방식이라 원문 인라인 태그(법령 인용 토큰: 제/7/조/괄호 등)
# 경계마다 줄바꿈이 들어가 있음 → DB 원본은 그대로 두고 표시 직전에 문장으로 재결합한다.
_ORF_OPEN = "(「『[{<‘“"          # 여는 괄호·따옴표: 뒤 줄바꿈 무공백 결합
_ORF_CLOSE = ")」』]}>’”,.·;:!?%~"  # 닫는 괄호·문장부호: 앞 줄바꿈 무공백 결합
_ORF_LIST = re.compile(r"^(\d{1,3}\s*[.)]\s|[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳㉑㉒㉓㉔㉕]"
                       r"|[-•*※▶▷◆□■○◦☞]|[가나다라마바사아자차카타파하]\s*[.)]\s)")
_ORF_UNIT = re.compile(r"^(조의\s*\d|조제|[조항호목편장절관년월일억만천원명건회차퍼])")
_ORF_JOSA = re.compile(r"^(으로|이라|부터|까지|[가이을를은는과와의에로라란만도])([\s,.]|[가-힣]|$)")
_ORF_SENT_END = ".?!:;。"


def _orf_join(prev: str, cur: str) -> Optional[str]:
    """prev·cur 줄 사이 줄바꿈 처리: None=유지, ''=무공백 결합, ' '=공백 결합."""
    p, c = prev[-1], cur[0]
    if p in _ORF_OPEN:
        return ""
    if _ORF_LIST.match(cur):  # 번호 목록·항 기호는 새 줄 유지
        return None
    if c in _ORF_CLOSE:
        return ""
    if c in "\"'":
        # 따옴표: 현재 문단 내 개수 홀수면 닫는 것 → 무공백, 짝수면 여는 것 → 공백
        return "" if prev.count(c) % 2 == 1 else " "
    if p in "\"'":
        if prev.count(p) % 2 == 1:  # 방금 연 따옴표
            return ""
        return "" if _ORF_JOSA.match(cur) else " "
    if p == "제" or prev.endswith("조제") or prev.endswith("조의"):
        return ""
    if p.isdigit() and _ORF_UNIT.match(cur):
        return ""
    if c == "(" and p not in _ORF_SENT_END:
        return ""
    if p in _ORF_CLOSE and _ORF_JOSA.match(cur):
        return ""
    if re.search(r"(^|\s)\d{1,3}[.)]$", prev):  # 줄 끝 목록 번호는 내용과 결합
        return " "
    if p in _ORF_SENT_END:
        return None
    if len(prev) <= 12 or len(cur) <= 12:  # 짧은 조각 = 끊긴 인라인 토큰
        return " "
    return None


def _olta_reflow(t: Optional[str]) -> str:
    """olta 크롤 텍스트의 조각난 줄바꿈을 표시용으로 재결합."""
    if not t or "\n" not in t:
        return t or ""
    out: List[str] = []
    for ln in (s.strip() for s in t.split("\n")):
        if not ln:
            if out and out[-1] != "":
                out.append("")
            continue
        if not out or out[-1] == "":
            out.append(ln)
            continue
        sep = _orf_join(out[-1], ln)
        if sep is None:
            out.append(ln)
        else:
            out[-1] = out[-1] + sep + ln
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out)


def _olta_card(r: sqlite3.Row) -> Dict[str, Any]:
    snip = _olta_reflow(r["attach_text"] or r["body_text"] or "")
    snip = re.sub(r"\s+", " ", snip).strip()[:160]
    return {
        "board": r["board"], "ntt_id": r["ntt_id"], "category": r["category"],
        "title": r["title"], "created_at": r["created_at"], "author": r["author"],
        "answer_count": r["answer_count"], "snippet": snip,
        "board_label": "질의응답" if r["board"] == "qa" else "지방세상담",
    }


_OLTA_SEL = (
    "SELECT op.board, op.ntt_id, op.category, op.title, op.author, op.created_at, "
    "op.answer_count, op.body_text, op.attach_text "
    "FROM article_olta ao JOIN olta_post op ON op.board=ao.board AND op.ntt_id=ao.ntt_id WHERE "
)


@app.route("/api/article_olta")
def api_article_olta() -> Response:
    """현행 조문에 연결된 질의응답+지방세상담(구분없이 합쳐) 직접/근접/관련 반환."""
    con = _prec_con()
    if con is None:
        return jsonify({"ok": True, "available": False, "direct": [], "near": [], "related": []})
    has = con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='article_olta'").fetchone()
    if not has:
        con.close()
        return jsonify({"ok": True, "available": False, "direct": [], "near": [], "related": []})
    law = _match_prec_law(con, request.args.get("law", ""))
    art = _norm_article(request.args.get("art", ""))
    out: Dict[str, Any] = {"ok": True, "available": True, "law": law, "art": art,
                           "direct": [], "near": [], "related": []}
    if not law or not art:
        con.close()
        return jsonify(out)
    grp = " GROUP BY op.board, op.ntt_id ORDER BY op.created_at DESC"
    out["direct"] = [_olta_card(r) for r in
                     con.execute(_OLTA_SEL + "ao.law=? AND ao.art=?" + grp, (law, art))]
    meta = con.execute("SELECT semok, seq FROM article_meta WHERE law=? AND art=?", (law, art)).fetchone()
    if meta is not None:
        semok, seq = meta["semok"], meta["seq"]
        near_q = ("ao.law=? AND ao.art!=? AND ao.art IN "
                  "(SELECT art FROM article_meta WHERE law=? AND semok=? AND ABS(seq-?)<=2)")
        out["near"] = [_olta_card(r) for r in
                       con.execute(_OLTA_SEL + near_q + grp, (law, art, law, semok, seq))]
        rel_q = ("ao.law=? AND ao.art!=? AND ao.art IN "
                 "(SELECT art FROM article_meta WHERE law=? AND semok=? AND ABS(seq-?)>2)")
        out["related"] = [_olta_card(r) for r in
                          con.execute(_OLTA_SEL + rel_q + grp, (law, art, law, semok, seq))]
    con.close()
    out["counts"] = {k: len(out[k]) for k in ("direct", "near", "related")}
    return jsonify(out)


@app.route("/api/article_olta_counts")
def api_article_olta_counts() -> Response:
    """법령 1개의 조문별 olta(질의+상담) 직접 연결 수(인라인 배지용)."""
    con = _prec_con()
    if con is None or not con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='article_olta'").fetchone():
        if con:
            con.close()
        return jsonify({"ok": True, "available": False, "counts": {}})
    law = _match_prec_law(con, request.args.get("law", ""))
    counts: Dict[str, int] = {}
    if law:
        for r in con.execute(
                "SELECT art, COUNT(DISTINCT board||'|'||ntt_id) c FROM article_olta WHERE law=? GROUP BY art",
                (law,)):
            counts[r["art"]] = r["c"]
    con.close()
    return jsonify({"ok": True, "available": True, "law": law, "counts": counts})


@app.route("/api/olta_post")
def api_olta_post() -> Response:
    """olta 글 1건 전체 내용(팝업 표시용)."""
    con = _prec_con()
    if con is None:
        return jsonify({"ok": False, "error": "인덱스 없음"})
    board = request.args.get("board", "")
    ntt = request.args.get("ntt_id", "")
    r = con.execute("SELECT * FROM olta_post WHERE board=? AND ntt_id=?", (board, ntt)).fetchone()
    con.close()
    if not r:
        return jsonify({"ok": False, "error": "글을 찾지 못했습니다."})
    try:
        answers = json.loads(r["answers_json"] or "[]")
    except Exception:
        answers = []
    for a in answers:
        if isinstance(a, dict) and a.get("text"):
            a["text"] = _olta_reflow(a["text"])
    return jsonify({"ok": True, "board": r["board"], "ntt_id": r["ntt_id"],
                    "board_label": "질의응답" if r["board"] == "qa" else "지방세상담",
                    "category": r["category"], "title": r["title"], "author": r["author"],
                    "created_at": r["created_at"], "answer_count": r["answer_count"],
                    "body_text": _olta_reflow(r["body_text"]), "attach_text": _olta_reflow(r["attach_text"]),
                    "answers": answers})


@app.route("/api/olta_search")
def api_olta_search() -> Response:
    """olta 글 키워드 검색(검색대상 체크박스 '질의응답/지방세상담'용)."""
    con = _prec_con()
    if con is None or not con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='olta_post'").fetchone():
        if con:
            con.close()
        return jsonify({"ok": True, "available": False, "items": []})
    q = (request.args.get("q", "") or "").strip()
    boards = [b for b in (request.args.get("boards", "qa,consult").split(",")) if b]
    try:
        limit = max(1, min(200, int(request.args.get("limit", "50"))))
    except ValueError:
        limit = 50
    if not q:
        con.close()
        return jsonify({"ok": True, "available": True, "items": []})
    terms = [t for t in re.split(r"\s+", q) if t]
    where = ["board IN (%s)" % ",".join("?" * len(boards))]
    params: List[Any] = list(boards)
    for t in terms:  # 모든 단어 포함(AND)
        where.append("(title LIKE ? OR body_text LIKE ? OR attach_text LIKE ? OR answers_json LIKE ?)")
        params += [f"%{t}%"] * 4
    sql = ("SELECT board, ntt_id, category, title, author, created_at, answer_count, "
           "body_text, attach_text FROM olta_post WHERE " + " AND ".join(where) +
           " ORDER BY created_at DESC LIMIT ?")
    params.append(limit)
    items = [_olta_card(r) for r in con.execute(sql, params)]
    con.close()
    return jsonify({"ok": True, "available": True, "q": q, "count": len(items), "items": items})


# ---------------------------------------------------------------------------
# 전체화면 법령 리더 + 조문별 노트 인라인 + Claude 질문 인박스
# ---------------------------------------------------------------------------
ASK_INBOX = DATA_DIR / "ask_inbox.jsonl"


@app.route("/reader")
def reader_page() -> Response:
    p = BASE_DIR / "static_v20" / "reader.html"
    if not p.exists():
        return _tool_error_page("법령 리더", "reader.html 을 찾지 못했습니다.")
    return Response(p.read_text(encoding="utf-8"), mimetype="text/html; charset=utf-8")


@app.route("/api/reader_notes")
def api_reader_notes() -> Response:
    """한 법령의 모든 노트를 조문번호(article)별로 묶어 반환(리더 인라인 표시용)."""
    ensure_note_schema()
    law_id = request.args.get("law_id", "").strip()
    mst = request.args.get("mst", "").strip()
    law_name = request.args.get("law_name", "").strip()
    with sqlite3.connect(DB_PATH) as con:
        con.row_factory = sqlite3.Row
        rows = [dict(r) for r in con.execute("SELECT * FROM thread_notes ORDER BY id ASC").fetchall()]
        ids = [int(r["id"]) for r in rows]
        refs_by_note: Dict[int, List[Dict[str, Any]]] = {i: [] for i in ids}
        if ids:
            ph = ",".join("?" for _ in ids)
            for rr in con.execute(f"SELECT * FROM thread_note_refs WHERE note_id IN ({ph})", ids).fetchall():
                d = dict(rr)
                refs_by_note.setdefault(int(d["note_id"]), []).append(d)

    def matches(ref: Dict[str, Any]) -> bool:
        if law_id and str(ref.get("law_id") or "") == law_id:
            return True
        if mst and str(ref.get("mst") or "") == mst:
            return True
        if law_name and str(ref.get("law_name") or "") == law_name:
            return True
        return False

    by_article: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        nid = int(row["id"])
        cand = (refs_by_note.get(nid) or [])
        primary = _primary_note_ref(row)
        if _note_ref_has_value(primary):
            cand = cand + [primary]
        arts = sorted({str(r.get("article") or "").strip() for r in cand
                       if matches(r) and str(r.get("article") or "").strip()})
        if not arts:
            continue
        card = {
            "id": nid, "title": row.get("title") or "", "body": row.get("body") or "",
            "source": row.get("source") or "me", "created_at": row.get("created_at") or "",
            "q": row.get("q") or "",
        }
        for a in arts:
            by_article.setdefault(a, []).append(card)
    return jsonify({"ok": True, "by_article": by_article,
                    "count": sum(len(v) for v in by_article.values())})


# ---------------------------------------------------------------------------
# 조/항/호/목 단위 회독(읽은 횟수) — 노트와 같은 단위 식별자로 dashboard.db 에 저장.
# 리더·대시보드가 같은 scope(law_id→mst→법령명)+단위키로 공유합니다.
# ---------------------------------------------------------------------------
def ensure_reading_schema() -> None:
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS unit_readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                law_name TEXT, law_id TEXT, mst TEXT,
                article TEXT, paragraph TEXT, ho TEXT, mok TEXT, unit_level TEXT,
                unit_key TEXT UNIQUE,
                count INTEGER DEFAULT 0,
                updated_at TEXT
            )
            """
        )
        con.commit()


ensure_reading_schema()


def _reading_scope(law_id: str, mst: str, law_name: str) -> str:
    """회독 저장의 법령 범위 키. 노트 매칭과 같은 우선순위(law_id→mst→법령명)."""
    return (str(law_id or "").strip() or str(mst or "").strip()
            or normalize_law_name(law_name or "") or "?")


def _reading_unit_part(ref: Dict[str, Any]) -> str:
    return "|".join(str(ref.get(k, "") or "").strip()
                    for k in ("article", "paragraph", "ho", "mok", "unit_level"))


@app.route("/api/readings", methods=["GET", "POST"])
def api_readings() -> Response:
    ensure_reading_schema()
    if request.method == "POST":
        payload = request.get_json(force=True) or {}
        scope = _reading_scope(payload.get("law_id", ""), payload.get("mst", ""), payload.get("law_name", ""))
        unit_part = _reading_unit_part(payload)
        if not unit_part.strip("|"):
            return jsonify({"ok": False, "error": "회독 단위 정보가 없습니다."}), 400
        unit_key = scope + "::" + unit_part
        try:
            delta = int(payload.get("delta", 1))
        except Exception:
            delta = 1
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with sqlite3.connect(DB_PATH) as con:
            row = con.execute("SELECT count FROM unit_readings WHERE unit_key=?", (unit_key,)).fetchone()
            cur = int(row[0]) if row else 0
            newc = max(0, cur + delta)
            if row is not None:
                con.execute("UPDATE unit_readings SET count=?, updated_at=?, law_name=? WHERE unit_key=?",
                            (newc, now, str(payload.get("law_name", "") or ""), unit_key))
            else:
                con.execute(
                    "INSERT INTO unit_readings(law_name, law_id, mst, article, paragraph, ho, mok, unit_level, unit_key, count, updated_at)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (str(payload.get("law_name", "") or ""), str(payload.get("law_id", "") or ""), str(payload.get("mst", "") or ""),
                     str(payload.get("article", "") or ""), str(payload.get("paragraph", "") or ""), str(payload.get("ho", "") or ""),
                     str(payload.get("mok", "") or ""), str(payload.get("unit_level", "") or ""), unit_key, newc, now),
                )
            con.commit()
        return jsonify({"ok": True, "unit": unit_part, "count": newc})

    law_id = request.args.get("law_id", "").strip()
    mst = request.args.get("mst", "").strip()
    law_name = request.args.get("law_name", "").strip()
    scope = _reading_scope(law_id, mst, law_name)
    like = scope.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "::%"
    with sqlite3.connect(DB_PATH) as con:
        rows = con.execute(
            "SELECT unit_key, count FROM unit_readings WHERE unit_key LIKE ? ESCAPE '\\'", (like,)
        ).fetchall()
    by_unit: Dict[str, int] = {}
    for uk, cnt in rows:
        part = uk.split("::", 1)[1] if "::" in uk else uk
        by_unit[part] = int(cnt or 0)
    return jsonify({"ok": True, "scope": scope, "by_unit": by_unit,
                    "count": sum(by_unit.values())})


@app.route("/api/ask_inbox", methods=["GET", "POST", "DELETE"])
def api_ask_inbox() -> Response:
    """조문 질문 인박스. 리더에서 보낸 질문을 로컬 파일에 쌓아두고, 이 채팅에서 일괄 처리."""
    if request.method == "POST":
        payload = request.get_json(force=True) or {}
        item = {
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "law_name": str(payload.get("law_name", ""))[:120],
            "article": str(payload.get("article", ""))[:40],
            "title": str(payload.get("title", ""))[:200],
            "prompt": str(payload.get("prompt", "")),
        }
        if not item["prompt"].strip():
            return jsonify({"ok": False, "error": "prompt 가 비었습니다."}), 400
        with open(ASK_INBOX, "a", encoding="utf-8") as f:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
        return jsonify({"ok": True})
    if request.method == "DELETE":
        try:
            ASK_INBOX.unlink()
        except FileNotFoundError:
            pass
        return jsonify({"ok": True, "cleared": True})
    items: List[Dict[str, Any]] = []
    if ASK_INBOX.exists():
        for ln in ASK_INBOX.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                items.append(json.loads(ln))
            except Exception:
                pass
    return jsonify({"ok": True, "items": items, "count": len(items)})


HANJA_QUEUE = DATA_DIR / "hanja_queue.jsonl"


@app.route("/api/hanja/queue", methods=["GET", "POST", "DELETE"])
def api_hanja_queue() -> Response:
    """한자 '완전변환' 요청 큐. 대시보드 버튼이 여기에 법령을 등록하면, 이 채팅에서 Claude가
    워크플로로 전 조문을 변환해 /api/hanja/law 에 저장한다(버튼→터미널 직접주입 불가 우회)."""
    if request.method == "POST":
        payload = request.get_json(force=True) or {}
        item = {
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "law_key": str(payload.get("law_key", "")),
            "law_name": str(payload.get("law_name", ""))[:120],
            "target": str(payload.get("target", "eflaw"))[:20],
            "law_id": str(payload.get("law_id", ""))[:40],
            "mst": str(payload.get("mst", ""))[:40],
        }
        if not item["law_name"] and not item["mst"] and not item["law_id"]:
            return jsonify({"ok": False, "error": "법령 식별자가 필요합니다."}), 400
        with open(HANJA_QUEUE, "a", encoding="utf-8") as f:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
        return jsonify({"ok": True})
    if request.method == "DELETE":
        try:
            HANJA_QUEUE.unlink()
        except FileNotFoundError:
            pass
        return jsonify({"ok": True, "cleared": True})
    items: List[Dict[str, Any]] = []
    if HANJA_QUEUE.exists():
        for ln in HANJA_QUEUE.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if ln:
                try:
                    items.append(json.loads(ln))
                except Exception:
                    pass
    return jsonify({"ok": True, "items": items, "count": len(items)})


# ---------------------------------------------------------------------------
# 지방세관계법 운영 예규 뷰어 (data/yegyu249.json) — 노트 연결 대상
# ---------------------------------------------------------------------------
YEGYU_JSON = DATA_DIR / "yegyu249.json"


def _load_yegyu() -> Dict[str, Any]:
    try:
        return json.loads(YEGYU_JSON.read_text(encoding="utf-8"))
    except Exception:
        return {"entries": []}


@app.route("/yegyu")
def yegyu_page() -> Response:
    p = BASE_DIR / "static_v20" / "yegyu.html"
    if not p.exists():
        return _tool_error_page("운영 예규", "yegyu.html 을 찾지 못했습니다.")
    return Response(p.read_text(encoding="utf-8"), mimetype="text/html; charset=utf-8")


@app.route("/api/yegyu")
def api_yegyu() -> Response:
    data = _load_yegyu()
    entries = data.get("entries", [])
    meta = {k: data.get(k) for k in ("name", "no", "date", "count")}
    key = request.args.get("key", "").strip()
    q = request.args.get("q", "").strip()
    if key:
        for e in entries:
            if e.get("key") == key:
                return jsonify({"ok": True, "entry": e, "meta": meta})
        return jsonify({"ok": False, "error": "해당 예규 항목을 찾지 못했습니다.", "meta": meta})
    if q:
        ql = q.replace(" ", "")
        hit = [e for e in entries
               if ql in (str(e.get("title", "")) + str(e.get("body", ""))).replace(" ", "")
               or ql in str(e.get("key", ""))]
        return jsonify({"ok": True, "count": len(hit), "entries": hit[:300], "meta": meta})
    return jsonify({"ok": True, "count": len(entries), "entries": entries, "meta": meta})


# ---------------------------------------------------------------------------
# 조문 ↔ 운영예규 연결 : yegyu249.json 을 (법·레벨·조) 단위로 인덱싱
# (키가 '법13-1'처럼 법을 구분 안 해 겹치므로, 본문의 법명 인용 + 문서순서 이월로 소속법 태깅)
# ---------------------------------------------------------------------------
_YEGYU_ARTIDX = None
_YEGYU_LAWFAM = ["지방세특례제한법", "지방세기본법", "지방세징수법", "지방세법"]


def _yegyu_fam(txt: str):
    for n in _YEGYU_LAWFAM:
        if n in txt:
            return n
    return None


def _yegyu_artidx():
    global _YEGYU_ARTIDX
    if _YEGYU_ARTIDX is not None:
        return _YEGYU_ARTIDX
    ents = _load_yegyu().get("entries", [])
    idx: Dict[Any, List[Any]] = {}
    cur = "지방세기본법"  # 문서상 첫 편
    for e in ents:
        key = str(e.get("key", ""))
        m = re.match(r"(법|시행령)(\d+)", key)
        if not m:
            continue
        level = "시행령" if key.startswith("시행령") else "법"
        art = "제" + m.group(2) + "조"
        fam = _yegyu_fam(str(e.get("title", "")) + " " + str(e.get("body", ""))[:400])
        if fam:
            cur = fam
        idx.setdefault((cur, level, art), []).append(
            {"key": e.get("key"), "title": e.get("title"), "body": e.get("body")})
    _YEGYU_ARTIDX = idx
    return idx


def _yegyu_lawkey(law_name: str):
    ln = str(law_name or "")
    level = "시행령" if "시행령" in ln else "법"
    for canon in _YEGYU_LAWFAM:
        if canon in ln:
            return canon, level
    return None, level


@app.route("/api/law_yegyu_counts")
def api_law_yegyu_counts() -> Response:
    """법령 1개의 조문별 운영예규 수(인라인 배지용)."""
    canon, level = _yegyu_lawkey(request.args.get("law", ""))
    if not canon:
        return jsonify({"ok": True, "available": False, "counts": {}})
    idx = _yegyu_artidx()
    counts = {art: len(lst) for (c, lv, art), lst in idx.items() if c == canon and lv == level}
    return jsonify({"ok": True, "available": True, "law": canon, "level": level, "counts": counts})


@app.route("/api/article_yegyu")
def api_article_yegyu() -> Response:
    """조문 1개에 연결된 운영예규 항목(본문 드롭다운 표시용)."""
    canon, level = _yegyu_lawkey(request.args.get("law", ""))
    art = _norm_article(request.args.get("art", ""))
    m = re.match(r"(제\d+조)", art)
    art_base = m.group(1) if m else art  # 운영예규 키는 '조의' 없이 기본 조번호
    idx = _yegyu_artidx()
    items = idx.get((canon, level, art_base), []) if canon else []
    return jsonify({"ok": True, "available": bool(canon), "law": canon, "art": art_base,
                    "count": len(items), "items": items})


# ---------------------------------------------------------------------------
# 회독·노트 git 동기화 (sync_util.py) — 킬 때 pull / 종료 시 push + 인앱 토글
# ---------------------------------------------------------------------------
@app.route("/api/sync/status")
def api_sync_status() -> Response:
    if not sync_util:
        return jsonify({"ok": True, "available": False})
    cfg = sync_util.load_config()
    remote = sync_util.has_remote()
    _, porcelain = sync_util._git("status", "--porcelain")
    return jsonify({"ok": True, "available": True, "auto": bool(cfg.get("auto")),
                    "last_sync": cfg.get("last_sync"), "has_remote": remote,
                    "dirty": bool(porcelain.strip())})


@app.route("/api/sync/toggle", methods=["POST"])
def api_sync_toggle() -> Response:
    if not sync_util:
        return jsonify({"ok": False, "error": "sync 모듈 없음"})
    cfg = sync_util.load_config()
    cfg["auto"] = bool((request.get_json(force=True) or {}).get("on"))
    sync_util.save_config(cfg)
    return jsonify({"ok": True, "auto": cfg["auto"]})


def _broad_sync_extras() -> Dict[str, Any]:
    """[지금 동기화]를 업무통합대시보드의 광범위 동기화와 동일 범위로 확장 (2026-08-09).

    1순위: 업무통합대시보드(17777)가 떠 있으면 그 /api/sync에 위임
           → 일정 병합 + 회사자료(readables) 받기 + 리포트 올리기 + 읽을것들 git + UI 기기별 채널 전부.
    폴백  : 17777이 꺼져 있으면 읽을것들 스크립트·git만 직접 수행
           (일정 병합·UI채널은 그 대시보드 로직이라 실행 중일 때만 가능).
    어느 단계도 삭제·회귀 없음 — 각 단계는 기존 검증된 스크립트/버튼 로직 그대로."""
    out: Dict[str, Any] = {}
    import subprocess
    import sys as _s

    def _todo_up() -> bool:
        import socket as _sock
        try:
            with _sock.create_connection(("127.0.0.1", 17777), timeout=0.4):
                return True
        except Exception:
            return False

    # 꺼져 있으면 자동으로 켠다 (집/회사 표준 경로 순회)
    if not _todo_up():
        for cand in (Path(r"C:\Users\jeons\Downloads\todo_manual_dashboard\todo_manual_dashboard_package"),
                     Path(r"C:\todo_manual_dashboard\todo_manual_dashboard_package")):
            if (cand / "app.py").exists():
                try:
                    subprocess.Popen('cmd /c chcp 65001 >nul & py -3.12 app.py', cwd=str(cand), shell=True,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                except Exception:
                    continue
                for _ in range(50):                     # 최대 25초 기동 대기
                    if _todo_up():
                        break
                    time.sleep(0.5)
                break

    try:
        r = requests.get("http://127.0.0.1:17777/api/sync", timeout=280)
        j = r.json()
        out["via"] = "todo-dashboard"
        out["ok"] = bool(j.get("ok"))
        out["message"] = str(j.get("message", ""))
        return out
    except Exception:
        pass
    out["via"] = "fallback"
    msgs: List[str] = []
    base = Path(r"C:\python_programs")
    rd = base / "읽을것들"

    def run(args, cwd, to=300):
        try:
            p = subprocess.run(args, cwd=str(cwd), capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=to,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return p.returncode, (p.stdout or "") + (p.stderr or "")
        except Exception as e:
            return -1, str(e)

    if (rd / "_pull_company.py").exists():
        rc, log = run([_s.executable, str(rd / "_pull_company.py")], rd, 600)
        m = re.search(r"신규 (\d+) · 갱신 (\d+)", log)
        if rc == 0 and m and (m.group(1) != "0" or m.group(2) != "0"):
            msgs.append(f"회사자료 +{m.group(1)}·갱신{m.group(2)}")
        run([_s.executable, str(rd / "_gather.py")], rd, 300)
        rc2, log2 = run([_s.executable, str(rd / "_push_reports.py")], rd, 600)
        m2 = re.search(r"올림 신규 (\d+) · 갱신 (\d+)", log2)
        if rc2 == 0 and m2 and (m2.group(1) != "0" or m2.group(2) != "0"):
            msgs.append(f"리포트 올림 +{m2.group(1)}·갱신{m2.group(2)}")
    if (base / ".git").exists():
        run(["git", "add", "읽을것들"], base)
        rc, _ = run(["git", "diff", "--cached", "--quiet", "--", "읽을것들"], base)
        if rc == 1:
            run(["git", "commit", "-m",
                 f"읽을것들 자동 동기화 ({os.environ.get('COMPUTERNAME','PC')})"], base)
        rc, _log = run(["git", "-c", "rebase.autoStash=true", "pull", "--rebase", "origin", "main"], base)
        if rc != 0:
            run(["git", "rebase", "--abort"], base)
            msgs.append("읽을것들 충돌⚠")
        else:
            rc2, _ = run(["git", "push", "origin", "main"], base)
            msgs.append("읽을것들 ✓" if rc2 == 0 else "읽을것들 받기만 ✓")
    msgs.append("일정·UI채널은 업무통합대시보드 실행 중일 때 함께 동기화")
    out["ok"] = True
    out["message"] = " · ".join(msgs)
    return out


@app.route("/api/sync/now", methods=["POST"])
def api_sync_now() -> Response:
    if not sync_util:
        return jsonify({"ok": False, "error": "sync 모듈 없음"})
    result = sync_util.do_sync()          # ① 이 대시보드 저장소(코드·UI·노트) — 기존 동작
    try:
        result["extras"] = _broad_sync_extras()   # ② 광범위(일정·HTML·읽을것들·UI채널)
    except Exception as e:
        result["extras"] = {"ok": False, "message": "확장 동기화 오류: " + str(e)}
    return jsonify(result)


@app.route("/api/pools", methods=["GET", "POST"])
def api_pools() -> Response:
    if request.method == "GET":
        return jsonify({"ok": True, "pools": load_pools()})
    payload = request.get_json(force=True) or {}
    raw_pools = payload.get("pools", {})
    pools: Dict[str, List[str]] = {}
    if isinstance(raw_pools, dict):
        for name, laws in raw_pools.items():
            name = str(name).strip()
            if not name:
                continue
            if isinstance(laws, str):
                law_list = [x.strip() for x in re.split(r"[\n,;]+", laws) if x.strip()]
            elif isinstance(laws, list):
                law_list = [str(x).strip() for x in laws if str(x).strip()]
            else:
                law_list = []
            pools[name] = law_list
    save_pools(pools or DEFAULT_POOLS)
    return jsonify({"ok": True, "pools": load_pools()})


@app.route("/api/search")
def api_search() -> Response:
    target = request.args.get("target", "eflaw")
    query = request.args.get("query", "")
    refresh = request.args.get("refresh") == "1"
    result = search_one_target(target, query, request.args.get("search", "1"), request.args.get("display", "20"), request.args.get("page", "1"), refresh)
    if not result.get("ok"):
        return jsonify(result), 400
    return jsonify(result)


@app.route("/api/search_multi")
def api_search_multi() -> Response:
    query = request.args.get("query", "").strip()
    targets = request.args.getlist("targets") or [request.args.get("target", "eflaw")]
    targets = [t for t in targets if t in TARGETS] or ["eflaw"]
    if not query and "ordin_gijang" not in targets:
        return jsonify({"ok": False, "error": "검색어를 입력하세요."}), 400
    search = request.args.get("search", "1")
    display = request.args.get("display", "20")
    page = request.args.get("page", "1")
    refresh = request.args.get("refresh") == "1"
    use_pool = request.args.get("use_pool") == "1"
    pool_name = request.args.get("pool", "")
    limit = max(1, min(100, int(display or 20)))

    if not query and "ordin_gijang" in targets:
        rows: List[Dict[str, Any]] = []
        errors: List[str] = []
        for target in targets:
            if target != "ordin_gijang":
                continue
            result = search_one_target(target, "", "1", display, page, refresh)
            if not result.get("ok"):
                errors.append(f"{TARGETS.get(target, target)}: {result.get('error')}")
                continue
            rows.extend(result.get("normalized", {}).get("items", []))
        return jsonify({"ok": True, "mode": "gijang_list", "items": rows[:limit], "count": len(rows[:limit]), "total": len(rows), "targets": targets, "errors": errors})

    if use_pool and pool_name:
        result = pool_search(load_pools(), pool_name, targets, query, search, limit, refresh)
        result["targets"] = targets
        return jsonify(result)

    rows: List[Dict[str, Any]] = []
    errors: List[str] = []
    total = 0
    seen_rows = set()
    query_parts = split_terms(query) if search == "2" else [query]
    query_parts = query_parts or [query]
    qstr = request.query_string.decode("utf-8")

    # v20: 여러 검색대상×검색어 요청을 동시에 보내 대기시간을 줄입니다(I/O 병렬).
    # 각 스레드는 자기 요청 컨텍스트를 복원해 get_oc()·request.args가 그대로 동작합니다.
    def _run_search(args: Tuple[str, str]) -> Tuple[str, Dict[str, Any]]:
        tg, qp = args
        with app.test_request_context("/?" + qstr):
            return tg, search_one_target(tg, qp, search, display, page, refresh)

    search_tasks = [(t, q) for t in targets for q in query_parts]
    if len(search_tasks) > 1:
        with ThreadPoolExecutor(max_workers=SEARCH_MAX_WORKERS) as ex:
            search_results = list(ex.map(_run_search, search_tasks))
    else:
        search_results = [_run_search(a) for a in search_tasks]

    for target, result in search_results:
        if not result.get("ok"):
            errors.append(f"{TARGETS.get(target, target)}: {result.get('error')}")
            continue
        norm = result.get("normalized", {})
        try:
            total += int(str(norm.get("total", "0")).replace(",", ""))
        except Exception:
            total += len(norm.get("items", []))
        for item in norm.get("items", []):
            sig = (item.get("target"), item.get("law_id"), item.get("mst"), item.get("name"))
            if sig in seen_rows:
                continue
            seen_rows.add(sig)
            rows.append(item)

    rows = interleave_rows_by_target(rows, targets)

    if search == "2":
        # 본문검색은 결과 항목마다 상세조회(HTTP)가 필요해 가장 느립니다. 동시에 처리합니다.
        cand = rows[:limit]

        def _enrich_one(item: Dict[str, Any]) -> Dict[str, Any]:
            with app.test_request_context("/?" + qstr):
                return enrich_item_with_matches(item, item.get("target", targets[0]), query, refresh)

        if len(cand) > 1:
            with ThreadPoolExecutor(max_workers=SEARCH_MAX_WORKERS) as ex:
                enriched_all = list(ex.map(_enrich_one, cand))
        else:
            enriched_all = [_enrich_one(i) for i in cand]
        rows = [e for e in enriched_all if e.get("matches")]

    return jsonify({"ok": True, "mode": "normal", "items": rows[:limit], "count": len(rows[:limit]), "total": total, "targets": targets, "errors": errors})



def related_query_terms(text: str, title: str = "") -> List[str]:
    """선택 조문에서 관련 법령/조례/판례 검색용 핵심어를 추립니다."""
    raw = re.sub(r"\s+", " ", f"{title} {text}".strip())
    # 인용 법령명/조문 번호를 우선 추출
    law_names = re.findall(r"([가-힣A-Za-z0-9·ㆍ\s]{2,60}?(?:법|령|규칙|조례|규정))\s*(?:제\d+조)?", raw)
    article_refs = re.findall(r"제\s*\d+\s*조(?:의\s*\d+)?", raw)
    # 너무 일반적인 단어 제거 후 2~5개만 사용
    stop = {"이 법", "같은 법", "같은 조", "해당 법", "이 조례", "같은 조례", "대통령령", "총리령", "부령"}
    terms: List[str] = []
    for x in law_names + article_refs:
        x = re.sub(r"\s+", " ", x).strip()
        if len(x) < 2 or x in stop:
            continue
        if x not in terms:
            terms.append(x)
    if len(terms) < 3:
        # 법령명이 없으면 명사성 토큰을 보조로 사용합니다.
        tokens = re.findall(r"[가-힣A-Za-z0-9·ㆍ]{2,}", raw)
        bad = {"한다","있는","없는","경우","따른","따라","관한","대한","또는","그리고","에게","에서","으로","한다는","제외","적용"}
        for t in tokens:
            if t in bad or re.fullmatch(r"제?\d+조?", t):
                continue
            if t not in terms:
                terms.append(t)
            if len(terms) >= 5:
                break
    return terms[:5]


@app.route("/api/related")
def api_related() -> Response:
    text = request.args.get("text", "")[:4000]
    title = request.args.get("title", "")[:300]
    source_target = request.args.get("source_target", "")
    source_name = request.args.get("source_name", "")
    refresh = request.args.get("refresh") == "1"
    terms = related_query_terms(text, title)
    if not terms:
        return jsonify({"ok": True, "terms": [], "items": [], "message": "연결 검색용 핵심어를 찾지 못했습니다."})
    targets = ["eflaw", "ordin", "ordin_gijang", "prec", "expc", "admrul"]
    rows: List[Dict[str, Any]] = []
    seen = set()
    errors: List[str] = []
    for target in targets:
        for term in terms[:3]:
            try:
                res = search_one_target(target, term, "2", "10", "1", refresh)
                if not res.get("ok"):
                    errors.append(f"{TARGETS.get(target,target)}: {res.get('error')}")
                    continue
                for item in res.get("normalized", {}).get("items", [])[:10]:
                    if source_target and item.get("target") == source_target and item.get("name") == source_name:
                        continue
                    sig = (item.get("target"), item.get("law_id"), item.get("mst"), item.get("name"))
                    if sig in seen:
                        continue
                    enriched = enrich_item_with_matches(item, item.get("target", target), " ".join(terms[:3]), refresh)
                    if not enriched.get("matches"):
                        continue
                    enriched["related_term"] = term
                    seen.add(sig)
                    rows.append(enriched)
                    if len(rows) >= 20:
                        break
            except Exception as e:
                errors.append(f"{TARGETS.get(target,target)}/{term}: {e}")
            if len(rows) >= 20:
                break
        if len(rows) >= 20:
            break
    return jsonify({"ok": True, "terms": terms, "items": rows[:20], "errors": errors})

@app.route("/api/detail")
def api_detail() -> Response:
    target = request.args.get("target", "eflaw")
    law_id = request.args.get("id", "")
    mst = request.args.get("mst", "")
    efyd = request.args.get("efyd", "") or request.args.get("effective_date", "")
    jo = request.args.get("jo", "")
    law_name = request.args.get("law_name", "") or request.args.get("name", "")
    refresh = request.args.get("refresh") == "1"
    result = get_detail_payload(target, law_id, mst, efyd, jo, refresh, law_name)
    if not result.get("ok"):
        return jsonify(result), 400
    # v20: 현행법령 본문에는 조문 간 인용 링크(법제처 lsInfoR.do 기반)를 붙입니다.
    if target in ("eflaw", "law") and isinstance(result.get("normalized"), dict):
        try:
            attach_lawgo_links(result["normalized"], mst, efyd, refresh)
        except Exception:
            pass
    return jsonify(result)


@app.route("/api/ref_target")
def api_ref_target() -> Response:
    """조문 인용 링크 클릭 시 대상 법령(lsiSeq=MST)·조문을 해석해 돌려줍니다."""
    seq = request.args.get("seq", "")
    refresh = request.args.get("refresh") == "1"
    result = resolve_lawgo_ref_target(seq, refresh)
    if not result.get("ok"):
        return jsonify(result), 400
    return jsonify(result)


@app.route("/api/bookmarks", methods=["GET", "POST"])
def api_bookmarks() -> Response:
    if request.method == "POST":
        payload = request.get_json(force=True)
        with sqlite3.connect(DB_PATH) as con:
            cur = con.execute(
                """
                INSERT INTO bookmarks(created_at, law_name, target, law_id, mst, efyd, jo, title, body, source_url, tags)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"), payload.get("law_name", ""), payload.get("target", ""),
                    payload.get("law_id", ""), payload.get("mst", ""), payload.get("efyd", ""), payload.get("jo", ""),
                    payload.get("title", ""), payload.get("body", ""), payload.get("source_url", ""), payload.get("tags", ""),
                ),
            )
            con.commit()
            return jsonify({"ok": True, "id": cur.lastrowid})

    with sqlite3.connect(DB_PATH) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute("SELECT * FROM bookmarks ORDER BY id DESC LIMIT 300").fetchall()
    return jsonify({"ok": True, "items": [dict(r) for r in rows]})


@app.route("/api/bookmarks/<int:bookmark_id>", methods=["DELETE"])
def api_delete_bookmark(bookmark_id: int) -> Response:
    with sqlite3.connect(DB_PATH) as con:
        con.execute("DELETE FROM bookmarks WHERE id=?", (bookmark_id,))
        con.commit()
    return jsonify({"ok": True})


@app.route("/api/notes/<path:key>", methods=["GET", "POST"])
def api_notes(key: str) -> Response:
    if request.method == "POST":
        note = (request.get_json(force=True) or {}).get("note", "")
        with sqlite3.connect(DB_PATH) as con:
            con.execute(
                "INSERT INTO notes(key, updated_at, note) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET updated_at=excluded.updated_at, note=excluded.note",
                (key, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), note),
            )
            con.commit()
        return jsonify({"ok": True})
    with sqlite3.connect(DB_PATH) as con:
        row = con.execute("SELECT note, updated_at FROM notes WHERE key=?", (key,)).fetchone()
    return jsonify({"ok": True, "note": row[0] if row else "", "updated_at": row[1] if row else ""})


@app.route("/api/export/bookmarks.csv")
def api_export_bookmarks() -> Response:
    with sqlite3.connect(DB_PATH) as con:
        con.row_factory = sqlite3.Row
        rows = [dict(r) for r in con.execute("SELECT * FROM bookmarks ORDER BY id DESC").fetchall()]
    out_path = DATA_DIR / "bookmarks_export.csv"
    fieldnames = ["id", "created_at", "law_name", "target", "law_id", "mst", "efyd", "jo", "title", "body", "source_url", "tags"]
    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})
    return send_file(out_path, as_attachment=True, download_name="지방세법령_북마크.csv")



@app.route("/api/title_search")
def api_title_search() -> Response:
    query = request.args.get("query", "").strip()
    targets = request.args.getlist("targets") or [request.args.get("target", "eflaw")]
    targets = [t for t in targets if t in TARGETS] or ["eflaw"]
    display = request.args.get("display", "15")
    refresh = request.args.get("refresh") == "1"
    rows: List[Dict[str, Any]] = []
    errors: List[str] = []
    if not query and "ordin_gijang" not in targets:
        return jsonify({"ok": True, "items": [], "count": 0})
    for target in targets:
        result = search_one_target(target, query, "1", display, "1", refresh)
        if not result.get("ok"):
            errors.append(f"{TARGETS.get(target, target)}: {result.get('error')}")
            continue
        rows.extend(result.get("normalized", {}).get("items", []))
    rows = interleave_rows_by_target(rows, targets)
    limit = max(1, min(100, int(display or 15)))
    return jsonify({"ok": True, "items": rows[:limit], "count": len(rows[:limit]), "errors": errors})




def _note_ref_from_payload(payload: Dict[str, Any]) -> Dict[str, str]:
    return {
        "law_name": str(payload.get("law_name", "") or ""),
        "target": str(payload.get("target", "") or ""),
        "law_id": str(payload.get("law_id", "") or ""),
        "mst": str(payload.get("mst", "") or ""),
        "article": str(payload.get("article", "") or ""),
        "paragraph": str(payload.get("paragraph", "") or ""),
        "ho": str(payload.get("ho", "") or ""),
        "mok": str(payload.get("mok", "") or ""),
        "unit_level": str(payload.get("unit_level", "") or ""),
        "unit_text": str(payload.get("unit_text", "") or ""),
    }


def _note_ref_has_value(ref: Dict[str, str]) -> bool:
    return any(str(ref.get(k, "") or "").strip() for k in ("law_name", "law_id", "mst", "article", "unit_text"))


def _insert_note_ref(con: sqlite3.Connection, note_id: int, ref: Dict[str, Any]) -> None:
    clean = _note_ref_from_payload(ref)
    if not _note_ref_has_value(clean):
        return
    con.execute(
        """
        INSERT INTO thread_note_refs(created_at, note_id, law_name, target, law_id, mst, article, paragraph, ho, mok, unit_level, unit_text)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"), note_id,
            clean.get("law_name", ""), clean.get("target", ""), clean.get("law_id", ""), clean.get("mst", ""),
            clean.get("article", ""), clean.get("paragraph", ""), clean.get("ho", ""), clean.get("mok", ""),
            clean.get("unit_level", ""), clean.get("unit_text", ""),
        ),
    )


def _primary_note_ref(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": None,
        "note_id": row.get("id"),
        "law_name": row.get("law_name", ""),
        "target": row.get("target", ""),
        "law_id": row.get("law_id", ""),
        "mst": row.get("mst", ""),
        "article": row.get("article", ""),
        "paragraph": row.get("paragraph", ""),
        "ho": row.get("ho", ""),
        "mok": row.get("mok", ""),
        "unit_level": row.get("unit_level", ""),
        "unit_text": row.get("unit_text", ""),
        "primary": True,
    }


def _article_number(value: str) -> int:
    m = re.search(r"제\s*(\d+)\s*조", str(value or ""))
    return int(m.group(1)) if m else -1


def _unit_num(value: str) -> str:
    """Normalize a paragraph/ho/mok label to a bare token regardless of notation
    (circled unicode ①-⑳, '제N항', 'N.', 'N의2.' sub-numbering, plain 'N', '가.' 등)
    so relevance matching survives notation drift between note-authoring paths and
    the live 법제처 API segment format (which uses circled unicode for paragraph)."""
    s = str(value or "").strip()
    if not s:
        return ""
    circled = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
    if s[0] in circled:
        return str(circled.index(s[0]) + 1)
    m = re.search(r"(\d+(?:의\d+)?)", s)
    if m:
        return m.group(1)
    return s.rstrip(".").strip()


@app.route("/api/thread_notes", methods=["GET", "POST", "PUT", "DELETE"])
def api_thread_notes() -> Response:
    ensure_note_schema()
    if request.method == "DELETE":
        note_id = request.args.get("id", "")
        if not str(note_id).isdigit():
            return jsonify({"ok": False, "error": "삭제할 노트 ID가 필요합니다."}), 400
        nid = int(note_id)
        with sqlite3.connect(DB_PATH) as con:
            con.execute("DELETE FROM thread_note_refs WHERE note_id=?", (nid,))
            con.execute("DELETE FROM thread_note_urls WHERE note_id=?", (nid,))
            con.execute("DELETE FROM thread_notes WHERE id=? OR parent_id=?", (nid, nid))
            con.commit()
        return jsonify({"ok": True, "deleted": nid})

    if request.method == "POST":
        payload = request.get_json(force=True) or {}
        body = str(payload.get("body", "")).strip()
        title = str(payload.get("title", "")).strip()[:200]
        try:
            imgs_list = [str(x) for x in (payload.get("imgs") or []) if isinstance(x, str) and x.strip()][:12]
        except Exception:
            imgs_list = []
        imgs_json = json.dumps(imgs_list, ensure_ascii=False)
        if not body and not imgs_list:
            return jsonify({"ok": False, "error": "노트 내용 또는 이미지를 입력하세요."}), 400
        primary = _note_ref_from_payload(payload)
        if not title:
            title = (body.splitlines()[0][:80] if body.splitlines() else "") or ("[이미지]" if imgs_list else "")
        source = "claude" if str(payload.get("source", "")).strip().lower() == "claude" else "me"
        qtext = str(payload.get("q", "") or "").strip()
        with sqlite3.connect(DB_PATH) as con:
            cur = con.execute(
                """
                INSERT INTO thread_notes(created_at, parent_id, law_name, target, law_id, mst, article, paragraph, ho, mok, unit_level, unit_text, body, title, source, q, imgs)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"), payload.get("parent_id") or None,
                    primary.get("law_name", ""), primary.get("target", ""), primary.get("law_id", ""), primary.get("mst", ""),
                    primary.get("article", ""), primary.get("paragraph", ""), primary.get("ho", ""), primary.get("mok", ""),
                    primary.get("unit_level", ""), primary.get("unit_text", ""), body, title, source, qtext, imgs_json,
                ),
            )
            nid = int(cur.lastrowid)
            refs = payload.get("refs") if isinstance(payload.get("refs"), list) else [primary]
            seen = set()
            for ref in refs:
                if not isinstance(ref, dict):
                    continue
                clean = _note_ref_from_payload(ref)
                key = tuple(clean.get(k, "") for k in ("law_name", "law_id", "mst", "article", "paragraph", "ho", "mok", "unit_level"))
                if key in seen:
                    continue
                seen.add(key)
                _insert_note_ref(con, nid, clean)
            for url in payload.get("urls", []) if isinstance(payload.get("urls"), list) else []:
                if not isinstance(url, dict):
                    continue
                u = str(url.get("url", "") or "").strip()
                if not u:
                    continue
                con.execute(
                    "INSERT INTO thread_note_urls(created_at, note_id, title, url) VALUES(?,?,?,?)",
                    (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), nid, str(url.get("title", "") or "").strip()[:200], u),
                )
            con.commit()
            return jsonify({"ok": True, "id": nid})

    if request.method == "PUT":
        note_id = request.args.get("id") or (request.get_json(force=True) or {}).get("id")
        if not str(note_id).isdigit():
            return jsonify({"ok": False, "error": "수정할 노트 ID가 필요합니다."}), 400
        payload = request.get_json(force=True) or {}
        nid = int(note_id)
        body = str(payload.get("body", "") or "").strip()
        title = str(payload.get("title", "") or "").strip()[:200]
        if not body:
            return jsonify({"ok": False, "error": "노트 본문을 입력하세요."}), 400
        refs = payload.get("refs") if isinstance(payload.get("refs"), list) else []
        primary = _note_ref_from_payload(refs[0] if refs and isinstance(refs[0], dict) else payload)
        with sqlite3.connect(DB_PATH) as con:
            con.execute(
                """
                UPDATE thread_notes
                   SET title=?, body=?, law_name=?, target=?, law_id=?, mst=?, article=?, paragraph=?, ho=?, mok=?, unit_level=?, unit_text=?
                 WHERE id=?
                """,
                (
                    title, body, primary.get("law_name", ""), primary.get("target", ""), primary.get("law_id", ""), primary.get("mst", ""),
                    primary.get("article", ""), primary.get("paragraph", ""), primary.get("ho", ""), primary.get("mok", ""),
                    primary.get("unit_level", ""), primary.get("unit_text", ""), nid,
                ),
            )
            con.execute("DELETE FROM thread_note_refs WHERE note_id=?", (nid,))
            seen = set()
            for ref in refs:
                if not isinstance(ref, dict):
                    continue
                clean = _note_ref_from_payload(ref)
                key = tuple(clean.get(k, "") for k in ("law_name", "law_id", "mst", "article", "paragraph", "ho", "mok", "unit_level"))
                if key in seen:
                    continue
                seen.add(key)
                _insert_note_ref(con, nid, clean)
            con.execute("DELETE FROM thread_note_urls WHERE note_id=?", (nid,))
            for url in payload.get("urls", []) if isinstance(payload.get("urls"), list) else []:
                if not isinstance(url, dict):
                    continue
                u = str(url.get("url", "") or "").strip()
                if not u:
                    continue
                con.execute(
                    "INSERT INTO thread_note_urls(created_at, note_id, title, url) VALUES(?,?,?,?)",
                    (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), nid, str(url.get("title", "") or "").strip()[:200], u),
                )
            con.commit()
        return jsonify({"ok": True, "id": nid})

    law_name = request.args.get("law_name", "").strip()
    law_id = request.args.get("law_id", "").strip()
    mst = request.args.get("mst", "").strip()
    article = request.args.get("article", "").strip()
    paragraph = request.args.get("paragraph", "").strip()
    ho = request.args.get("ho", "").strip()
    mok = request.args.get("mok", "").strip()
    sort = request.args.get("sort", "relevance").strip()
    source_filter = request.args.get("source", "").strip().lower()
    page = max(1, int(request.args.get("page", "1") or 1))
    page_size = max(5, min(50, int(request.args.get("page_size", "8") or 8)))
    offset = (page - 1) * page_size

    with sqlite3.connect(DB_PATH) as con:
        con.row_factory = sqlite3.Row
        all_rows = [dict(r) for r in con.execute("SELECT * FROM thread_notes ORDER BY id DESC").fetchall()]
        if source_filter in ("me", "claude"):
            all_rows = [r for r in all_rows if (r.get("source") or "me") == source_filter]
        ids = [int(r["id"]) for r in all_rows]
        refs_by_note: Dict[int, List[Dict[str, Any]]] = {int(r["id"]): [] for r in all_rows}
        urls_by_note: Dict[int, List[Dict[str, Any]]] = {int(r["id"]): [] for r in all_rows}
        if ids:
            placeholders = ",".join("?" for _ in ids)
            for rr in con.execute(f"SELECT * FROM thread_note_refs WHERE note_id IN ({placeholders}) ORDER BY id ASC", ids).fetchall():
                d = dict(rr)
                refs_by_note.setdefault(int(d["note_id"]), []).append(d)
            for uu in con.execute(f"SELECT * FROM thread_note_urls WHERE note_id IN ({placeholders}) ORDER BY id ASC", ids).fetchall():
                d = dict(uu)
                urls_by_note.setdefault(int(d["note_id"]), []).append(d)

    def score_ref(ref: Dict[str, Any]) -> int:
        score = 0
        if law_id and ref.get("law_id") == law_id:
            score += 120
        if mst and ref.get("mst") == mst:
            score += 110
        if law_name and ref.get("law_name") == law_name:
            score += 90
        elif law_name and ref.get("law_name") and (law_name in str(ref.get("law_name")) or str(ref.get("law_name")) in law_name):
            score += 35
        if article and ref.get("article") == article:
            score += 80
            if paragraph and _unit_num(ref.get("paragraph")) == _unit_num(paragraph):
                score += 25
            if ho and _unit_num(ref.get("ho")) == _unit_num(ho):
                score += 20
            if mok and _unit_num(ref.get("mok")) == _unit_num(mok):
                score += 15
        elif article and ref.get("article"):
            a = _article_number(article)
            b = _article_number(str(ref.get("article")))
            if a >= 0 and b >= 0 and law_name and ref.get("law_name") == law_name:
                diff = abs(a - b)
                if diff == 1:
                    score += 35
                elif diff == 2:
                    score += 20
                elif diff <= 5:
                    score += 8
        return score

    def score_note(row: Dict[str, Any]) -> int:
        nid = int(row.get("id", 0))
        refs = refs_by_note.get(nid) or []
        primary = _primary_note_ref(row)
        candidates = refs + ([primary] if _note_ref_has_value(primary) else [])
        score = max([score_ref(r) for r in candidates] or [0])
        hay = " ".join(str(x or "") for x in (row.get("title"), row.get("body"), row.get("unit_text")))
        if law_name and law_name in hay:
            score += 12
        if article and article in hay:
            score += 8
        return score

    for row in all_rows:
        nid = int(row.get("id", 0))
        refs = refs_by_note.get(nid) or []
        primary = _primary_note_ref(row)
        merged: List[Dict[str, Any]] = []
        seen_keys = set()
        for ref in refs + ([primary] if _note_ref_has_value(primary) else []):
            key = tuple(str(ref.get(k, "") or "") for k in ("law_name", "law_id", "mst", "article", "paragraph", "ho", "mok", "unit_level"))
            if key in seen_keys:
                continue
            seen_keys.add(key)
            merged.append(ref)
        row["refs"] = merged
        row["urls"] = urls_by_note.get(nid, [])
        row["_score"] = score_note(row)

    if sort == "relevance":
        all_rows.sort(key=lambda r: (r.get("_score", 0), r.get("id", 0)), reverse=True)
    else:
        all_rows.sort(key=lambda r: r.get("id", 0), reverse=True)

    total = len(all_rows)
    rows = all_rows[offset:offset + page_size]
    return jsonify({
        "ok": True,
        "items": rows,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
        "sort": sort,
    })


@app.route("/api/hanja/dict", methods=["GET"])
def api_hanja_dict() -> Response:
    """병합된 한자 사전(시드+사용자 교정)을 반환. 프론트가 본문에 루비 병기할 때 사용."""
    d = merged_hanja_dict()
    return jsonify({"ok": True, "dict": d, "count": len([v for v in d.values() if v])})


@app.route("/api/hanja/override", methods=["POST", "DELETE"])
def api_hanja_override() -> Response:
    """한자 교정 저장/삭제. hanja=''로 저장하면 그 단어는 한자 안 붙임(억제)."""
    ensure_hanja_schema()
    if request.method == "DELETE":
        term = (request.args.get("term") or "").strip()
        if not term:
            return jsonify({"ok": False, "error": "term이 필요합니다."}), 400
        with sqlite3.connect(DB_PATH) as con:
            con.execute("DELETE FROM hanja_overrides WHERE term=?", (term,))
            con.commit()
        return jsonify({"ok": True, "deleted": term})
    payload = request.get_json(force=True) or {}
    term = str(payload.get("term", "")).strip()
    hanja = str(payload.get("hanja", "")).strip()
    source = "claude" if str(payload.get("source", "")).strip().lower() == "claude" else "user"
    if not term:
        return jsonify({"ok": False, "error": "term이 필요합니다."}), 400
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            "INSERT INTO hanja_overrides(term, hanja, updated_at, source) VALUES(?,?,?,?) "
            "ON CONFLICT(term) DO UPDATE SET hanja=excluded.hanja, updated_at=excluded.updated_at, source=excluded.source",
            (term, hanja, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), source),
        )
        con.commit()
    return jsonify({"ok": True, "term": term, "hanja": hanja})


@app.route("/api/hanja/law", methods=["GET", "POST", "DELETE"])
def api_hanja_law() -> Response:
    """법령 단위 한자 변환판(국한문 혼용) 저장/조회. data = {원문구절: 한자변환구절}. Claude가 변환해 POST."""
    ensure_hanja_schema()
    if request.method == "GET":
        law_key = (request.args.get("law_key") or "").strip()
        if not law_key:
            return jsonify({"ok": True, "has": False, "map": {}, "count": 0})
        with sqlite3.connect(DB_PATH) as con:
            row = con.execute("SELECT law_name, data FROM hanja_law WHERE law_key=?", (law_key,)).fetchone()
        if not row:
            return jsonify({"ok": True, "has": False, "map": {}, "count": 0})
        try:
            m = json.loads(row[1] or "{}")
        except Exception:
            m = {}
        return jsonify({"ok": True, "has": bool(m), "law_name": row[0] or "", "map": m, "count": len(m)})
    if request.method == "DELETE":
        law_key = (request.args.get("law_key") or "").strip()
        with sqlite3.connect(DB_PATH) as con:
            con.execute("DELETE FROM hanja_law WHERE law_key=?", (law_key,))
            con.commit()
        return jsonify({"ok": True, "deleted": law_key})
    payload = request.get_json(force=True) or {}
    law_key = str(payload.get("law_key", "")).strip()
    law_name = str(payload.get("law_name", "")).strip()
    new_map = payload.get("map") or {}
    if not law_key or not isinstance(new_map, dict):
        return jsonify({"ok": False, "error": "law_key와 map이 필요합니다."}), 400
    replace = bool(payload.get("replace"))
    with sqlite3.connect(DB_PATH) as con:
        cur = con.execute("SELECT data FROM hanja_law WHERE law_key=?", (law_key,)).fetchone()
        existing: Dict[str, str] = {}
        if cur and not replace:
            try:
                existing = json.loads(cur[0] or "{}")
            except Exception:
                existing = {}
        for k, v in new_map.items():
            if isinstance(k, str) and isinstance(v, str) and k.strip():
                existing[k] = v
        con.execute(
            "INSERT INTO hanja_law(law_key, law_name, data, updated_at) VALUES(?,?,?,?) "
            "ON CONFLICT(law_key) DO UPDATE SET law_name=excluded.law_name, data=excluded.data, updated_at=excluded.updated_at",
            (law_key, law_name, json.dumps(existing, ensure_ascii=False), datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        con.commit()
    return jsonify({"ok": True, "law_key": law_key, "count": len(existing)})


@app.route("/api/thread_notes/link", methods=["POST", "DELETE"])
def api_thread_note_link() -> Response:
    ensure_note_schema()
    if request.method == "DELETE":
        ref_id = request.args.get("id", "")
        if not str(ref_id).isdigit():
            return jsonify({"ok": False, "error": "삭제할 연결 ID가 필요합니다."}), 400
        with sqlite3.connect(DB_PATH) as con:
            con.execute("DELETE FROM thread_note_refs WHERE id=?", (int(ref_id),))
            con.commit()
        return jsonify({"ok": True})
    payload = request.get_json(force=True) or {}
    note_id = payload.get("note_id") or payload.get("id")
    if not str(note_id).isdigit():
        return jsonify({"ok": False, "error": "연결할 노트 ID가 필요합니다."}), 400
    ref = payload.get("ref") if isinstance(payload.get("ref"), dict) else payload
    with sqlite3.connect(DB_PATH) as con:
        _insert_note_ref(con, int(note_id), ref)
        con.commit()
    return jsonify({"ok": True})

def safe_filename(text: str, max_len: int = 90) -> str:
    text = re.sub(r"[\\/:*?\"<>|]+", "_", str(text or "").strip())
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"_+", "_", text).strip("._ ")
    if not text:
        text = hashlib.sha1(str(time.time()).encode("utf-8")).hexdigest()[:12]
    return text[:max_len]


def normalize_law_file_url(url: str) -> str:
    url = str(url or "").strip()
    if not url:
        return ""
    if url.startswith("http://") or url.startswith("https://"):
        return url
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return "https://www.law.go.kr" + url
    return "https://www.law.go.kr/" + url.lstrip("./")


@app.route("/api/forms/preview", methods=["POST"])
def api_forms_preview() -> Response:
    payload = request.get_json(force=True) or {}
    law_name = str(payload.get("law_name") or "법령").strip() or "법령"
    title = str(payload.get("title") or "서식").strip() or "서식"
    pdf_url = normalize_law_file_url(str(payload.get("pdf_url") or ""))

    if not pdf_url:
        return jsonify({"ok": False, "error": "PDF 링크가 없습니다."}), 400

    law_dir_name = safe_filename(law_name, 80)
    title_name = safe_filename(title, 120)
    folder = FORMS_DIR / law_dir_name
    folder.mkdir(parents=True, exist_ok=True)
    file_path = folder / f"{title_name}.pdf"
    index_path = folder / "forms_index.json"

    cached = file_path.exists() and file_path.stat().st_size > 0

    if not cached:
        try:
            with requests.get(pdf_url, stream=True, timeout=40, headers={"User-Agent": "Mozilla/5.0"}) as r:
                r.raise_for_status()
                tmp_path = file_path.with_suffix(".pdf.tmp")
                with tmp_path.open("wb") as f:
                    for chunk in r.iter_content(chunk_size=1024 * 128):
                        if chunk:
                            f.write(chunk)
                tmp_path.replace(file_path)
        except Exception as e:
            return jsonify({"ok": False, "error": f"PDF 다운로드 실패: {e}"}), 502

    # 간단한 로컬 인덱스 저장
    try:
        if index_path.exists():
            forms_index = json.loads(index_path.read_text(encoding="utf-8"))
        else:
            forms_index = {}
        forms_index[title] = {
            "title": title,
            "law_name": law_name,
            "pdf_url": pdf_url,
            "local_file": str(file_path),
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        index_path.write_text(json.dumps(forms_index, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

    rel = f"{law_dir_name}/{file_path.name}"
    return jsonify({
        "ok": True,
        "cached": cached,
        "title": title,
        "law_name": law_name,
        "file_url": f"/forms_file/{rel}",
        "local_path": str(file_path),
    })


@app.route("/forms_file/<path:relpath>")
def forms_file(relpath: str) -> Response:
    return send_from_directory(FORMS_DIR, relpath, as_attachment=False)


@app.route("/api/ui_state/<path:key>", methods=["GET", "POST", "DELETE"])
def api_ui_state(key: str) -> Response:
    """브라우저 localStorage가 흔들릴 때를 대비한 가벼운 UI 상태 저장소입니다."""
    safe_key = re.sub(r"[^0-9A-Za-z_.-]+", "_", str(key or "")).strip("_")[:80]
    if not safe_key:
        return jsonify({"ok": False, "error": "state key is required"}), 400

    try:
        if UI_STATE_PATH.exists():
            raw = json.loads(UI_STATE_PATH.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raw = {}
        else:
            raw = {}
    except Exception:
        raw = {}

    if request.method == "GET":
        return jsonify({"ok": True, "key": safe_key, "data": raw.get(safe_key)})

    if request.method == "DELETE":
        raw.pop(safe_key, None)
        UI_STATE_PATH.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
        return jsonify({"ok": True, "key": safe_key, "deleted": True})

    payload = request.get_json(force=False, silent=True)
    if payload is None:
        body_text = request.get_data(as_text=True) or ""
        if body_text.strip():
            try:
                payload = json.loads(body_text)
            except Exception:
                payload = {}
        else:
            payload = {}
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "state payload must be an object"}), 400
    payload.setdefault("savedAt", datetime.now().isoformat())
    payload["serverSavedAt"] = datetime.now().isoformat()
    raw[safe_key] = payload
    tmp_path = UI_STATE_PATH.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(UI_STATE_PATH)
    return jsonify({"ok": True, "key": safe_key, "saved": True, "path": str(UI_STATE_PATH), "serverSavedAt": payload["serverSavedAt"]})


# ---------------------------------------------------------------------------
# v20: 법령창 도구 — 위임법령 / 신구법 비교 / 3단비교
# ---------------------------------------------------------------------------

def _tool_error_page(title: str, msg: str) -> Response:
    body = (
        "<html><head><meta charset='utf-8'><title>" + html.escape(title) + "</title></head>"
        "<body style='font-family:Malgun Gothic,sans-serif;padding:24px;line-height:1.7'>"
        "<h3>" + html.escape(title) + "</h3><p>" + html.escape(msg) + "</p>"
        "<p style='color:#667085'>이 창은 닫아도 됩니다.</p></body></html>"
    )
    return Response(body, status=404, mimetype="text/html; charset=utf-8")


@app.route("/open/delegated")
def open_delegated() -> Response:
    """위임법령 조회(lsDelegated)를 간단한 표 형태 HTML로 보여줍니다."""
    law_id = request.args.get("id", "").strip()
    mst = request.args.get("mst", "").strip()
    name = request.args.get("name", "").strip() or "법령"
    refresh = request.args.get("refresh") == "1"
    if not (law_id or mst):
        return _tool_error_page("위임법령 조회", "법령 ID가 없습니다.")
    result: Dict[str, Any] = {"ok": False, "error": "조회 실패"}
    for params in ({"target": "lsDelegated", "type": "JSON", "ID": law_id, "OC": get_oc()},
                   {"target": "lsDelegated", "type": "JSON", "MST": mst, "OC": get_oc()}):
        if not (params.get("ID") or params.get("MST")):
            continue
        result = request_law_api("lawService.do", params, refresh=refresh)
        if result.get("ok") and isinstance(result.get("data"), dict) and "raw" not in result["data"]:
            break
    if not result.get("ok"):
        return _tool_error_page("위임법령 조회", str(result.get("error") or "법제처 API 호출에 실패했습니다."))
    data = result.get("data", {})
    law_title = str(find_key_recursive(data, ["법령명", "법령명한글"]) or name)

    rows_html: List[str] = []
    jo_units = find_all_by_key(data, "위임조문정보")
    for unit in jo_units:
        for u in as_list(unit):
            if not isinstance(u, dict):
                continue
            jo_label = " ".join(t for t in (article_number_from_item(u), pick(u, "조문제목", "조제목", "제목")) if t).strip() or "조문"
            delega_rows = []
            for info in as_list(u.get("위임정보")):
                if not isinstance(info, dict):
                    continue
                d_title = pick(info, "위임법령제목", "위임행정규칙제목", "위임자치법규제목", "제목")
                d_kind = pick(info, "위임구분")
                d_seq = pick(info, "위임법령일련번호", "위임행정규칙일련번호", "위임자치법규일련번호", "일련번호")
                jo_info = info.get("위임법령조문정보")
                jo_txts = []
                for j in as_list(jo_info):
                    if isinstance(j, dict):
                        t = " ".join(x for x in (article_number_from_item(j), pick(j, "조문제목", "제목")) if x)
                        if t:
                            jo_txts.append(t)
                    elif isinstance(j, str) and j.strip():
                        jo_txts.append(j.strip())
                link = f"https://www.law.go.kr/LSW/lsInfoP.do?lsiSeq={html.escape(d_seq)}" if d_seq else ""
                shown = html.escape(d_title or "(제목 없음)")
                if link:
                    shown = f"<a href='{link}' target='_blank' rel='noopener noreferrer'>{shown}</a>"
                delega_rows.append(
                    "<li>" + shown
                    + (f" <span style='color:#667085'>[{html.escape(d_kind)}]</span>" if d_kind else "")
                    + (f"<div style='color:#475467;font-size:13px'>{html.escape(' · '.join(jo_txts))}</div>" if jo_txts else "")
                    + "</li>"
                )
            if delega_rows:
                rows_html.append(
                    f"<tr><td style='vertical-align:top;white-space:nowrap;padding:8px 12px;border-bottom:1px solid #e4e7ec'><b>{html.escape(jo_label)}</b></td>"
                    f"<td style='padding:8px 12px;border-bottom:1px solid #e4e7ec'><ul style='margin:0;padding-left:18px'>{''.join(delega_rows)}</ul></td></tr>"
                )

    if rows_html:
        table = ("<table style='border-collapse:collapse;width:100%;max-width:1100px'>"
                 "<thead><tr><th style='text-align:left;padding:8px 12px;border-bottom:2px solid #98a2b3'>조문</th>"
                 "<th style='text-align:left;padding:8px 12px;border-bottom:2px solid #98a2b3'>위임 하위법령·자치법규</th></tr></thead>"
                 "<tbody>" + "".join(rows_html) + "</tbody></table>")
    else:
        pretty = html.escape(json.dumps(data, ensure_ascii=False, indent=2)[:200000])
        table = ("<p>위임조문 구조를 표로 정리하지 못해 원본 JSON을 표시합니다.</p>"
                 f"<pre style='background:#f8f9fc;border:1px solid #e4e7ec;padding:14px;border-radius:8px;overflow:auto'>{pretty}</pre>")

    body = (
        "<html><head><meta charset='utf-8'><title>위임법령 · " + html.escape(law_title) + "</title></head>"
        "<body style='font-family:Malgun Gothic,sans-serif;padding:24px;line-height:1.7;color:#101828'>"
        "<h2 style='margin-top:0'>위임법령 조회</h2>"
        "<p><b>" + html.escape(law_title) + "</b> 의 조문별 위임(시행령·시행규칙·자치법규) 현황입니다. "
        "제목을 누르면 법제처 원문이 새 탭으로 열립니다.</p>" + table + "</body></html>"
    )
    return Response(body, mimetype="text/html; charset=utf-8")


def _open_law_tool_redirect(target: str, link_keys: List[str], fallback_title: str) -> Response:
    name = request.args.get("name", "").strip()
    law_id = request.args.get("id", "").strip()
    refresh = request.args.get("refresh") == "1"
    if not name and not law_id:
        return _tool_error_page(fallback_title, "법령명이 없습니다.")
    result = request_law_api("lawSearch.do", {"target": target, "type": "JSON", "query": name, "display": "50", "OC": get_oc()}, refresh=refresh)
    if not result.get("ok"):
        return _tool_error_page(fallback_title, str(result.get("error") or "법제처 API 호출에 실패했습니다."))
    items = []
    for key in ("oldAndNew", "thdCmp"):
        found = find_key_recursive(result.get("data", {}), [key])
        if found is not None:
            items = as_list(found)
            break
    if not items:
        return _tool_error_page(fallback_title, f"'{name}' 에 대한 {fallback_title} 자료가 없습니다.")
    chosen = None
    for it in items:
        if isinstance(it, dict) and law_id and pick(it, "신구법ID", "법령ID") == law_id:
            chosen = it
            break
    if chosen is None:
        for it in items:
            if isinstance(it, dict) and name and normalize_law_name(pick(it, "신구법명", "법령명한글", "법령명")) == normalize_law_name(name):
                chosen = it
                break
    if chosen is None:
        chosen = next((it for it in items if isinstance(it, dict)), None)
    if not isinstance(chosen, dict):
        return _tool_error_page(fallback_title, "자료 항목을 해석하지 못했습니다.")
    link = ""
    for k in link_keys:
        link = pick(chosen, k)
        if link:
            break
    if not link:
        link = pick_detail_link(chosen)
    if not link:
        return _tool_error_page(fallback_title, "상세링크가 응답에 없습니다.")
    from flask import redirect
    return redirect(absolutize_law_url(link))


@app.route("/open/oldandnew")
def open_oldandnew() -> Response:
    return _open_law_tool_redirect("oldAndNew", ["신구법상세링크"], "신구법 비교")


@app.route("/open/thdcmp")
def open_thdcmp() -> Response:
    knd = request.args.get("knd", "2").strip()
    keys = ["인용조문_삼단비교상세링크"] if knd == "1" else ["위임조문_삼단비교상세링크", "인용조문_삼단비교상세링크"]
    return _open_law_tool_redirect("thdCmp", keys, "3단비교")


@app.route("/api/health")
def health() -> Response:
    return jsonify({"ok": True, "db": str(DB_PATH), "cache_dir": str(CACHE_DIR), "pools": str(POOLS_PATH)})


# ── 한자 엔진(형태소+161k 대사전) 즉석 변환: gold 미보유 세그먼트 폴백 ──────
_HJ_ENGINE = {"fn": None, "err": None}


def _load_hanja_engine():
    """hanja_engine(형태소 기반 로컬 변환기)을 지연 로드. DB/파일에 아무것도 쓰지 않는다."""
    if _HJ_ENGINE["fn"] is not None or _HJ_ENGINE["err"] is not None:
        return
    try:
        import sys as _sys
        eng_dir = str(BASE_DIR.parent / "hanja_engine")
        if eng_dir not in _sys.path:
            _sys.path.insert(0, eng_dir)
        from convert import convert_text as _ct  # noqa
        _ct("초기화")  # kiwi/사전 웜업
        _HJ_ENGINE["fn"] = _ct
    except Exception as e:  # 엔진 미설치 등 — 대시보드 본기능엔 영향 없음
        _HJ_ENGINE["err"] = str(e)


@app.route("/api/hanja/convert", methods=["POST"])
def api_hanja_convert() -> Response:
    """텍스트 배열을 로컬 엔진으로 즉석 국한문 변환. 어디에도 저장하지 않음(임시).
    gold한자 버튼이 gold 맵에 없는 세그먼트를 채울 때 사용(빈틈없는 변환)."""
    _load_hanja_engine()
    if _HJ_ENGINE["fn"] is None:
        return jsonify({"ok": False, "error": f"엔진 로드 실패: {_HJ_ENGINE['err']}"}), 500
    payload = request.get_json(force=True, silent=True) or {}
    texts = payload.get("texts") or []
    outputs, flagged = [], []
    for t in texts:
        try:
            r = _HJ_ENGINE["fn"](str(t))
            outputs.append(r["output"])
            if r.get("homographs") or r.get("unknown"):
                flagged.append({"text": str(t)[:60], "homographs": r.get("homographs", []),
                                "unknown": r.get("unknown", [])})
        except Exception:
            outputs.append(str(t))  # 실패 시 원문 유지(안전)
    return jsonify({"ok": True, "outputs": outputs, "flagged": flagged[:50]})


# ── 문제(기출) 대시보드: study/ 폴더를 /quiz 로 서빙 ───────────────────────
QUIZ_DIR = BASE_DIR / "study"


@app.route("/quiz")
@app.route("/quiz/")
def quiz_index() -> Response:
    return send_from_directory(str(QUIZ_DIR), "index.html")


@app.route("/quiz/<path:filename>")
def quiz_files(filename: str) -> Response:
    return send_from_directory(str(QUIZ_DIR), filename)


@app.route("/api/quiz_note", methods=["POST"])
def api_quiz_note() -> Response:
    """문제 해설(claude_qa.json) 저장/수정 — 단일 키 머지(사용자 편집 보존)."""
    payload = request.get_json(force=True) or {}
    qid = str(payload.get("id") or "").strip()
    if not qid:
        return jsonify({"error": "no id"}), 400
    path = QUIZ_DIR / "claude_qa.json"
    try:
        data: Dict[str, Any] = {}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8-sig")) or {}
            except Exception:
                data = {}
        if payload.get("delete"):
            data.pop(qid, None)
        else:
            cur = data.get(qid)
            entry: Dict[str, Any] = cur if isinstance(cur, dict) else {}
            for k in ("ts", "e", "model", "laws", "refs"):
                if k in payload:
                    entry[k] = payload[k]
            data[qid] = entry
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return jsonify({"ok": True, "entry": data.get(qid)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _start_ctrl_alt_0_shutdown_hotkey() -> None:
    """Windows에서 Ctrl+Alt+0을 누르면 현재 대시보드 서버 프로세스를 종료합니다."""
    if os.name != "nt":
        return
    try:
        import ctypes
        import threading

        user32 = ctypes.windll.user32
        MOD_ALT = 0x0001
        MOD_CONTROL = 0x0002
        VK_0 = 0x30
        WM_HOTKEY = 0x0312
        HOTKEY_ID = 6155

        class MSG(ctypes.Structure):
            _fields_ = [
                ("hwnd", ctypes.c_void_p),
                ("message", ctypes.c_uint),
                ("wParam", ctypes.c_void_p),
                ("lParam", ctypes.c_void_p),
                ("time", ctypes.c_uint),
                ("pt_x", ctypes.c_long),
                ("pt_y", ctypes.c_long),
            ]

        def loop() -> None:
            try:
                user32.RegisterHotKey(None, HOTKEY_ID, MOD_CONTROL | MOD_ALT, VK_0)
                msg = MSG()
                while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
                    if msg.message == WM_HOTKEY and int(msg.wParam or 0) == HOTKEY_ID:
                        os._exit(0)
            except Exception:
                return

        threading.Thread(target=loop, daemon=True).start()
    except Exception:
        return


if __name__ == "__main__":
    _start_ctrl_alt_0_shutdown_hotkey()
    print("=" * 72)
    print(f"{APP_TITLE} 실행 중")
    print("브라우저에서 http://127.0.0.1:6155 접속")
    print("종료하려면 이 창에서 Ctrl + C")
    print("=" * 72)
    # 0.0.0.0: 폰(Tailscale VPN)에서 /m 모바일 리더 접속 허용 (2026-08-09).
    # Tailscale은 사설망이라 외부 인터넷엔 열리지 않지만, 공용 와이파이 LAN 노출이
    # 걱정되면 Windows 방화벽에서 6155를 Tailscale 인터페이스로 한정하면 된다.
    app.run(host="0.0.0.0", port=6155, debug=False)
