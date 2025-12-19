"""
파일명: assign_cohorts.py
설명:
- 차량 집합 V, 가상요청 집합 VR에 대해 비용행렬을 만들고 LAP(헝가리안)으로 1:1 매칭
- 매칭 후, 삽입 유틸로 실제 스케줄 반영(부분할당 포함)
"""

from typing import List, Tuple
import numpy as np
from scipy.optimize import linear_sum_assignment

from .data_models import VehicleState, VirtualRequest
from .config import INSERT_SEARCH_FULL, INSERT_TAIL_WINDOW, BIG_M
from .insertion import (
    estimate_cost_for_virtual_request,
    apply_virtual_assignment,
)


def lap_assign_cohorts_to_vehicles(
    vehicles: List[VehicleState],
    vreqs: List[VirtualRequest],
    search_full: bool = INSERT_SEARCH_FULL,
    tail_lambda: int = INSERT_TAIL_WINDOW,
) -> List[Tuple[int, int, int]]:
    """
    반환: [(veh_idx, vreq_idx, take_count), ...]
    """
    if not vehicles or not vreqs:
        return []

    nV = len(vehicles)
    nR = len(vreqs)
    C = np.full((nV, nR), BIG_M, dtype=float)
    TAKE = np.zeros((nV, nR), dtype=int)

    for vi, v in enumerate(vehicles):
        for ri, vr in enumerate(vreqs):
            cost, taken = estimate_cost_for_virtual_request(
                v, vr, search_full=search_full, tail_lambda=tail_lambda
            )
            C[vi, ri] = cost
            TAKE[vi, ri] = taken

    row_ind, col_ind = linear_sum_assignment(C)

    matches: List[Tuple[int, int, int]] = []
    for vi, ri in zip(row_ind, col_ind):
        if C[vi, ri] >= BIG_M * 0.1:  # 큰 비용(사실상 불가) 컷
            continue
        if TAKE[vi, ri] <= 0:
            continue
        matches.append((vi, ri, int(TAKE[vi, ri])))

    return matches


def commit_cohort_assignments(
    vehicles: List[VehicleState],
    vreqs: List[VirtualRequest],
    matches: List[Tuple[int, int, int]],
    search_full: bool = INSERT_SEARCH_FULL,
    tail_lambda: int = INSERT_TAIL_WINDOW,
) -> int:
    """
    LAP 결과를 실제 스케줄에 반영.
    반환: 총 삽입된 pax 수
    """
    total_applied = 0
    for (vi, ri, take_cnt) in matches:
        v = vehicles[vi]
        vr = vreqs[ri]
        applied = apply_virtual_assignment(
            v, vr, take_cnt,
            search_full=search_full, tail_lambda=tail_lambda
        )
        total_applied += applied
    return total_applied
