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
- USB 드라이버는 필요 없습니다 (LAN/VXI-11 통신).
- Python 3.13+ 사용 시 stdlib에서 제거된 `xdrlib`이 `python-vxi11`의 의존성입니다. `requirements.txt`의 `standard-xdrlib` 백포트로 자동 처리됩니다.

### 통합 테스트 (참고)

macOS Python 3.14 + PyQt6 6.11 + SDM3055 (192.168.0.177) 환경에서 검증됨:
- `*IDN?` 응답: `Siglent Technologies,SDM3055,...`
- ScanCard 자동 감지 (OFF/ON)
- DCI AUTO/200mA 레인지에서 안정적인 mA 측정 확인
