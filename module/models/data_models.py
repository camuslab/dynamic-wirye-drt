"""
파일명: scripts/data_models.py
요청/차량/스케줄 자료구조 정의 (+ 진행 중 경로 보간 상태, rebalance stop)
"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

@dataclass
class Request:
    req_id: str
    o_lon: float
    o_lat: float
    d_lon: float
    d_lat: float
    t_request: int  # 초단위 승차시각(절대 시각)

@dataclass
class Stop:
    # kind: "pickup" | "dropoff" | "rebalance"
    kind: str
    req_id: Optional[str]  # rebalance는 None 허용
    lon: float
    lat: float

@dataclass
class VehicleState:
    veh_id: str
    lon: float
    lat: float
    t_avail: float = 0.0
    schedule: List[Stop] = field(default_factory=list)
    onboard_reqs: List[str] = field(default_factory=list)

    # === 진행 중 경로(배치 간 보간용) ===
    active_coords: List[Tuple[float, float]] = field(default_factory=list)     # [(lon,lat), ...]
    active_timestamps: List[float] = field(default_factory=list)               # [0, t1, t2, ...] (초)
    active_elapsed: float = 0.0                                                # 현재 경로에서 경과시간(초)

    def clear_active_path(self):
        self.active_coords.clear()
        self.active_timestamps.clear()
        self.active_elapsed = 0.0

    def has_active_path(self) -> bool:
        return len(self.active_coords) >= 2 and len(self.active_timestamps) == len(self.active_coords)

@dataclass
class InsertionDecision:
    """
    삽입 결정 결과를 나타내는 데이터 클래스.
    matching.insertion 모듈에서 사용하며, 여기서 정의하여 공통 모델로 사용.
    """
    req_id: str
    veh_id: str
    new_schedule: List[Stop]
    cost_sec: float