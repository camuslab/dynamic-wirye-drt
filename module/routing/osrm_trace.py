"""
파일명: scripts/osrm_trace.py (신규)
- OSRM 응답을 좌표/세그시간/누적타임스탬프로 변환
- 특정 시각 보간 좌표 계산
- VehicleState에 '다음 정차지'까지 active path 설정/갱신 헬퍼
"""

from typing import List, Tuple
from .osrm_client import OSRM
from .osrm_client import OSRM  # 같은 폴더이므로 그대로
from ..models.data_models import VehicleState, Stop

def build_trace(start: Tuple[float, float], end: Tuple[float, float], osrm: OSRM):
    """
    return: coords(list[[lon,lat]]), seg_durs(list[float]), timestamps(list[float])
    """
    info = osrm.route_full(start, end)
    coords = [(float(x), float(y)) for x, y in info["coords"]]
    seg_durs = [float(s) for s in info["seg_durs"]]
    # 누적 타임스탬프
    ts = [0.0]
    acc = 0.0
    for d in seg_durs:
        acc += d
        ts.append(acc)
    return coords, seg_durs, ts

def position_at_time(coords: List[Tuple[float,float]], timestamps: List[float], t_sec: float) -> Tuple[float,float]:
    if not coords or len(coords) == 1:
        return coords[0] if coords else (0.0, 0.0)
    if t_sec <= 0: return coords[0]
    if t_sec >= timestamps[-1]: return coords[-1]
    import bisect
    i = bisect.bisect_right(timestamps, t_sec) - 1
    i = max(0, min(i, len(coords) - 2))
    t0, t1 = timestamps[i], timestamps[i+1]
    ratio = 0.0 if (t1 - t0) <= 0 else (t_sec - t0) / (t1 - t0)
    x1, y1 = coords[i]
    x2, y2 = coords[i+1]
    return (x1 + (x2 - x1) * ratio, y1 + (y2 - y1) * ratio)

def set_active_path_to_next_stop(v: VehicleState, osrm: OSRM):
    """차량 v의 현위치 → 다음 stop까지 OSRM 궤적을 active_* 필드에 세팅"""
    if not v.schedule:
        v.clear_active_path()
        return
    start = (v.lon, v.lat)
    end = (v.schedule[0].lon, v.schedule[0].lat)
    coords, _, ts = build_trace(start, end, osrm)
    v.active_coords = coords
    v.active_timestamps = ts
    v.active_elapsed = 0.0

def advance_vehicle_by(v: VehicleState, dt_sec: float):
    """배치 간격(dt_sec)만큼 진행(보간) → 위치 갱신/도착 처리(정차시간은 엔진에서 더하기)"""
    if not v.has_active_path():
        return
    v.active_elapsed += dt_sec
    x, y = position_at_time(v.active_coords, v.active_timestamps, v.active_elapsed)
    v.lon, v.lat = x, y
    # 경로 완료 시 active clear 및 stop 소비는 엔진(run_batches) 쪽에서 처리 권장