# 파일: scripts/reactive_rebalance.py
from __future__ import annotations
from typing import List, Tuple, Optional

def _dist_ll(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    # 간단한 평면 근사(위도 가중 포함)
    import math
    dx = (lon1 - lon2) * 111_320 * math.cos(math.radians((lat1 + lat2) / 2.0))
    dy = (lat1 - lat2) * 110_540
    return math.hypot(dx, dy)

def _veh_req_dist(v, r, osrm_obj, use_osrm: bool) -> float:
    # 거리/시간 점수: OSRM 있으면 duration, 없으면 직선거리
    if use_osrm and osrm_obj:
        try:
            return osrm_obj.oneway_duration_sec(v.lon, v.lat, r.o_lon, r.o_lat)
        except Exception:
            pass
    return _dist_ll(v.lon, v.lat, r.o_lon, r.o_lat)

def assign_idle_to_rejected(
    idle_vehicles: list,
    hot_requests: list,
    osrm_obj,
    P,
    k_top: int = 3,
) -> List[Tuple[str, str]]:
    """
    유휴 차량과 '핫' 요청을 그리디로 매칭.
    - 각 요청 r에 대해: idle과의 거리/시간 점수를 계산, 상위 k대 중 랜덤 1대 선택.
    - (veh_id, req_id) 리스트 반환. 실제 삽입평가는 엔진 쪽에서 수행.

    idle_vehicles: List[VehicleState]
    hot_requests : List[Request]  (또는 .o_lon/.o_lat 필드가 있는 Request 유사체)
    """
    import random

    if not idle_vehicles or not hot_requests:
        return []

    use_osrm = getattr(P, "use_osrm", False)
    # 요청은 오래 기다린 순(또는 t_request 순)으로
    hot_sorted = sorted(hot_requests, key=lambda r: getattr(r, "t_request", 0))
    idle_left = {v.veh_id: v for v in idle_vehicles}
    pairs: List[Tuple[str, str]] = []

    for r in hot_sorted:
        # 남은 idle만 스코어링
        scored = []
        for vid, v in idle_left.items():
            s = _veh_req_dist(v, r, osrm_obj, use_osrm)
            scored.append((s, vid))
        if not scored:
            break
        scored.sort(key=lambda x: x[0])
        top = [vid for _, vid in scored[:min(k_top, len(scored))]]
        chosen = random.choice(top)
        pairs.append((chosen, r.req_id))
        # 한 번 배정한 idle은 빼준다(한 r에 한 v만)
        idle_left.pop(chosen, None)

    return pairs