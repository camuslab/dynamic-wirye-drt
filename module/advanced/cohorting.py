"""
파일명: cohorting.py
설명:
- 배치 직전 대기 큐에서, 시간/공간 임계값으로 유사 OD 그룹(코호트) 생성
- 결과: Cohort 리스트와 VirtualRequest 리스트 반환
"""

from typing import List, Tuple
from ..models.data_models import Request, Cohort, VirtualRequest
from ..config.config import (
    COHORT_TIME_TOL_SEC,
    COHORT_PICK_TOL_M,
    COHORT_DROP_TOL_M,
)
from ..utils.utils import haversine_m


def build_cohorts(
    pending: List[Request],
    t_center: int,
    t_tol_sec: int = COHORT_TIME_TOL_SEC,
    pick_tol_m: float = COHORT_PICK_TOL_M,
    drop_tol_m: float = COHORT_DROP_TOL_M,
) -> Tuple[List[Cohort], List[VirtualRequest]]:
    """
    pending: 이번 배치주기에 처리 대상인 '대기 큐' 요청들
    t_center: 배치 기준시각(예: tk)
    반환: (cohorts, virtual_requests)
    """
    if not pending:
        return [], []

    used = set()
    cohorts: List[Cohort] = []

    for r in pending:
        if r.req_id in used:
            continue
        group = [r]
        for s in pending:
            if s.req_id in used or s.req_id == r.req_id:
                continue
            # 시간 근접
            if abs(s.t_request - r.t_request) > t_tol_sec:
                continue
            # 공간 근접(픽업/드롭)
            if haversine_m(r.o_lon, r.o_lat, s.o_lon, s.o_lat) > pick_tol_m:
                continue
            if haversine_m(r.d_lon, r.d_lat, s.d_lon, s.d_lat) > drop_tol_m:
                continue
            group.append(s)

        for g in group:
            used.add(g.req_id)

        # 대표 좌표/시간(평균)
        o_lon = sum(g.o_lon for g in group) / len(group)
        o_lat = sum(g.o_lat for g in group) / len(group)
        d_lon = sum(g.d_lon for g in group) / len(group)
        d_lat = sum(g.d_lat for g in group) / len(group)
        t_center_grp = int(sum(g.t_request for g in group) / len(group))

        cohort = Cohort(
            cohort_id=f"C{len(cohorts)+1}",
            member_req_ids=[g.req_id for g in group],
            o_lon=o_lon, o_lat=o_lat, d_lon=d_lon, d_lat=d_lat,
            t_request_center=t_center_grp, size=len(group)
        )
        cohorts.append(cohort)

    vreqs = [
        VirtualRequest(
            cohort_id=c.cohort_id,
            group_size=c.size,
            o_lon=c.o_lon, o_lat=c.o_lat, d_lon=c.d_lon, d_lat=c.d_lat,
            t_request_center=c.t_request_center,
        )
        for c in cohorts
    ]
    return cohorts, vreqs
