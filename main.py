# main.py - module 패키지 기반 DRT 시뮬레이션 실행
"""
위례 DRT 시뮬레이션 메인 실행 스크립트
"""

import os
import sys
import time
from pathlib import Path

# === (0) 프로젝트 루트 설정 ===
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

print(f"PROJECT_ROOT: {PROJECT_ROOT}")

# === (1) module 패키지에서 필요한 모듈 임포트 ===
from module.config.config import (
    ServiceParams,
    INPUT_PATH,
    RUN_TAG as _RUN_TAG_ORIG,
    SIM_START_SEC,
    SIM_END_SEC,
    LIMIT_N,
    LIMIT_RANDOM,
    LIMIT_SEED,
)

from module.io.loaders import load_requests_parquet
from module.io.exporters import save_json
from module.vehicle.vehicle_init import init_vehicles_random_distributed
from module.engine.engine import run_batches

# === (2) RUN_TAG 강제 변경 (비교용) ===
RUN_TAG = f"{_RUN_TAG_ORIG}"

print(f">>> RUN_TAG (override): {RUN_TAG}")

# === (3) 시뮬레이션 시작 ===
start_time = time.time()

# === (4) 파라미터 인스턴스 ===
P = ServiceParams()
print(f"\n>>> Params (after overrides): {P}")
print(f">>> Time window: start={SIM_START_SEC}, end={SIM_END_SEC}")
print(f">>> LIMIT_N={LIMIT_N} (random={LIMIT_RANDOM}, seed={LIMIT_SEED})")

# === (5) 요청 데이터 로드 ===
print("\n=== 요청 데이터 로드 ===")
requests = load_requests_parquet(
    INPUT_PATH,
    P,
    o_lon_col="출발_x",
    o_lat_col="출발_y",
    d_lon_col="도착_x",
    d_lat_col="도착_y",
    t_col="승차_timestamp",
)
print(f"[REQ] {len(requests)}개 요청 로드 완료")

# === (6) 차량 초기화 ===
print("\n=== 차량 초기화 ===")
vehicles = init_vehicles_random_distributed(P.fleet_size, seed=42)
print(f"[VEH] {len(vehicles)}대 차량 초기화 완료")

# === (7) OSRM 연결 테스트 ===
def test_osrm_connection(base_url: str = "http://127.0.0.1:8000") -> bool:
    try:
        import requests as rq

        start_lon, start_lat = 127.143, 37.479
        end_lon, end_lat = 127.150, 37.485

        route_url = f"{base_url}/route/v1/driving/{start_lon},{start_lat};{end_lon},{end_lat}"
        r = rq.get(route_url, params={"overview": "false"}, timeout=10)

        if r.status_code == 200 and r.json().get("routes"):
            dur = r.json()["routes"][0]["duration"]
            print(f"✓ OSRM 라우팅 테스트 성공: {dur:.1f}s")
            return True
        return False
    except Exception as e:
        print(f"✗ OSRM 연결 실패: {e}")
        return False

print("\n=== OSRM 연결 테스트 ===")
osrm_ok = test_osrm_connection(P.osrm_base_url)
if not osrm_ok and P.use_osrm:
    print("⚠️  OSRM 연결 실패 → 직선거리 근사 사용")
    P.use_osrm = False

# === (8) 시뮬레이션 실행 ===
print("\n=== 시뮬레이션 실행 ===")
t0_wall = time.perf_counter()
t0_cpu = time.process_time()

result = run_batches(requests, vehicles, P)

wall = time.perf_counter() - t0_wall
cpu = time.process_time() - t0_cpu

print(f"\n[LOG] RUN_TAG={RUN_TAG} | wall={wall:.2f}s | cpu={cpu:.2f}s")

# === (9) 결과 저장 ===
print("\n=== 결과 저장 ===")
SAVE_DIR = PROJECT_ROOT / "outputs" / RUN_TAG
os.makedirs(SAVE_DIR, exist_ok=True)

output_files = {
    "summary": SAVE_DIR / "summary.json",
    "events": SAVE_DIR / "events.json",
    "moves": SAVE_DIR / "moves.json",
    "tracks": SAVE_DIR / "tracks.json",
    "reroutes": SAVE_DIR / "reroutes.json",
}

save_json({"served": result["served"], "rejected": result["rejected"]}, output_files["summary"])
save_json(result["events"], output_files["events"])
save_json(result["moves"], output_files["moves"])
save_json(result["tracks"], output_files["tracks"])
save_json(result["reroutes"], output_files["reroutes"])

print("[JSON SAVED]")
for k, v in output_files.items():
    print(f"  ✓ {v}")

# === (10) 결과 요약 ===
served = len(result["served"])
rejected = len(result["rejected"])
total = served + rejected
success_rate = (served / total * 100) if total > 0 else 0.0

elapsed = time.time() - start_time

print("\n" + "=" * 50)
print("📊 최종 결과 (비교용 실행)")
print("=" * 50)
print(f"  - Output Dir : outputs/{RUN_TAG}")
print(f"  - Served     : {served}")
print(f"  - Rejected   : {rejected}")
print(f"  - Total      : {total}")
print(f"  - Success %  : {success_rate:.2f}")
print(f"  - Elapsed(s) : {elapsed:.2f}")
print("=" * 50)
