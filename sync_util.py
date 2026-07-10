# -*- coding: utf-8 -*-
"""회독·노트 등 사용자 데이터(dashboard.db) <-> JSON 내보내기/되돌리기 + git 동기화.

- export : DB 사용자 테이블  -> data/sync/user_data.json (텍스트, git 추적)
- import : user_data.json    -> DB (대상 테이블 전체 교체)
- pull   : git pull + import  (킬 때 동기화 = 원격 최신 반영)
- push   : export + git add/commit/push (변경 올리기)

※ '단일 사용자' 전제: 한 곳에서 열어 쓰고 닫을 때 push, 다른 곳은 열 때 pull.
  (동시에 두 곳 편집은 피할 것 — 나중에 연 쪽이 이김)

CLI: python sync_util.py [pull|push|sync|export|import]
"""
from __future__ import annotations
import json
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB_PATH = HERE / "data" / "dashboard.db"
SYNC_DIR = HERE / "data" / "sync"
JSON_PATH = SYNC_DIR / "user_data.json"
CONFIG_PATH = SYNC_DIR / "sync_config.json"

# 동기화 대상: 회독·노트·북마크 등 사용자 입력 데이터.
# (hanja_law = 한자 변환맵은 대용량·재생성 가능이라 제외 → 로컬 보존)
TABLES = ["bookmarks", "notes", "thread_notes", "thread_note_refs",
          "thread_note_urls", "hanja_overrides", "unit_readings"]


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_config():
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"auto": False, "last_sync": None}


def save_config(cfg):
    SYNC_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def export_data():
    if not DB_PATH.exists():
        return {"ok": False, "error": "dashboard.db 없음"}
    SYNC_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    data = {"_meta": {"exported_at": _now()}}
    try:
        existing = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for t in TABLES:
            if t not in existing:
                data[t] = []
                continue
            rows = [dict(r) for r in con.execute(f'SELECT * FROM "{t}"')]
            rows.sort(key=lambda x: json.dumps(x, ensure_ascii=False, sort_keys=True))
            data[t] = rows
    finally:
        con.close()
    JSON_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"ok": True, "rows": sum(len(data.get(t, [])) for t in TABLES), "path": str(JSON_PATH)}


def import_data():
    if not JSON_PATH.exists():
        return {"ok": True, "skipped": "user_data.json 없음"}
    data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    con = sqlite3.connect(DB_PATH)
    try:
        existing = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        con.execute("BEGIN")
        for t in TABLES:
            if t not in existing or t not in data:
                continue
            cols = [r[1] for r in con.execute(f'PRAGMA table_info("{t}")')]
            con.execute(f'DELETE FROM "{t}"')
            for row in (data.get(t) or []):
                keys = [k for k in cols if k in row]
                ph = ",".join("?" * len(keys))
                con.execute(f'INSERT INTO "{t}" ({",".join(keys)}) VALUES ({ph})',
                            [row[k] for k in keys])
        con.commit()
    except Exception as e:
        con.rollback()
        con.close()
        return {"ok": False, "error": str(e)}
    con.close()
    return {"ok": True}


def _git(*args, timeout=120):
    p = subprocess.run(["git", "-C", str(HERE), *args],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout)
    return p.returncode, ((p.stdout or "") + (p.stderr or "")).strip()


def has_remote():
    rc, out = _git("remote")
    return rc == 0 and bool(out.strip())


def git_pull():
    if not has_remote():
        return {"ok": False, "error": "원격(remote) 없음"}
    rc, out = _git("pull", "--rebase", "--autostash")
    return {"ok": rc == 0, "log": out[-400:]}


def git_push(msg=None):
    _git("add", "-A")
    _, staged = _git("diff", "--cached", "--name-only")
    if staged.strip():
        _git("commit", "-m", msg or f"sync: {_now()} (auto)")
    if not has_remote():
        return {"ok": True, "log": "커밋만(원격 없음)"}
    rc, out = _git("push")
    return {"ok": rc == 0, "log": out[-400:]}


def do_pull():
    r = git_pull()
    if r.get("ok"):
        r["import"] = import_data()
    return r


def do_push():
    export_data()
    return git_push()


def do_sync():
    pull = do_pull()
    push = do_push()
    cfg = load_config()
    cfg["last_sync"] = _now()
    save_config(cfg)
    return {"ok": bool(pull.get("ok", True)) and bool(push.get("ok", True)),
            "pull": pull, "push": push, "last_sync": cfg["last_sync"]}


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "sync"
    fn = {"pull": do_pull, "push": do_push, "sync": do_sync,
          "export": export_data, "import": import_data}.get(cmd)
    if not fn:
        print("usage: python sync_util.py [pull|push|sync|export|import]")
        sys.exit(1)
    print(json.dumps(fn(), ensure_ascii=False, indent=2))
