# -*- coding: utf-8 -*-
"""출장 등으로 자리 비울 때 시스템 절전(sleep)·화면 꺼짐·화면보호기를 막아 수집이 끊기지 않게 함.

두 가지를 함께 사용한다(둘 다 시스템 설정을 영구 변경하지 않음):
 1) SetThreadExecutionState(ES_DISPLAY_REQUIRED) — 유휴 절전·화면 꺼짐 방지.
 2) 주기적 1px 마우스 흔들기(SendInput) — 입력 유휴 타이머를 리셋해 화면보호기 확실히 차단.
    (ES_DISPLAY_REQUIRED만으로는 화면보호기가 뜨는 경우가 있어 입력 갱신을 추가.)

이 프로세스가 살아있는 동안만 유효하고, 종료하면 자동으로 원래 절전 설정으로 돌아간다.
중지: 이 프로세스를 종료(작업관리자/Stop-Process)하면 됨.
"""
import ctypes
import io
import sys
import time
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002
FLAGS = ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED

MOUSEEVENTF_MOVE = 0x0001


def nudge_mouse() -> None:
    """커서를 +1px 이동 후 -1px 복귀(상대 이동) — 순이동 0, 화면보호기 타이머만 리셋."""
    ctypes.windll.user32.mouse_event(MOUSEEVENTF_MOVE, 1, 0, 0, 0)
    ctypes.windll.user32.mouse_event(MOUSEEVENTF_MOVE, ctypes.c_long(-1), 0, 0, 0)


print(f"[{datetime.now():%H:%M:%S}] keep-awake ON — 절전·화면 꺼짐·화면보호기 방지 (이 프로세스 동안만)")
try:
    while True:
        ctypes.windll.kernel32.SetThreadExecutionState(FLAGS)
        nudge_mouse()          # 화면보호기 차단(입력 유휴 리셋)
        time.sleep(30)         # 30초마다 갱신(화면보호기 최소 1분보다 짧게)
except KeyboardInterrupt:
    pass
finally:
    ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)  # 원복
    print(f"[{datetime.now():%H:%M:%S}] keep-awake OFF — 절전 설정 원복")
