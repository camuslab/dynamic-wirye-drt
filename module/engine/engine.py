# 파일: scripts/engine.py
"""
메인 배치 엔진
- 절대시각 기반 재시도/타임아웃(배치 틱에 비민감)
- 스케줄 무결성 검사(기존 탑승자 drop 미손실, 신규 pick/drop 쌍 보장)
- 드롭 ETA 데드라인: t_end + tail_flush_max_sec (sec 우선, 없으면 구버전 batch방식 환산)
- 리액티브 리밸런싱: '핫' 요청 우선, 유휴차량과 최근접 매칭(외부 모듈 있으면 우선 사용)
"""

from __future__ import annotations
from typing import List, Dict, Tuple, Optional
from dataclasses import replace
import time, os, json, math, random

from ..config.config import ServiceParams, OUT_SUMMARY, OUT_ATTEMPTS
from ..models.data_models import Request, VehicleState, Stop
from ..dispatch.context_mapping import select_candidate_vehicles
from ..dispatch.insertion import best_insertion_for_vehicle, _simulate_schedule
from ..dispatch.assignment import solve_lap
from ..routing.osrm_client import OSRM
from ..utils.utils import segment_times

ENGINE_PATCH_TAG = "drop-deadline+strict-apply+abs-timeout+tail-sec"

# ----------------- 유틸 -----------------
def _fmt_hms(sec: float) -> str:
    sec = int(max(0, sec))
    h = sec // 3600; m = (sec % 3600) // 60; s = sec % 60
    return f"{h:d}:{m:02d}:{s:02d}"

def _sched_snapshot(v: VehicleState) -> List[dict]:
    return [{"kind": s.kind, "req_id": s.req_id, "lon": s.lon, "lat": s.lat} for s in v.schedule]

def _any_schedule_left(vehicles: List[VehicleState]) -> bool:
    return any(v.schedule for v in vehicles)

# --- 재시도에 따른 제약 완화(Detour + Pickup Late) ---
def _eff_limits(P: ServiceParams, retries: int) -> ServiceParams:
    if retries <= 0:
        return P
    # detour 완화
    base_detour = float(getattr(P, "detour_ratio_max", 2.0))
    step_detour = float(getattr(P, "detour_bonus_per_retry", 0.0)) * retries
    cap_detour  = float(getattr(P, "detour_bonus_cap", base_detour))
    eff_detour  = min(base_detour + step_detour, cap_detour)
    # 늦게 픽업(late) 완화
    base_late = float(getattr(P, "pickup_late_sec", getattr(P, "max_wait_sec", 0.0)))
    bonus_per = float(getattr(P, "wait_bonus_per_retry_sec", 0.0))
    cap_bonus = float(getattr(P, "wait_bonus_cap_sec", 0.0))
    add_late  = min(bonus_per * retries, cap_bonus)
    eff_late  = base_late + add_late
    return replace(P, detour_ratio_max=eff_detour, pickup_late_sec=eff_late)

# ------------- 이동/이벤트 처리 -------------
def advance_vehicles(vehicles, dt, P, osrm_obj, events, moves, now):
    for v in vehicles:
        remain = dt
        while remain > 0 and v.schedule:
            start_lon, start_lat = v.lon, v.lat
            dest = v.schedule[0]
            seg = segment_times([(start_lon, start_lat), (dest.lon, dest.lat)],
                                P.use_osrm, osrm_obj, P.avg_speed_kmh)
            travel = seg[0] if seg else 0.0

            if travel > remain:
                # 부분 이동
                if P.use_osrm and osrm_obj:
                    new_lon, new_lat = osrm_obj.progress_point_by_time(
                        (start_lon, start_lat), (dest.lon, dest.lat), elapsed_s=remain
                    )
                else:
                    frac = max(0.0, min(1.0, remain / max(1e-9, travel)))
                    new_lon = start_lon + (dest.lon - start_lon) * frac
                    new_lat = start_lat + (dest.lat - start_lat) * frac

                moves.append({
                    "veh_id": v.veh_id,
                    "t_start": int(now + (dt - remain)),
                    "t_end":   int(now + dt),
                    "lon1": start_lon, "lat1": start_lat,
                    "lon2": new_lon,   "lat2": new_lat,
                    "partial": True,
                    "load": len(v.onboard_reqs)
                })

                v.lon, v.lat = new_lon, new_lat
                v.t_avail += remain
                remain = 0
                break

            # 전체 leg 완료
            moves.append({
                "veh_id": v.veh_id,
                "t_start": int(now + (dt - remain)),
                "t_end":   int(now + (dt - remain) + travel),
                "lon1": start_lon, "lat1": start_lat,
                "lon2": dest.lon,  "lat2": dest.lat,
                "partial": False,
                "load": len(v.onboard_reqs)
            })
            v.t_avail += travel
            remain   -= travel

            # 서비스 시간
            v.t_avail += P.service_time_sec
            remain    -= P.service_time_sec

            # 스톱 처리
            s = v.schedule.pop(0)
            v.lon, v.lat = s.lon, s.lat

            if s.kind == "rebalance":
                continue  # 리밸런스 스톱은 승하차 없음

            ev_type = "PICKUP" if s.kind == "pickup" else "DROPOFF"
            events.append({
                "t": int(now + (dt - max(0, remain))),
                "type": ev_type, "veh_id": v.veh_id, "req_id": s.req_id,
                "lon": v.lon, "lat": v.lat
            })
            if s.kind == "pickup":
                if s.req_id not in v.onboard_reqs:
                    v.onboard_reqs.append(s.req_id)
            else:
                if s.req_id in v.onboard_reqs:
                    v.onboard_reqs.remove(s.req_id)

        if remain > 0:
            v.t_avail += remain

# ------------- 메인 루프 -------------
def run_batches(requests: List[Request], vehicles: List[VehicleState], P: ServiceParams) -> Dict:
    print(f"[ENGINE] patch={ENGINE_PATCH_TAG} | OSRM={getattr(P,'use_osrm',False)}", flush=True)

    osrm_obj = OSRM(P.osrm_base_url, P.osrm_profile) if getattr(P, "use_osrm", False) else None

    current   = requests[0].t_request if requests else 0
    t_end     = requests[-1].t_request if requests else 0
    total_reqs = len(requests)

    # --- 드롭 ETA 데드라인(마지막요청 + tail) 설정 (sec 우선) ---
    tail_window_sec = getattr(P, "tail_flush_max_sec", None)
    if tail_window_sec is None:
        # 구버전 호환: 배치개수→초 환산
        _tail_batches = getattr(P, "tail_flush_max_batches", 360)
        tail_window_sec = (10**9 if _tail_batches is None else int(_tail_batches) * int(getattr(P, "batch_seconds", 30)))
    deadline_drop_sec = int(t_end + int(tail_window_sec))
    setattr(P, "_drop_deadline_abs", float(deadline_drop_sec))
    print(f"[CFG] tail_window_sec={tail_window_sec} | drop-deadline={deadline_drop_sec} (t_end={t_end})", flush=True)

    served, rejected = [], []
    events, moves, tracks, reroutes = [], [], [], []
    attempts: Dict[str, Dict] = {}

    for v in vehicles:
        tracks.append({"veh_id": v.veh_id, "points": []})

    pending: List[Request] = []
    retries: Dict[str, int] = {}  # (통계/호환 유지)

    # 절대시각 기반 상태 테이블
    # pending_state[rid] = {"retry_idx": int, "late_eff": float, "deadline": float}
    pending_state: Dict[str, Dict] = {}

    # ★ 추가: 요청 조회/허용지연 테이블
    req_map = {r.req_id: r for r in requests}   # rid -> Request
    allowed_late: Dict[str, float] = {}         # rid -> 'ASSIGN 시 확정한 pickup late 허용(초)'

    next_idx = 0

    start_wall = time.perf_counter()
    batch_no = 0
    print(f"[START] 총 요청 {total_reqs}건 | 차량 {len(vehicles)}대 | Δt={P.batch_seconds}s", flush=True)

    def _safe_eff_limits(P0, k):
        try:
            return _eff_limits(P0, k)
        except Exception:
            P2 = replace(P0)
            try:
                base_late = float(getattr(P0, "pickup_late_sec", getattr(P0, "max_wait_sec", 0.0)))
                bonus_per = float(getattr(P0, "wait_bonus_per_retry_sec", 0.0))
                cap_bonus = float(getattr(P0, "wait_bonus_cap_sec", 0.0))
                P2.pickup_late_sec = base_late + min(bonus_per * k, cap_bonus)
            except Exception:
                pass
            return P2

    # === 보강된 스케줄 적용: 정책하드가드 + 기존픽업ETA 악화금지 ===
    def _sched_apply(v, decision, now_abs,
                     req_map, allowed_late, this_req_allowed_late,
                     P, osrm_obj) -> bool:
        """무결성 + '기존 픽업 ETA 악화 금지' + '허용 지연 한도' 검사 후 적용"""
        before = _sched_snapshot(v)
        new_sched = decision.new_schedule

        # (0) 기존 픽업 ETA baseline 계산 (현 스케줄 기준)
        _, old_arrivals = _simulate_schedule(v, v.schedule, P, osrm_obj)
        old_pick_eta = {}  # req_id -> 기존 픽업 ETA(절대시각)
        cur_abs = float(now_abs)
        for idx, s in enumerate(v.schedule):
            if s.kind == "pickup":
                old_pick_eta[s.req_id] = cur_abs + float(old_arrivals[idx])

        # (1) 기존 탑승자 drop 미손실 + 신규 pick/drop 존재
        for rid in list(v.onboard_reqs):
            if not any(s.kind == "dropoff" and s.req_id == rid for s in new_sched):
                return False
        has_pick = any(s.kind == "pickup" and s.req_id == decision.req_id for s in new_sched)
        has_drop = any(s.kind == "dropoff" and s.req_id == decision.req_id for s in new_sched)
        if not (has_pick and has_drop):
            return False

        # (2) 새 스케줄 ETA 계산
        _, new_arrivals = _simulate_schedule(v, new_sched, P, osrm_obj)

        # (2-1) 요청별 허용 지연 한도 준비
        # 새로 배정되는 요청은 이번에 확정된 this_req_allowed_late 사용
        per_req_allow = dict(allowed_late)
        per_req_allow[decision.req_id] = float(this_req_allowed_late)

        # (2-2) '픽업 ETA가 더 늦어지지 않는' 하드 가드 + 허용지연 하드 가드
        SLACK = 1e-6  # 수치오차/서비스시간 보정용
        for idx, s in enumerate(new_sched):
            if s.kind != "pickup":
                continue
            rid = s.req_id
            req = req_map.get(rid)
            if not req:
                continue
            t_req = float(req.t_request)
            eta_new = cur_abs + float(new_arrivals[idx])
            allow_late = float(per_req_allow.get(
                rid,
                getattr(P, "pickup_late_sec", getattr(P, "max_wait_sec", 900))
            ))

            # (A) 정책 하드 가드: 요청+허용지연 이내여야 함
            if eta_new > t_req + allow_late + SLACK:
                return False

            # (B) 드리프트 금지: 기존 대비 픽업 ETA가 늦어지면 거절 (신규는 제외)
            if rid in old_pick_eta:
                eta_old = float(old_pick_eta[rid])
                if eta_new > eta_old + SLACK:
                    return False

        # (3) 통과 시 적용
        v.schedule = new_sched
        after = _sched_snapshot(v)
        reroutes.append({"t": int(now_abs), "veh_id": v.veh_id, "before": before, "after": after})
        return True

    # 즉시 배정(리액티브 등) 시에도 같은 가드 사용
    def _try_immediate_assign(v: VehicleState, r: Request, k_try: int, now_abs: float) -> Optional[str]:
        P_eff = _safe_eff_limits(P, k_try)
        try:
            dec = best_insertion_for_vehicle(r, v, P_eff, osrm_obj, now_abs=now_abs)
        except Exception as e:
            print(f"[WARN] best_insertion_for_vehicle 실패 veh={v.veh_id} req={r.req_id}: {e}")
            return None
        if not dec:
            return None

        # 이번 시도에서의 허용지연(초) 계산
        late_eff = float(getattr(P_eff, "pickup_late_sec", getattr(P_eff, "max_wait_sec", 900)))
        ok = _sched_apply(
            v, dec, now_abs=now_abs,
            req_map=req_map,
            allowed_late=allowed_late,
            this_req_allowed_late=late_eff,
            P=P, osrm_obj=osrm_obj
        )
        if not ok:
            return None

        # 적용 성공 → 이 요청의 허용지연을 고정 저장
        allowed_late[r.req_id] = late_eff
        return r.req_id

    # --- 메인 루프 ---
    while current <= t_end or pending or next_idx < total_reqs:
        batch_no += 1

        # (1) 신규 유입
        new_cnt = 0
        while next_idx < total_reqs and requests[next_idx].t_request < current + P.batch_seconds:
            r = requests[next_idx]
            pending.append(r)

            # 상태 초기화(절대시각)
            base_late = float(getattr(P, "pickup_late_sec", getattr(P, "max_wait_sec", 900)))
            pending_state[r.req_id] = {
                "retry_idx": 0,
                "late_eff": base_late,
                "deadline": float(r.t_request) + base_late,
            }

            retries[r.req_id] = 0
            attempts[r.req_id] = {"attempt": 1, "final_status": "pending"}
            next_idx += 1
            new_cnt += 1

        print(f"\n[Batch {batch_no}] t={current}~{current + P.batch_seconds} | 신규 {new_cnt} | 대기 {len(pending)} | 잔여 {total_reqs - next_idx}", flush=True)
        if not pending and next_idx >= total_reqs and current > t_end:
            break

        # (2) 비용행렬 초기화
        veh_map = {v.veh_id: i for i, v in enumerate(vehicles)}
        req_map_idx = {r.req_id: j for j, r in enumerate(pending)}
        m, n = len(vehicles), len(pending)
        big_m = getattr(P, "big_m", 1e12)
        cost = [[big_m for _ in range(n)] for _ in range(m)]
        pick = [[None for _ in range(n)] for _ in range(m)]

        # (3) 후보선정→삽입평가
        feas_count = 0
        for r in pending:
            st = pending_state.get(r.req_id, {"retry_idx": 0})
            k = int(st["retry_idx"])
            P_eff = _safe_eff_limits(P, k)

            try:
                cands = select_candidate_vehicles(r, vehicles, P_eff, retry_k=k, max_retries=getattr(P, "max_retries", 0))
            except Exception as e:
                print(f"[WARN] select_candidate_vehicles 실패 req={r.req_id}: {e}")
                cands = vehicles

            for v in cands:
                try:
                    dec = best_insertion_for_vehicle(r, v, P_eff, osrm_obj, now_abs=current)
                except Exception as e:
                    print(f"[WARN] insertion 실패 veh={v.veh_id} req={r.req_id}: {e}")
                    continue
                if not dec:
                    continue
                i, j = veh_map[v.veh_id], req_map_idx[r.req_id]
                if dec.cost_sec < cost[i][j]:
                    if cost[i][j] >= big_m: feas_count += 1
                    cost[i][j] = dec.cost_sec
                    pick[i][j] = dec

        # (4) LAP 매칭
        pairs = solve_lap(cost)
        print(f"  → LAP 결과: 매칭 {len(pairs)}건 | feasible 총 {feas_count}", flush=True)

        # (5) 스케줄 적용 + ASSIGN
        assigned_ids = set()
        for i, j in pairs:
            dec = pick[i][j]
            if not dec:
                continue
            v = vehicles[i]

            # 이 요청의 현재 재시도 단계에서의 허용 지연(초) 계산
            rid = dec.req_id
            st = pending_state.get(rid, {"retry_idx": 0})
            k_try = int(st["retry_idx"])
            P_eff = _safe_eff_limits(P, k_try)
            late_eff = float(getattr(P_eff, "pickup_late_sec", getattr(P_eff, "max_wait_sec", 900)))

            ok = _sched_apply(
                v, dec, now_abs=current,
                req_map=req_map,
                allowed_late=allowed_late,
                this_req_allowed_late=late_eff,
                P=P, osrm_obj=osrm_obj
            )
            if not ok:
                continue

            # 통과했으면 기록
            allowed_late[rid] = late_eff  # 이 요청의 허용 지연을 '고정'
            att_no = k_try + 1
            events.append({"t": int(current), "type": "ASSIGN", "veh_id": v.veh_id, "req_id": rid, "attempt": att_no})
            served.append(rid)
            attempts[rid] = {"attempt": att_no, "final_status": "served"}
            assigned_ids.add(rid)

        # (6) 타임아웃/재시도(절대시각)
        remain_pending = []
        for r in pending:
            if r.req_id in assigned_ids:
                continue

            st = pending_state.get(r.req_id)
            if not st:
                base_late = float(getattr(P, "pickup_late_sec", getattr(P, "max_wait_sec", 900)))
                st = pending_state.setdefault(r.req_id, {
                    "retry_idx": 0,
                    "late_eff": base_late,
                    "deadline": float(r.t_request) + base_late,
                })

            # 잘못된 t_request 방어
            if not isinstance(r.t_request, (int, float)) or (isinstance(r.t_request, float) and math.isnan(r.t_request)):
                rejected.append(r.req_id)
                attempts[r.req_id] = {"attempt": int(st["retry_idx"]) + 1, "final_status": "rejected"}
                events.append({"t": int(current), "type": "REJECT", "veh_id": None, "req_id": r.req_id, "reason": "bad_t_request"})
                continue

            desired  = float(r.t_request)
            deadline = float(st["deadline"])

            if current >= deadline:
                # 재시도 한도 확인
                if int(st["retry_idx"]) < int(getattr(P, "max_retries", 0)):
                    st["retry_idx"] += 1
                    base_late = float(getattr(P, "pickup_late_sec", getattr(P, "max_wait_sec", 900)))
                    add = min(
                        float(getattr(P, "wait_bonus_per_retry_sec", 0.0)) * float(st["retry_idx"]),
                        float(getattr(P, "wait_bonus_cap_sec", 0.0))
                    )
                    st["late_eff"] = base_late + add
                    st["deadline"] = desired + st["late_eff"]
                    retries[r.req_id] = int(st["retry_idx"])
                    attempts[r.req_id]["attempt"] = int(st["retry_idx"]) + 1
                    remain_pending.append(r)
                else:
                    rejected.append(r.req_id)
                    attempts[r.req_id] = {"attempt": int(st["retry_idx"]) + 1, "final_status": "rejected"}
                    events.append({"t": int(current), "type": "REJECT", "veh_id": None,
                                   "req_id": r.req_id, "reason": "pickup_window_timeout"})
            else:
                remain_pending.append(r)
        pending = remain_pending

        # (7) 리액티브(외부 모듈 우선, 없으면 내부 fallback)
        if getattr(P, "enable_rebalance", False):
            try:
                try:
                    from ..advanced.reactive_rebalance import assign_idle_to_rejected
                except (ImportError, ModuleNotFoundError, Exception):
                    assign_idle_to_rejected = None

                idle = [v for v in vehicles if len(v.schedule) == 0]
                if idle and pending:
                    mxr = getattr(P, "max_retries", 0)
                    hot = [r for r in pending if mxr >= 1 and retries.get(r.req_id, 0) >= (mxr - 1)]
                    if not hot:
                        pend_sorted = sorted(pending, key=lambda rr: (retries.get(rr.req_id, 0), rr.t_request))
                        hot = pend_sorted[-min(20, len(pend_sorted)):]

                    served_now = []
                    if assign_idle_to_rejected:
                        pairs_rb = assign_idle_to_rejected(idle, hot, osrm_obj, P, k_top=3)
                        for veh_id, rid in pairs_rb:
                            v = next((vv for vv in vehicles if vv.veh_id == veh_id), None)
                            r = next((rr for rr in pending if rr.req_id == rid), None)
                            if not (v and r):
                                continue
                            rid_ok = _try_immediate_assign(v, r, retries.get(r.req_id, 0), now_abs=current)
                            if rid_ok:
                                events.append({"t": int(current), "type": "REBALANCE_ASSIGN", "veh_id": v.veh_id, "req_id": r.req_id})
                                served.append(r.req_id)
                                attempts[r.req_id] = {"attempt": retries.get(r.req_id, 0)+1, "final_status": "served"}
                                served_now.append(r.req_id)
                    else:
                        def _dist(v, r_):
                            dx = (v.lon - r_.o_lon) * 111320 * math.cos(math.radians((v.lat + r_.o_lat)/2.0))
                            dy = (v.lat - r_.o_lat) * 110540
                            return math.hypot(dx, dy)
                        idle_left = [v for v in idle]
                        for r in hot:
                            scored = sorted((( _dist(v, r), v) for v in idle_left if len(v.schedule) == 0),
                                            key=lambda x: x[0])
                            pool = [v for _, v in scored[:min(3, len(scored))]]
                            if not pool:
                                continue
                            v = random.choice(pool)
                            rid_ok = _try_immediate_assign(v, r, retries.get(r.req_id, 0), now_abs=current)
                            if rid_ok:
                                events.append({"t": int(current), "type": "REBALANCE_ASSIGN", "veh_id": v.veh_id, "req_id": r.req_id})
                                served.append(r.req_id)
                                attempts[r.req_id] = {"attempt": retries.get(r.req_id, 0)+1, "final_status": "served"}
                                served_now.append(r.req_id)
                                idle_left = [vv for vv in idle_left if vv.veh_id != v.veh_id]
                    if served_now:
                        pending = [x for x in pending if x.req_id not in set(served_now)]
            except Exception as e:
                print("[WARN] reactive rebalancing skipped:", e)

        # (8) 이동 시뮬레이션 + 로그
        advance_vehicles(vehicles, P.batch_seconds, P, osrm_obj, events, moves, now=current)
        for k, v in enumerate(vehicles):
            tracks[k]["points"].append({
                "t": int(current + P.batch_seconds),
                "lon": v.lon, "lat": v.lat, "load": len(v.onboard_reqs)
            })
        current += P.batch_seconds

        processed = next_idx
        progress_read = processed / max(1, total_reqs)
        elapsed = time.perf_counter() - start_wall
        eta_sec = (elapsed / progress_read - elapsed) if progress_read > 0 else 0.0
        print(
            f"  → 요약: served {len(served)} | rejected {len(rejected)} | pending {len(pending)} | "
            f"읽기진행 {progress_read*100:.1f}% | 경과 {_fmt_hms(elapsed)} | ETA {_fmt_hms(eta_sec)}",
            flush=True
        )

    # ---------- 테일 플러시 (절대시각 데드라인) ----------
    tail_deadline = float(getattr(P, "_drop_deadline_abs", t_end))
    flushed_batches = 0
    if _any_schedule_left(vehicles):
        print("\n[TAIL] 남은 스케줄 소진 시작", flush=True)
    while _any_schedule_left(vehicles) and current < tail_deadline:
        advance_vehicles(vehicles, P.batch_seconds, P, osrm_obj, events, moves, now=current)
        for k, v in enumerate(vehicles):
            tracks[k]["points"].append({
                "t": int(current + P.batch_seconds),
                "lon": v.lon, "lat": v.lat, "load": len(v.onboard_reqs)
            })
        current += P.batch_seconds
        flushed_batches += 1
    if flushed_batches > 0:
        print(f"[TAIL] 소진 배치 수={flushed_batches} | 종료시각={int(current)} | 데드라인={int(tail_deadline)}", flush=True)

    # 종료 시 pending 남았으면 거절
    if pending:
        for r in pending:
            rejected.append(r.req_id)
            st = pending_state.get(r.req_id, {"retry_idx": retries.get(r.req_id, 0)})
            attempts[r.req_id] = {"attempt": int(st["retry_idx"]) + 1, "final_status": "rejected"}
            events.append({
                "t": int(current),
                "type": "REJECT",
                "veh_id": None,
                "req_id": r.req_id,
                "reason": "end_flush"
            })

    elapsed_total = time.perf_counter() - start_wall
    print(f"\n[END] 완료! 성공 {len(served)}, 실패 {len(rejected)} | 총 경과 {_fmt_hms(elapsed_total)}", flush=True)

    # attempts 저장
    try:
        out_attempts = OUT_ATTEMPTS or os.path.join(os.path.dirname(OUT_SUMMARY), "attempts.json")
        os.makedirs(os.path.dirname(out_attempts), exist_ok=True)
        with open(out_attempts, "w", encoding="utf-8") as f:
            json.dump(attempts, f, ensure_ascii=False, indent=2)
        print(f"[SAVE] attempts -> {out_attempts}")
    except Exception as e:
        print("[WARN] attempts 저장 실패:", e)

    return {
        "served": served, "rejected": rejected,
        "vehicles": vehicles, "events": events, "moves": moves,
        "tracks": tracks, "reroutes": reroutes, "attempts": attempts
    }