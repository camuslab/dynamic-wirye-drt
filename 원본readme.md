## Dynamic Wirye DRT 시뮬레이션

경기도 위례 지역을 가정한 동적 DRT(Demand Responsive Transport) 시뮬레이션 프로젝트입니다. 차량-수요 매칭, 경로 삽입, 반응형 리밸런싱 등을 통해 정책/파라미터 변화가 성능지표에 미치는 영향을 분석합니다.

### 빠른 시작

- 요구사항
  - Python 3.13 권장
  - Node.js 18+ (프런트엔드 시각화 사용 시)

- 가상환경
  - 동봉된 환경 사용:  
    Powershell
    ```
    .\dynamic_drt\bin\Activate.ps1
    ```
  - 새로 만들기(선택):  
    ```
    python -m venv .venv
    .\.venv\Scripts\Activate.ps1
    pip install -r requirements.txt   # 파일이 있을 경우
    ```

### 디렉터리 구조

- `scripts/`: 핵심 시뮬레이션 로직과 유틸
  - `engine.py`: 시뮬레이션 엔진(이벤트 루프, 매칭/삽입 등)
  - `assignment.py`, `insertion.py`: 배차/경로 삽입
  - `reactive_rebalance.py`: 반응형 리밸런싱
  - `config.py`: 주요 파라미터 설정
  - `run_wirye.py`, `run_sweep.py`: 실행 엔트리포인트
- `data/`: 입력 데이터 (예: `parquet/` 원시/전처리 파일)
- `outputs/`: 시뮬레이션 결과(JSON; `attempts.json`, `events.json`, `moves.json`, `summary.json` 등)
- `results/`: 집계/비교 결과(CSV, PNG)
- `react-project/`: 웹 시각화(지도/차트) 프런트엔드
- `figs/`: 생성된 그래프 이미지
- 노트북들: 분석/시각화/민감도(`분석.ipynb`, `시각화.ipynb`, `파라미터-민감도분석.ipynb`, `성능평가지표.ipynb` 등)

### 데이터

- 위치: `data/`
  - 예: `data/parquet/wirye_trip_20240102.parquet`
- 요구 스키마(예시): 요청 시각, 픽업/드롭 수요 위치, 승객 수, (선택) OSRM 매칭용 좌표 등
- 주의: 큰 파일은 VCS 제외 권장

### 설정(`scripts/config.py`)

- 예시 파라미터: 차량 대수, 차량 용량, 최대 대기시간, 허용 우회율, 재시도 횟수, 시간해상도, 리밸런싱 주기 등
- 정책 실험은 이 파일을 수정하거나 실행 시 인자로 주입

### 실행 방법

- 단일 시나리오
  ```
  python .\scripts\run_wirye.py
  ```
  - 결과는 `outputs/<시나리오명>/`에 JSON으로 저장

- 파라미터 스윕
  ```
  python .\scripts\run_sweep.py
  ```
  - 결과는 `outputs/run_sweep/` 및 `outputs/run_sweep_report/`(CSV) 생성

### 산출물

- `outputs/<scenario>/`
  - `attempts.json`: 요청 시도 기록
  - `events.json`: 이벤트 타임라인
  - `moves.json`: 차량 이동
  - `reroutes.json`: 재경로 이력
  - `summary.json`: 핵심 성능지표 요약(성공률, 평균대기, 평균탑승 등)
  - `tracks.json`: 트래킹(지도 시각화용)
- `results/`: 비교/집계 결과(CSV, PNG) 및 트레이드오프 그래프

### 시각화

- 노트북
  ```
  jupyter lab
  ```
  - `분석.ipynb`, `시각화.ipynb` 등을 열어 결과 탐색

- 웹(React)
  ```
  cd react-project
  npm install
  npm run dev
  ```
  - 브라우저에서 로컬 서버 접속
  - 필요시 `react-project/public/data/`에 결과 JSON을 배치해 바로 로딩

### 재현성/로그

- 실행 로그: `runtime_log.csv`
- 실험 메타/결과는 폴더명 규칙과 함께 `results/` CSV로 관리 권장
- 시드 고정(해당 시드 옵션이 있을 경우)으로 실험 재현성 확보

### 개발 가이드

- 코드 스타일: 명확한 함수/변수명, 예외/엣지케이스 우선 처리
- 캐시 파일: `__pycache__/`, `*.pyc`는 삭제해도 무방(자동 재생성). VCS 제외 권장
- `.gitignore` 권장
  ```
  __pycache__/
  *.pyc
  .venv/
  dynamic_drt/
  data/parquet/
  outputs/
  results/
  .DS_Store
  ```

### 문제 해결

- OSRM/네트워킹 관련 오류: `scripts/osrm_client.py` 설정 확인
- 메모리 이슈: 스윕 범위 축소, 배치 실행
- 권한/경로 이슈(Windows): PowerShell 실행 정책 및 경로에 공백 여부 확인

### 라이선스/문의

- 라이선스: (프로젝트에 맞게 명시)
- 문의: (이메일/이슈 트래커)
