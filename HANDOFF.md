# 작업 인계 — 2026-05-27 05:43 UTC

## 현재 작업
원본 Linux/PyQt6 데스크톱 앱(`martin-bochum/DMM-Siglent-SDM`)을 macOS 호환으로 포팅하고, 같은 SCPI 코어 위에 **FastAPI + WebSocket 웹앱**을 얹어 LAN 어디서나 브라우저로 접근. 이번 세션에서 **자동 재연결 + 모드 복원 + freshness UI** 보강 (`e8e5bc6`). 모든 변경은 `withwave/DMM-Siglent-SDM` `main` 브랜치에 푸시 완료, 워킹 트리 clean.

## 최근 결정 (이유 포함)

- **DMMController.connect() 는 raise 하지 않고 bool 반환.** 이전엔 lifespan에서 한 번 시도하고 실패하면 `instr=None` 인 채로 영원히 머물러, DMM이 나중에 살아나도 우리 앱은 회복 불가 → 사용자가 서버 재시작해야 했음. 이제 poll_loop이 2 s 백오프로 계속 재시도하면서 마지막 선택한 mode/range도 같이 replay → DMM이 부팅하면서 factory default(보통 VDC)로 올라와도 우리가 잡고 있던 모드로 자동 복귀.
- **freshness 는 client wall clock(`Date.now()`) 기준.** server `ts`를 그대로 쓰면 device 간 시계 skew로 음수가 나올 수 있음. server `ts` 는 payload에 남겨 두되 (외부 도구 디버깅용), UI 계산은 ws.onmessage 시점의 `Date.now()` 차이만 사용.
- **헤더 conn-dot은 e2e health.** 이전엔 WebSocket open만 보여서 DMM이 죽어도 녹색이라 사용자가 혼란. 이제 `WS open && lastReadingHadError==false && age<1s` 일 때만 녹색.
- **RECONNECT_BACKOFF_S = 2 s.** 1 s 미만은 부팅 중 DMM에 SYN 폭격 → inactivity timer 리셋되어 DMM 자체 회복 방해 (`dmm-recover` 와 같은 이유). 5 s 이상은 LAN blip 회복이 너무 느려 보임.
- **SCPISocket을 `connect_retries=1, retry_delay=0` 으로 재초기화.** 기본값 6 × 3 s = 18 s는 우리 poll loop을 그만큼 block함. 외부에서 우리가 직접 retry 사이클을 돌리므로 SCPISocket 내부 retry는 꺼야 함.
- **이전 turn의 핵심 결정 유지**:
  - `vxi11` → `scpi.SCPISocket`(raw TCP 5025). VXI-11 1-client 한정 + ungraceful 종료 시 분 단위 stuck. `b57f0fe` 의 timeout 단위 버그(60*1000 = 16 h)가 진짜 hang 원인이었음.
  - SCPISocket 안전 가드 풀세트: `RLock` + `_drain()` 선처리 + 실패/공백/binary 응답 시 `_reconnect()` + `SO_LINGER(0)`. `read_raw()`는 finally에서 무조건 reconnect (SCDP screenshot 잔재 차단).
  - 데스크톱 + 웹 한 repo 유지. Tauri/Electron 안 가고 PWA + `launch.py` 로 데스크톱 경험.
  - DMM 깊은 hang 회복은 quiet wait가 핵심 (polling이 inactivity timer 리셋). `tools/dmm-recover`가 30 초 간격으로만 probe.

## 변경 파일 (이번 세션 — `e8e5bc6`)

- `web_app.py` — `DMMController.connect()` non-raise + replay mode, `_close_quietly()`, `_apply_mode()` 추출, `poll_loop` 가 reconnect cadence 소유, `_broadcast()` 추출, payload `ts` 추가, `/api/info`에 `connected`+`last_connect_ts`, `/api/mode` 503 매핑.
- `web/index.html` — `<span id="freshness">` 추가.
- `web/style.css` — status bar flex 정렬, `#freshness` / `.stale` 색상.
- `web/app.js` — `lastMsgClientMs` + `updateFreshness()` + `setInterval(500ms)`, ws.onopen 시 `fetchInfo()` 재호출, conn-dot e2e health 반영.
- `tests/test_endpoints.sh` — `tools/ma` 호출에 `MA_HOST=127.0.0.1 MA_PORT="$PORT"` 전달 (이전엔 ma가 default localhost:8000을 찾아 항상 실패).

(이전 세션 변경 파일은 `dd8dd42` 인계 노트 참조 — `scpi.py`, `sdm30xx_time_qt6.py`, `multimeter.ini`, `requirements.txt`, `launch.py`, `run.sh|command|bat`, `tools/build-macos-app.sh`, `tools/ma`, `tools/dmm-recover` 등.)

## 다음 할 일

- [x] HTTP API smoke test (`tests/test_endpoints.sh`) — 전체 통과.
- [x] `./run.sh` 더블클릭 실행 (Linux) — venv stamp + uvicorn 자동 기동 확인.
- [x] WebSocket polling 안정성 — 6 s 동안 24 frame ≈ 3.9 Hz, 끊김 없음.
- [x] **자동 재연결 시뮬레이션** (bogus host 192.168.0.250) — `connected:False`, error frame 즉시 broadcast, 2 s 간격 retry 사이클 확인.
- [ ] **실제 DMM OFF→ON 수동 검증** (사용자만 가능):
  1. PWA/브라우저로 접속, 임의 모드 선택 (예: VAC)
  2. DMM 후면 전원 OFF → status bar 빨강 `disconnected · last X s ago`, LCD `ERR`
  3. DMM 전원 ON (30–60 s) → 자동으로 reading 재개 + **VAC 모드 유지** + IDN 헤더 복원
  4. `/tmp/dmm-web.log`에 `connected: Siglent ... (restored VAC AUTO)` 라인 확인
- [ ] macOS 전용 검증: `./run.command` 더블클릭 → chromeless 윈도우, `./tools/build-macos-app.sh /Applications` → Spotlight, 브라우저 Install 버튼.
- [ ] iOS Safari / Android Chrome에서 PWA 설치 확인 (LAN 비-HTTPS → 데스크톱 Chrome은 install 거부할 수 있음, 그땐 `launch.py`로 우회).
- [ ] 점진 확장 (사용자 합의: DC mA 시작 + 확장): RES/CAP/Temp 모드 UI 보강, CSV 다운로드, mobile UI 폴리싱, Basic auth (LAN 외부 노출 시), SCDP screenshot 전송.
- [ ] upstream `martin-bochum/DMM-Siglent-SDM`에 데스크톱 fix만 PR로 보낼지 검토 (timeout 단위 버그, false→False, atexit, SYST:LOCal).

## 미해결 / 막힌 곳

- **SDM3055 펌웨어 깊은 hang은 전원 사이클 외 회복 불가** (펌웨어 한계). `dmm-recover`의 quiet wait도 90 초로 시도했지만 그것만으로는 안 됨. 일반 사용에서는 거의 안 생길 듯 (SO_LINGER + SYST:LOCal + atexit 예방).
- 데스크톱 앱과 웹앱 **동시 실행 불가** (SCPI 단일 client) — 한계 인지, README 명시.
- 웹앱이 startup 시점에 `multimeter.ini` 를 한 번만 읽음 → DMM IP를 다른 값으로 바꾸려면 서버 재시작 필요 (일반 사용에선 IP 안 바뀜).
- `web/icon.svg` 는 PWA install 시 사용되지만 일부 OS는 PNG만 받음. `icon-128.png` (기존 repo 아이콘) fallback. 더 큰 PNG(192/512)는 미생성.

## 참고

### 핵심 파일/라인 (이번 세션 추가/변경)
- `web_app.py:80` `DMMController` 클래스 docstring (재연결 모델 설명)
- `web_app.py:101` `RECONNECT_BACKOFF_S = 2.0`
- `web_app.py:118` `connect()` non-raise + replay mode
- `web_app.py:167` `_apply_mode()` — set_mode + connect 공용
- `web_app.py:208` `poll_once()` — error 시 `_connected=False`
- `web_app.py:246` `poll_loop()` — 재연결 cadence 소유, error frame broadcast
- `web_app.py:282` lifespan — 첫 connect 실패 시 last_reading seed
- `web_app.py:338` `/api/info` — `connected` + `last_connect_ts`
- `web/app.js:109` `lastMsgClientMs`, `lastReadingHadError`
- `web/app.js:132` `updateFreshness()` + `setInterval(500ms)` + dot e2e health
- `web/app.js:392` `openWS()` — ws.onopen 시 fetchInfo() 재호출

### 이전 세션 핵심 (참고용)
- `scpi.py:35` SCPISocket `__init__` (lock, RLock, _connect)
- `scpi.py:103` `ask()` — drain + try/except + reconnect + binary guard
- `scpi.py:148` `read_raw()` — finally에서 무조건 reconnect
- `sdm30xx_time_qt6.py:115` `init_dmm()`
- `sdm30xx_time_qt6.py:2353` `ende()` + `_ende_done` idempotent guard
- `sdm30xx_time_qt6.py:2380` `atexit.register(ende)` + signal handlers
- `web/app.js:30` SCALE_STEPS + applyScale + cycleScale
- `web/app.js:118` `chart` IIFE (circular buffer + draw + auto-scale)

### 커밋 히스토리 (최신순)
- `e8e5bc6` **이번 세션** — auto-reconnect + mode replay + freshness UI
- `dd8dd42` 이전 handoff
- `d7aed99` `tools/dmm-recover` 회복 도구
- `5d20503` `/api/reading` + `tools/ma` + server 입력 + scale 토글
- `56b95b9` run.sh/command/bat + .app 빌더
- `0b7c20d` launch.py + PWA
- `595beda` 실시간 canvas 차트
- `dd34e54` 웹앱(FastAPI + WebSocket) 최초
- `3463610` SCPISocket lock + read_raw post-reconnect (현재 transport)
- `b57f0fe` **timeout 단위 버그 fix** (진짜 hang 원인)

### 외부 연결
- DMM: Siglent SDM3055 @ `192.168.0.177:5025` (raw SCPI). VXI-11(111)도 열려있지만 사용 안 함.
- 리포지토리: https://github.com/withwave/DMM-Siglent-SDM (origin/main, 현재 HEAD `e8e5bc6`)
- upstream(fork 원본): https://github.com/martin-bochum/DMM-Siglent-SDM (GPL)

### PWA 자동 갱신
- `web/sw.js` 는 **network-first** (`fetch().then(cache.put).catch(cache.match)`) — install된 PWA도 윈도우 재실행 또는 새로고침 1회로 새 코드 자동 적용.
- 강제 무효화가 필요하면 `sw.js:4` 의 `CACHE = 'sdm-shell-vN'` 버전 bump.
