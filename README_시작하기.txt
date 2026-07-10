법령 대시보드 (law.go.kr / 기장군) — 다른 PC에서 바로 실행하기
============================================================

[빠른 시작]
1) 이 폴더(law_dashboard_portable)를 통째로 PC에 복사합니다.
2) Windows에 Python 3.10 이상이 설치돼 있어야 합니다.
   - 없으면 https://www.python.org/downloads/ 에서 설치
   - 설치 화면에서 "Add Python to PATH" 를 꼭 체크하세요.
3) "START_법령대시보드.bat" 를 더블클릭합니다.
   - 처음 1회는 필요한 패키지(flask, requests, python-dotenv)를
     자동으로 설치합니다(인터넷 필요, 30초~1분).
   - 잠시 후 기본 브라우저에 대시보드가 열립니다.
     주소: http://127.0.0.1:6155

[종료 방법]
- 검은 콘솔(명령) 창을 닫거나, 그 창에서 Ctrl + C
- 또는 "stop_law_dashboard_all.bat" 실행
- 전역 단축키 Ctrl + Alt + 0 으로도 종료됩니다.

[API 인증키 설정]
- 법제처 OPEN API 인증키(OC)는 .env 파일의 OPENLAW_OC 값으로 읽습니다.
- 처음 설치 시: .env.example 을 복사해 .env 로 만들고 OPENLAW_OC 를 본인 OC 로 채우세요.
- .env 가 없으면 화면 상단 OC 입력란에 직접 넣어도 됩니다.
  (.env 는 저장소(git)에 올라가지 않습니다)

[폴더 구성]
- START_법령대시보드.bat ...... 실행 런처(이걸 더블클릭)
- app_law_notes_v20.pyw ........ 서버(백엔드)
- run_server.py ............... 콘솔 실행용 시작 스크립트
- static_v20\index.html ....... 대시보드 화면(프론트엔드, 최신)
- static\index.html ........... 예비 화면
- hanja_dict.json ............. 국한문(한자) 변환 사전
- gijang_ordinances_manual.json  기장군 자치법규 보강 데이터
- data\dashboard.db ........... 내 노트·한자 설정이 저장된 DB
- data\law_pools.json ......... 저장된 법령 묶음
- data\ui_state.json .......... 마지막 화면 상태
- .env ........................ API 인증키
- requirements.txt ............ 필요한 파이썬 패키지 목록
- stop_law_dashboard_all.bat .. 서버 강제 종료

[주요 기능]
- 법령/판례/해석례/조례(기장군) 통합 검색, 3열 비교 보기
- 인용링크 클릭(기본=팝업, 우클릭=1·2·3열/새 창)
- 조문 노트 + 클로드 문답 자동저장, 한자(국한문) 변환, 인쇄/내보내기
- 노트 카드: 클릭=큰 팝업(새 창), 우클릭=열에 표시

[문제 해결]
- "Python not found" → Python 설치 후 PATH 체크하고 다시 실행
- 브라우저가 자동으로 안 열리면 직접 http://127.0.0.1:6155 접속
- 6155 포트가 이미 사용 중이면 런처가 기존 프로세스를 정리합니다
- 패키지 설치가 막히면(인터넷 차단 등) 명령프롬프트에서:
      py -m pip install flask requests python-dotenv
  실행 후 다시 런처를 더블클릭하세요.
