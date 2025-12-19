"""
시뮬레이션 전역 파라미터와 입출력 경로 정의
- 대기시간 제약: 요청(t_request)→픽업 ≤ 대기시간(10분)
- 우회율 상한: 2.0배
- λ-삽입창: 전체 구간 탐색
"""

from dataclasses import dataclass

# =========================
# 1) 파라미터 클래스
# =========================
@dataclass
class ServiceParams:
    # ----- 배치 시뮬레이션 기본 -----
    batch_seconds: int = 60               # 배치 간격(초)
    service_time_sec: int = 10            # 정차(픽업/드롭) 서비스 시간(초)
    vehicle_capacity: int = 5             # 차량 최대 탑승 인원

    # ----- 대기/우회 제약 -----
    pickup_early_sec: int = 0             
    pickup_late_sec: int = 600            # 대기시간 10분
    detour_ratio_max: float = 2.0         # 우회율 상한(실제탑승/OD최단)

    # ----- OSRM 이동시간/경로 -----
    use_osrm: bool = True
    osrm_base_url: str = "http://127.0.0.1:8000"
    osrm_profile: str = "driving"
    avg_speed_kmh: float = 30.0           # OSRM 미사용 시 직선+평균속도 근사

    # ----- λ(람다) 삽입창 (head-only) -----
    insert_pick_window = None             # None → 픽업위치 전 구간 탐색
    insert_drop_window = None             # None → 드롭위치 전 구간 탐색

    # ----- 리밸런싱 -----
    enable_rebalance: bool = True
    rebalance_interval_sec: int = 120     # 리액티브 주기 짧게

    # ----- 재시도(완화) -----
    max_retries: int = 2                  # 총 3번(초기 1 + 재시도 2)
    wait_bonus_per_retry_sec: int = 180   # 재시도마다 허용 '늦게 픽업' +3분
    wait_bonus_cap_sec: int = 600         # 늦게 픽업 완화 상한 +10분
    detour_bonus_per_retry: float = 0.25  # 재시도마다 detour 비율 +0.25
    detour_bonus_cap: float = 3.0         # detour 최대 3.0배

    # ----- 실험/로그 -----
    fleet_size: int = 40                  # 차량 수
    big_m: float = 1e12
    log_every_batches: int = 1
    debug_max_batches: int | None = None
    debug_max_requests: int | None = None

    # ----- 테일 플러시 -----
    tail_flush_max_sec: int | None = 10800

# =========================
# 2) 입출력 경로/태그
# =========================
INPUT_PATH: str = "data/processed/240307_wirye_od.parquet"

RUN_TAG: str = "40대(nonkey1)"            # 시나리오 명칭

def _out(p: str) -> str:
    return f"outputs/{RUN_TAG}/{p}"

OUT_SUMMARY: str = _out("summary.json")
OUT_EVENTS:  str = _out("events.json")
OUT_TRACKS:  str = _out("tracks.json")
OUT_MOVES:   str = _out("moves.json")
OUT_REROUTE: str = _out("reroutes.json")
OUT_ATTEMPTS: str = _out("attempts.json")
 

# =========================
# 3) 시뮬레이션 시간창/샘플링
# =========================
SIM_START_SEC: int | None = 25200
SIM_END_SEC:   int | None = 34200
LIMIT_N:       int | None = None     # 전제 요청
LIMIT_RANDOM:  bool = False          # 랜덤 샘플링
LIMIT_SEED:    int = 42