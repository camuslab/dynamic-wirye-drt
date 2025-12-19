"""
파일명: utils.py
거리/시간 보조 함수
"""

import math
from typing import List, Tuple, Optional
from ..routing.osrm_client import OSRM

def euclidean_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    # 위례 스케일에서는 유클리드 근사 ok (단위: m)
    dx = (lon2 - lon1) * 90000.0
    dy = (lat2 - lat1) * 111000.0
    return math.hypot(dx, dy)

def segment_times(coords: List[Tuple[float, float]],
                  use_osrm: bool,
                  osrm_obj: Optional[OSRM],
                  avg_speed_kmh: float) -> List[float]:
    """
    coords: [(lon,lat), ...]
    return: 각 leg의 소요시간(초) 리스트
    """
    if len(coords) < 2:
        return []
    if use_osrm and osrm_obj is not None:
        try:
            return osrm_obj.route_leg_durations(coords)
        except Exception:
            pass
    # fallback: 직선거리 / 평균속도
    out = []
    v_mps = max(1e-3, avg_speed_kmh * 1000 / 3600)
    for i in range(len(coords) - 1):
        lon1, lat1 = coords[i]
        lon2, lat2 = coords[i + 1]
        dist = euclidean_m(lon1, lat1, lon2, lat2)
        out.append(dist / v_mps)
    return out



def interp_on_polyline(line: List[Tuple[float, float]], frac: float) -> Tuple[float, float]:
    """
    polyline(line) 위에서 전체 길이의 frac(0~1) 지점 좌표를 반환.
    선분들을 유클리드(m)로 길이 누적하여 타겟 지점을 찾아 선분 내 선형보간.
    """
    if not line:
        return (0.0, 0.0)
    if len(line) == 1:
        return line[0]

    # 총 길이(m)
    seg_len = []
    total = 0.0
    for i in range(len(line) - 1):
        l1, l2 = line[i], line[i+1]
        d = euclidean_m(l1[0], l1[1], l2[0], l2[1])
        seg_len.append(d)
        total += d

    if total <= 0:
        # 전부 같은 점이라면 시작점 반환
        return line[0]

    target = total * max(0.0, min(1.0, frac))

    # target 이 속한 선분 찾기
    run = 0.0
    for i in range(len(seg_len)):
        if run + seg_len[i] >= target:
            # 이 선분 안에서 위치
            l1, l2 = line[i], line[i+1]
            remain = target - run
            if seg_len[i] <= 0:
                return l2
            r = remain / seg_len[i]
            lon = l1[0] + (l2[0] - l1[0]) * r
            lat = l1[1] + (l2[1] - l1[1]) * r
            return (lon, lat)
        run += seg_len[i]

    # 혹시 누적오차로 못찾으면 마지막 점
    return line[-1]

# --- 직선거리(하버사인) 기반 소요시간 근사 ---
def straight_line_seconds(lon1: float, lat1: float, lon2: float, lat2: float, avg_speed_kmh: float) -> float:
    """
    haversine(미터) / (평균속도 m/s) 로 시간(초) 근사.
    OSRM을 쓰지 않거나 실패했을 때 OD 최단시간의 fallback으로 사용.
    """
    import math
    R = 6371000.0  # meters
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    d_m = 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))  # meters
    v_mps = max(0.1, float(avg_speed_kmh) / 3.6)              # m/s (0으로 나눔 방지)
    return d_m / v_mps