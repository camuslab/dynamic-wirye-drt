# 파일: scripts/insertion.py
# - (하드) 양방향 픽업창, 우회율, 용량, 순서 무결성
# - (하드) 신규요청 pick/drop 모두 포함, 기존승객 drop 미손실
# - (하드) drop ETA ≤ P._drop_deadline_abs (엔진에서 셋업)
# - λ(head-only) 창 탐색

from __future__ import annotations
from typing import Tuple, List, Optional
# dataclass import 제거 (더 이상 필요 없음)

from ..models.data_models import Request, VehicleState, Stop, InsertionDecision  # InsertionDecision 추가
from ..config.config import ServiceParams
from ..utils.utils import segment_times, straight_line_seconds
from ..routing.osrm_client import OSRM

# InsertionDecision 클래스 정의 제거 (16-20줄 삭제)

def _simulate_schedule(v: VehicleState, sched: List[Stop],
                       P: ServiceParams, osrm_obj: Optional[OSRM]) -> Tuple[float, List[float]]:
    t = 0.0
    arrivals: List[float] = []
    cur_lon, cur_lat = v.lon, v.lat
    for s in sched:
        seg = segment_times([(cur_lon, cur_lat), (s.lon, s.lat)],
                            P.use_osrm, osrm_obj, P.avg_speed_kmh)
        travel = seg[0] if seg else 0.0
        t += travel
        arrivals.append(t)
        t += P.service_time_sec
        cur_lon, cur_lat = s.lon, s.lat
    return t, arrivals

def evaluate_feasibility_and_cost(
    v: VehicleState, new_sched: List[Stop], r: Request,
    P: ServiceParams, osrm_obj: Optional[OSRM], now_abs: float
) -> Tuple[bool, float]:
    big_m = float(getattr(P, "big_m", 1e12))

    # --- 스케줄 길이(2C) ---
    n_events = sum(1 for s in new_sched if s.kind in ("pickup", "dropoff"))
    if n_events > 2 * int(P.vehicle_capacity):
        return False, big_m

    # --- 기존승객 drop 미손실 + 용량 시뮬 ---
    load = len(v.onboard_reqs)
    onboard = set(v.onboard_reqs)
    for s in new_sched:
        if s.kind == "pickup":
            if s.req_id not in onboard:
                load += 1
                onboard.add(s.req_id)
        else:
            if s.req_id in onboard:
                load -= 1
                onboard.remove(s.req_id)
        if load > P.vehicle_capacity or load < 0:
            return False, big_m

    for rid in v.onboard_reqs:
        if not any(s.kind == "dropoff" and s.req_id == rid for s in new_sched):
            return False, big_m

    # --- 신규요청 pick/drop 둘 다 존재 & 순서 ---
    try:
        pi = next(i for i, s in enumerate(new_sched) if s.kind == "pickup"  and s.req_id == r.req_id)
        di = next(i for i, s in enumerate(new_sched) if s.kind == "dropoff" and s.req_id == r.req_id)
    except StopIteration:
        return False, big_m
    if di <= pi:
        return False, big_m

    # --- 시간계산 ---
    total_td, arrivals = _simulate_schedule(v, new_sched, P, osrm_obj)
    base_abs = float(now_abs)
    t_pick_abs = base_abs + arrivals[pi]
    t_drop_abs = base_abs + arrivals[di]

    # --- 픽업창 (조기픽업 금지): t_request ≤ t_pick ≤ t_request + pickup_late_sec ---
    desired = float(r.t_request)
    late    = float(getattr(P, "pickup_late_sec", getattr(P, "max_wait_sec", 900)))
    if not (desired <= t_pick_abs <= desired + late):
        return False, big_m    

    # --- 탑승시간 & 우회율 ---
    ride_time = max(0.0, t_drop_abs - (t_pick_abs + P.service_time_sec))
    max_cap = getattr(P, "max_ride_time_sec", None)
    if max_cap is not None and ride_time > float(max_cap):
        return False, big_m

    if P.use_osrm and osrm_obj:
        od_sec = osrm_obj.oneway_duration_sec(r.o_lon, r.o_lat, r.d_lon, r.d_lat)
    else:
        od_sec = straight_line_seconds(r.o_lon, r.o_lat, r.d_lon, r.d_lat, P.avg_speed_kmh)
    od_sec = max(1.0, float(od_sec))
    detour = ride_time / od_sec
    if detour > float(getattr(P, "detour_ratio_max", 2.0)):
        return False, big_m

    # --- 드롭 ETA 데드라인(엔진에서 설정) ---
    ddl = getattr(P, "_drop_deadline_abs", None)
    if ddl is not None and t_drop_abs > float(ddl):
        return False, big_m

    return True, float(total_td)

def best_insertion_for_vehicle(
    r: Request, v: VehicleState, P: ServiceParams, osrm_obj: Optional[OSRM], now_abs: float
) -> Optional[InsertionDecision]:
    sched = list(v.schedule)

    if not sched:
        trial = [Stop("pickup", r.req_id, r.o_lon, r.o_lat),
                 Stop("dropoff", r.req_id, r.d_lon, r.d_lat)]
        feas, td = evaluate_feasibility_and_cost(v, trial, r, P, osrm_obj, now_abs)
        # ✅ veh_id 추가
        return InsertionDecision(r.req_id, v.veh_id, trial, td) if feas else None

    n = len(sched)

    if getattr(P, "insert_pick_window", None) is None:
        pick_end = n
    else:
        k = max(1, int(P.insert_pick_window))
        pick_end = min(n, k)

    best: Optional[InsertionDecision] = None

    for i in range(0, pick_end + 1):
        if getattr(P, "insert_drop_window", None) is None:
            drop_last = n + 1
        else:
            lam = max(1, int(P.insert_drop_window))
            drop_last = min(n + 1, i + 1 + lam)

        for j in range(i + 1, drop_last + 1):
            new_sched = (
                sched[:i]
                + [Stop("pickup", r.req_id, r.o_lon, r.o_lat)]
                + sched[i:j-1]
                + [Stop("dropoff", r.req_id, r.d_lon, r.d_lat)]
                + sched[j-1:]
            )
            feas, td = evaluate_feasibility_and_cost(v, new_sched, r, P, osrm_obj, now_abs)
            if not feas:
                continue
            if (best is None) or (td < best.cost_sec):
                # ✅ veh_id 추가, 파라미터 순서: req_id, veh_id, new_schedule, cost_sec
                best = InsertionDecision(r.req_id, v.veh_id, new_sched, td)

    return best