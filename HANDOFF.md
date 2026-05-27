# 작업 인계 — 2026-05-27 11:35

## 현재 작업
원본 Linux/PyQt6 데스크톱 앱(`martin-bochum/DMM-Siglent-SDM`)을 macOS 호환으로 포팅하고, 같은 SCPI 코어 위에 **FastAPI + WebSocket 웹앱**을 얹어 LAN 어디서나 브라우저로 접근할 수 있게 만들었습니다. 모든 변경은 `withwave/DMM-Siglent-SDM` `main` 브랜치에 푸시 완료, 워킹 트리 clean.

## 최근 결정 (이유 포함)

- **`vxi11` → `scpi.SCPISocket`(raw TCP 5025)으로 전환.** SDM3055 VXI-11 데몬이 1 client 한정 + ungraceful 종료 시 분 단위 stuck. raw SCPI는 그 제약이 없고 회복 빠름. `python-vxi11`의 `timeout`이 **seconds 단위**인데 upstream이 `60*1000`을 써서 사실상 16시간 timeout = 영구 freeze였던 게 진짜 hang 원인이었습니다 (자세한 fix는 `b57f0fe`).
- **SCPISocket 안전 가드 풀세트**: `threading.RLock`, ask 전 `_drain()`, 실패/공백/binary 응답 시 `_reconnect()`, close에 `SO_LINGER(0)`(RST로 즉시 세션 종료). 빠른 polling + button handler 동시 호출 시 buffer desync 죽음 루프 방지. `read_raw()`도 finally에서 무조건 reconnect — SCDP screenshot 잔재가 다음 ask로 흘러들지 않게.
- **데스크톱 + 웹 한 repo 유지** (분리 안 함). 이유: `scpi.py` 한 파일이 양쪽 transport 핵심이고, 우리가 4시간 시행착오로 다듬은 가드를 한 곳에서만 수정. fork 관계도 그대로.
- **Tauri/Electron 안 가고 PWA + `launch.py`로 데스크톱 경험.** 브라우저 `--app` 모드 + manifest + service worker만으로 standalone 윈도우 + dock 아이콘 확보. 단일 바이너리 빌드 부담 0.
- **DMM stuck 회복 = quiet wait가 핵심.** 폴링/ping/nc로 SYN을 던지면 instrument의 inactivity timer가 매번 리셋되어 자체 회복 못 함. `tools/dmm-recover`가 30초 간격으로만 probe하며 양보.

## 변경 파일 (최근 ~10 커밋)

- `scpi.py` — SCPISocket transport (데스크톱·웹 공유)
- `sdm30xx_time_qt6.py` — `from scpi import SCPISocket`, `init_dmm()` 추출, DCI 디폴트, `make_font` 폰트 폴백, atexit/SIGTERM/SIGINT 핸들러, `ende()` Remote Lock 해제
- `multimeter.ini` — `HOST=192.168.0.177`
- `requirements.txt` — PyQt6, pyqtgraph, numpy, xlsxwriter, fastapi, uvicorn[standard]
- `web_app.py` — FastAPI 앱, 250ms polling task, WebSocket broadcast, `/api/info|reading|reading.txt|mode|reset-minmax`, CORS open
- `web/index.html|style.css|app.js` — 데스크톱 룩앤필 + canvas 차트 + Server 입력 + scale 토글
- `web/manifest.json|sw.js|icon.svg|icon-128.png` — PWA
- `launch.py` — uvicorn 시작 + Chrome/Edge/Brave `--app` 윈도우 (macOS/Linux/Windows)
- `run.sh|run.command|run.bat` — 더블클릭 실행 (venv 자동 생성)
- `tools/build-macos-app.sh` — `.app` 번들 빌더 (`icon.icns` 자동 변환)
- `tools/ma` — 외부 명령으로 현재값 읽기 (`./tools/ma`, `./tools/ma -w`)
- `tools/dmm-recover` — stuck DMM quiet-wait 회복
- `tests/test_endpoints.sh` — HTTP API smoke test
- `.gitignore` — `__pycache__/`, `.venv/`, `.browser-profile/`, `*.app/`
- `README.md` — macOS 설치, 웹앱, HTTP API, 실행 방법 4가지, stuck 회복

## 다음 할 일

- [ ] **DMM 회복 후 전체 수동 검증**: 현재 SDM3055가 stuck (5025 refused). 후면 전원 OFF 10초 → ON 후 ① `./tools/ma` 동작 ② `./tests/test_endpoints.sh` 통과 ③ `./run.command` 더블클릭 → chromeless 윈도우 ④ `./tools/build-macos-app.sh /Applications` 후 Spotlight 검색 ⑤ 브라우저 Install 버튼 ⑥ Server 입력란/scale 토글 ⑦ 차트 30분 동작 안정성.
- [ ] **iOS Safari / Android Chrome에서 PWA 설치** 확인. LAN URL은 비-HTTPS라 데스크톱 Chrome은 install 거부할 수 있음 — 그땐 `launch.py`로 우회.
- [ ] **점진 확장** (사용자 합의: DC mA 시작 + 확장): RES/CAP/Temp 모드 UI 보강, CSV 다운로드, mobile UI 폴리싱, Basic auth (LAN 외부 노출 시), SCDP screenshot 전송.
- [ ] upstream `martin-bochum/DMM-Siglent-SDM`에 데스크톱 fix만 PR로 보낼지 검토 (timeout 단위 버그, false→False, atexit, SYST:LOCal). 웹앱 코드는 별도 — upstream PR엔 noise.

## 미해결 / 막힌 곳

- **SDM3055 펌웨어 깊은 hang은 전원 사이클 외 회복 불가**. `dmm-recover`의 quiet wait도 90초 시도했지만 회복 안 됨. 펌웨어 한계라 우리 코드로 더 할 수 있는 것 없음 (이미 SO_LINGER + SYST:LOCal + atexit으로 예방). 일반 사용에서는 거의 안 생길 듯.
- 데스크톱 앱과 웹앱 **동시 실행 불가** (SCPI 단일 client) — 한계 인지, README 명시. 둘 다 쓰려면 한쪽 종료 후 다른 쪽 실행.
- `web/icon.svg`는 PWA install 시 사용되지만 일부 OS는 PNG만 받음. `icon-128.png` (기존 repo 아이콘) fallback으로 처리. 더 큰 PNG(192/512)는 미생성 — 필요 시 `sips`로 추가.

## 참고

### 핵심 파일/라인
- `scpi.py:35` SCPISocket `__init__` (lock, RLock, _connect)
- `scpi.py:103` `ask()` — drain + try/except + reconnect + binary guard
- `scpi.py:148` `read_raw()` — finally에서 무조건 reconnect (SCDP 잔재 차단)
- `sdm30xx_time_qt6.py:115` `init_dmm()` — `instr.timeout = 10` (init), 끝에서 2로 단축
- `sdm30xx_time_qt6.py:2353` `ende()` + `_ende_done` idempotent guard
- `sdm30xx_time_qt6.py:2380` `atexit.register(ende)` + signal handlers
- `web_app.py:118` `DMMController.poll_loop` — 250ms asyncio + run_in_executor
- `web_app.py:194` `/api/reading.txt` — engineering prefix
- `web_app.py:218` CORS middleware (LAN 다른 호스트 허용)
- `web/app.js:14` `getServerHost()` / `apiUrl()` / `wsUrl()`
- `web/app.js:30` SCALE_STEPS + applyScale + cycleScale
- `web/app.js:118` `chart` IIFE (circular buffer + draw + auto-scale)

### 커밋 히스토리 핵심 (최신순)
- `d7aed99` dmm-recover 회복 도구
- `5d20503` /api/reading + tools/ma + server 입력 + scale 토글
- `56b95b9` run.sh/command/bat + .app 빌더
- `0b7c20d` launch.py + PWA
- `595beda` 실시간 canvas 차트
- `dd34e54` 웹앱 (FastAPI + WebSocket) 최초
- `3463610` SCPISocket lock + read_raw post-reconnect (현재 transport)
- `b57f0fe` **timeout 단위 버그 fix** (이게 진짜 hang 원인이었음)

### 외부 연결
- DMM: Siglent SDM3055 @ `192.168.0.177:5025` (raw SCPI). VXI-11(111)도 열려있지만 더 이상 사용 안 함.
- 리포지토리: https://github.com/withwave/DMM-Siglent-SDM (origin/main)
- upstream(fork 원본): https://github.com/martin-bochum/DMM-Siglent-SDM (GPL)
