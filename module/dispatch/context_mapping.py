# scripts/context_mapping.py
from __future__ import annotations
from typing import List, Tuple
import math, random

from ..config.config import ServiceParams
from ..models.data_models import Request, VehicleState


def _dist_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """위경도 간 근사 거리(m). 빠른 후보 정렬용."""
    dx = (lon1 - lon2) * 111320 * math.cos(math.radians((lat1 + lat2) / 2.0))
    dy = (lat1 - lat2) * 110540
    return math.hypot(dx, dy)


def _split_idle_busy(vehicles: List[VehicleState]) -> Tuple[List[VehicleState], List[VehicleState]]:
    idle = [v for v in vehicles if len(v.schedule) == 0]
    busy = [v for v in vehicles if len(v.schedule) > 0]
    return idle, busy


def select_candidate_vehicles(
    req: Request,
    vehicles: List[VehicleState],
    P: ServiceParams,
    retry_k: int = 0,
    max_retries: int = 0
) -> List[VehicleState]:
    """
    후보군 선정:
    - 현재 50대 규모 시뮬레이션에서는 성능 최적화(샘플링)보다 
      전체 차량을 검토하여 성공률을 높이는 것이 유리함.
    - 유휴 차량을 우선적으로 검토하도록 정렬하여 반환.
    """
    idle, busy = _split_idle_busy(vehicles)
    return idle + busy