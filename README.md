# Linux/Debian Digital Multimeter Software
Digital Multimeter Control over LAN

Linux / Debian / RaspiOS

Siglent SDM3055, SDM3055-SC<br>

read <font size="3"><a href="https://github.com/martin-bochum/DMM-Siglent-SDM/blob/main/README" target="_blank" >README</a> !
<br>
Video: <font size="3"><a href="http://martin-bochum.de/Cloud/Siglent-SDM3055-SC.m4v" target="_blank" >SC-Card in action</a>
<br>
Video: <font size="3"><a href="http://martin-bochum.de/Cloud/Siglent-SDM3055-SC-ACI-OK.m4v" target="_blank" >SC-Card ACI bug fix</a>

![Screenshot_20250317_115940](https://github.com/user-attachments/assets/4242f7b8-4151-4e38-b9b7-db972df79422)
![Screenshot_20250317_120028](https://github.com/user-attachments/assets/4dc56fd5-fd3e-4509-bc1d-b43ae2bb3075)
![Screenshot_20250317_120331](https://github.com/user-attachments/assets/58e40b15-4aad-4f02-bce3-215c3c253d1b)
![Screenshot_20250317_121036](https://github.com/user-attachments/assets/98e368f6-c91b-436d-bf42-5f0e8d2caf74)

## macOS 설치 및 실행

macOS에서도 사용할 수 있습니다. (테스트 환경: Python 3.14, Homebrew, Apple Silicon)

### 의존성 설치

```bash
# Homebrew Python 권장
brew install python

# 프로젝트 디렉터리에서 가상환경 생성 (권장)
cd ~/AI/DMM-Siglent-SDM
python3 -m venv .venv
source .venv/bin/activate

# 의존성 설치
pip install -r requirements.txt
```

### 설정

`multimeter.ini`에서 DMM의 IP 주소를 확인하세요. 기본값: `HOST = 192.168.0.177`.

### 실행

```bash
# 반드시 프로젝트 디렉터리에서 실행 (multimeter.ini와 .ui 파일 상대 경로)
cd ~/AI/DMM-Siglent-SDM
python3 sdm30xx_time_qt6.py
```

DMM 연결 실패 시 크래시 대신 명확한 에러 메시지가 표시됩니다.

### DC 전류(mA) 빠른 시작

앱 실행 후 함수 다이얼에서 `DCI`를 선택하고, 레인지를 `20mA` 또는 `200mA`로 설정하면 DC 전류 측정이 시작됩니다.

### macOS 관련 참고

- 'Noto Sans', 'DejaVu Sans Mono' 폰트가 없어도 시스템 sans-serif/monospace로 자동 폴백됩니다.
- USB 드라이버는 필요 없습니다 (LAN/raw SCPI on port 5025, 내장 `scpi.py`만 사용 — `python-vxi11` 불필요).
- 앱 시작 시 자동으로 DCI(DC current mA) 모드로 진입합니다 — DC 전류 측정이 주 사용 사례.
- 종료 시 `ende()`가 ABORt + *CLS + SYSTem:LOCal을 보내 DMM Remote Lock을 해제합니다. SIGTERM/SIGINT/atexit으로도 보장 호출.

## 웹앱 (브라우저 접근)

같은 DMM을 로컬 네트워크의 어떤 장치(태블릿, 폰, 다른 PC)에서도 브라우저로 보고 조작할 수 있는 FastAPI + WebSocket 앱이 함께 포함되어 있습니다.

```bash
cd ~/AI/DMM-Siglent-SDM
source .venv/bin/activate
pip install -r requirements.txt        # fastapi + uvicorn 포함
uvicorn web_app:app --host 0.0.0.0 --port 8000
```

그다음 같은 네트워크의 브라우저에서 `http://<이 컴퓨터의 IP>:8000` 접속.

- 데스크톱 앱과 동시 실행 불가 — SDM3055의 SCPI raw socket은 동시 1 클라이언트만 허용
- UI는 데스크톱과 동일한 룩앤필 (녹색 LCD + 다이얼 + 모드 버튼 + min/max)
- WebSocket으로 250 ms 주기 측정값 push
- 모드: DCI / ACI / VDC / VAC / RES / FREQ / CAP
- 종료(Ctrl-C) 시 데스크톱 앱과 동일하게 Remote Lock 해제 후 정리

코드 구성:
- `web_app.py` — FastAPI 앱, 폴링 task, WebSocket broadcast, REST API
- `web/index.html`, `web/style.css`, `web/app.js` — 정적 프론트엔드
- `web/manifest.json`, `web/sw.js` — PWA manifest + Service Worker
- `scpi.py` — SCPISocket transport (데스크톱/웹 공유)

### HTTP API (외부 스크립트/명령행에서 측정값 읽기)

웹앱이 떠 있는 동안 별도 SCPI 연결 없이 현재 측정값을 가져올 수 있습니다 (백엔드 폴링 태스크가 이미 250 ms 주기로 측정 중인 값을 그대로 노출 — DMM에 추가 부담 0).

| Endpoint | 응답 | 용도 |
|---|---|---|
| `GET /api/info` | JSON: IDN, host/port, 모드 카탈로그, 현재 mode/range | UI 초기화, 진단 |
| `GET /api/reading` | JSON: `{value, mode, range, prefix, min, max}` | 자동화 / 다른 스크립트 |
| `GET /api/reading.txt` | 텍스트 한 줄: `-30.7087 nA  DCI Auto` | 사람 / shell |
| `POST /api/mode/{mode}?range={arg}` | `{ok, mode, range}` | 모드 전환 (DCI/ACI/VDC/...) |
| `POST /api/reset-minmax` | `{ok: true}` | min/max 초기화 |
| `WS /ws` | 250 ms 주기 reading JSON push | 실시간 UI |

빠른 호출 예시:
```bash
curl -s http://localhost:8000/api/reading.txt
# -30.7087 nA  DCI Auto

curl -sX POST http://localhost:8000/api/mode/DCI?range=0.2
# {"ok":true,"mode":"DCI","range":"0.2"}
```

### `tools/ma` — 한 글자 명령으로 현재값 읽기

```bash
./tools/ma                  # 한 번
./tools/ma -w               # 0.5 s 마다 in-place 갱신 (watch)
./tools/ma -w 0.1           # 0.1 s 마다
MA_HOST=10.0.0.4 ./tools/ma # 다른 호스트
```

PATH에 심볼릭 링크하면 그냥 `ma`로 호출:
```bash
ln -s "$PWD/tools/ma" /usr/local/bin/ma
ma                          # +0.0024 mA  DCI Auto
```

웹앱이 실행 중이어야 하며 (SCPI 소켓 단일 client 제약), `tools/ma`는 SCPI에 직접 연결하지 않고 HTTP만 사용하므로 안전합니다.

### 다른 LAN 서버로 연결 / 화면 크기 모드

웹 UI 상단에 두 가지 컨트롤이 있습니다:

- **Server 입력란** — 비워두면 페이지를 띄운 호스트에 연결. 다른 컴퓨터의 백엔드를 보고 싶으면 `192.168.0.50:8000` 같이 입력 후 `Set`. localStorage에 저장돼서 새로고침 후에도 유지. WebSocket과 모든 REST 호출이 그 호스트로 전환. (백엔드는 CORS를 열어둠.)
- **`1×` 버튼** — 클릭할 때마다 화면 배율을 1× → ½× → ¼× → 1× 순으로 토글. 작은 화면이나 멀티 모니터에서 한쪽 구석에 띄우고 싶을 때 유용. `zoom` CSS 속성으로 모든 요소 + 클릭 영역이 비례 축소. localStorage에 저장.

### 데스크톱 앱처럼 실행하기 (PyQt 없이)

브라우저는 그대로 두고, 같은 웹앱을 "앱처럼" 띄우는 방법 세 가지. **위로 갈수록 한 번에 실행하기 쉬움.**

**방법 0 — macOS `.app` 번들 (가장 매끄러움, Spotlight/Dock 검색 가능)**
```bash
./tools/build-macos-app.sh                  # 프로젝트 폴더에 .app 생성
./tools/build-macos-app.sh /Applications    # 곧장 Applications로
```
빌드된 `Siglent SDM Web.app`을 **Finder에서 더블클릭** 또는 Spotlight로 검색. dock 아이콘도 정상 표시됨. 앱이 프로젝트 폴더의 `run.sh`를 호출하므로 `git pull` 만으로 업데이트 반영.

**방법 1 — 더블클릭 실행 스크립트 (`.app` 빌드 없이)**

| OS | 파일 | 실행 |
|---|---|---|
| macOS | `run.command` | Finder에서 더블클릭 → Terminal 자동 실행 |
| Linux | `run.sh` | `./run.sh` 또는 파일관리자에서 실행 |
| Windows | `run.bat` | 더블클릭 |

처음 실행 시 `.venv` 자동 생성 + `requirements.txt` 자동 설치 후 launch. 두 번째 실행부터는 즉시 시작.

**방법 A — `launch.py` 직접 (개발자용)**
```bash
source .venv/bin/activate
python3 launch.py            # 로컬에서만
python3 launch.py --lan      # 다른 기기도 접근 가능
python3 launch.py --no-browser  # 서버만 (모바일에서 접속)
```
- uvicorn을 자동 시작하고 Chrome/Edge/Brave/Arc를 `--app` 모드로 띄움 — 탭/주소창 없는 standalone 윈도우
- Ctrl-C로 종료 시 DMM Remote Lock 해제 후 정리

**방법 B — PWA 설치 (브라우저에서 "앱으로 설치")**

먼저 서버 띄우기:
```bash
uvicorn web_app:app --host 0.0.0.0 --port 8000
```

그 다음 브라우저에서 `http://localhost:8000` 열고:
- **Chrome / Edge**: 주소창 우측 끝의 ⊕ 설치 아이콘 클릭, 또는 메뉴 → "Siglent SDM Web 설치"
- **Brave**: 메뉴 → 앱 → 바로가기 만들기 → "창에서 열기"
- **iOS Safari**: 공유 → 홈 화면에 추가
- **Android Chrome**: 메뉴 → 홈 화면에 추가

설치 후엔 도크/홈에 아이콘이 생기고 standalone 창으로 열림. 같은 LAN의 폰/태블릿에서도 `http://<이 컴퓨터 IP>:8000` 으로 동일하게 설치 가능 (단 Chrome 데스크톱은 비-HTTPS LAN URL은 설치 거부할 수 있음 — 그땐 방법 A 사용).

### LAN의 다른 기기에서 설치

서버 PC에서 `./run.sh --lan` (콘솔에 `LAN: http://<IP>:8000` 출력됨). 다른 PC/모바일 브라우저로 그 URL을 열고 **Install** 버튼(모바일은 "홈 화면에 추가").

서버는 한 곳만 (SCPI 단일 client), 브라우저는 여럿 OK. 방화벽이 TCP 8000을 막으면 허용 필요.

### 만약 DMM이 응답하지 않으면 (Remote Lock / Stuck)

빠른 connect/disconnect 반복은 SDM3055의 LAN 펌웨어를 stuck 시킬 수 있습니다. 가벼운 것부터 차례로 시도:

```bash
./tools/dmm-recover           # 한 번 probe → 안 되면 quiet wait 2분 → 가이드 출력
./tools/dmm-recover --wait 0  # probe만, 안 되면 즉시 가이드
```

이 도구가 중요한 이유: stuck 상태에서 `ping` 이나 `nc` 같은 명령으로 자꾸 TCP SYN을 던지면 DMM의 inactivity timer가 매번 리셋되어 **영영 자체 회복 못 함**. `dmm-recover`는 길게 30초 간격으로만 probe하며 그동안 instrument가 timeout으로 stale session을 풀 기회를 줍니다.

매뉴얼 회복 순서:
1. **Front panel**: `Shift` + `Trigger` (또는 `Shift` + `Run/Hold`) → Local 전환
2. **Utility 메뉴**: `Utility` → `I/O` → `LAN` → `Apply` 또는 `Reset LAN`
3. **LAN 케이블 분리** 30초 → 재연결
4. **후면 전원 OFF** 10초 → ON (확실, 100%)

### 통합 테스트 (참고)

macOS Python 3.14 + PyQt6 6.11 + SDM3055 (192.168.0.177) 환경에서 검증됨:
- `*IDN?` 응답: `Siglent Technologies,SDM3055,...`
- ScanCard 자동 감지 (OFF/ON)
- DCI AUTO/200mA 레인지에서 안정적인 mA 측정
- 시작 시 자동 DCI 모드 진입 (GUI 스크린샷 확인)
