"""
파일명: scripts/osrm_client.py
OSRM HTTP 클라이언트
- route/table
- route_full(): geometry + annotation(duration) + 누적시간
- progress_point_by_time(): 'elapsed_s' 시점 보간 좌표
- oneway_duration_sec(): OD 최단시간(우회율 분모)
"""

from __future__ import annotations
import math
import bisect
from typing import List, Tuple, Dict, Any, Optional
import requests

def _fmt_coords(coords: List[Tuple[float, float]]) -> str:
    return ";".join([f"{lon:.6f},{lat:.6f}" for lon, lat in coords])

def _haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))

class OSRM:
    def __init__(self, base_url: str = "http://127.0.0.1:5000", profile: str = "driving", cache: bool = True):
        self.base_url = base_url.rstrip("/")
        self.profile = profile
        self._cache_route: Optional[Dict[str, Dict[str, Any]]] = {} if cache else None
        self._cache_table: Optional[Dict[str, List[List[float]]]] = {} if cache else None

    # ---------- Core enriched API ----------
    def route_full(self, start: Tuple[float, float], end: Tuple[float, float]) -> Dict[str, Any]:
        """
        start→end 경로:
          - coords: [[lon,lat], ...] (GeoJSON geometry)
          - seg_durs: [s1, s2, ...]   (각 세그 소요)
          - cum_durs: [0, s1, s1+s2, ...]
          - total_dur: 총 소요(초)
        """
        key = f"{start[0]:.6f},{start[1]:.6f}|{end[0]:.6f},{end[1]:.6f}"
        if self._cache_route is not None and key in self._cache_route:
            return self._cache_route[key]

        url = f"{self.base_url}/route/v1/{self.profile}/{_fmt_coords([start, end])}"
        params = {"overview": "full", "steps": "true", "annotations": "duration", "geometries": "geojson"}
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
        js = r.json()
        routes = js.get("routes", [])
        if not routes:
            data = {"coords": [list(start), list(end)], "seg_durs": [0.0], "cum_durs": [0.0, 0.0], "total_dur": 0.0}
            if self._cache_route is not None: self._cache_route[key] = data
            return data

        route = routes[0]
        total_dur = float(route.get("duration", 0.0))
        geom = route.get("geometry", {}) or {}
        coords: List[List[float]] = geom.get("coordinates", []) or [list(start), list(end)]

        seg_durs: List[float] = []
        for leg in route.get("legs", []):
            ann = leg.get("annotation", {})
            durs = ann.get("duration") or []
            seg_durs.extend([float(x) for x in durs])

        if not seg_durs:
            nseg = max(1, len(coords) - 1)
            seg_durs = [ (total_dur / nseg) if total_dur > 0 else 0.0 ] * nseg

        cum: List[float] = [0.0]
        acc = 0.0
        for d in seg_durs:
            acc += d
            cum.append(acc)

        data = {
            "coords": coords,
            "seg_durs": seg_durs,
            "cum_durs": cum,
            "total_dur": total_dur if total_dur > 0 else (cum[-1] if cum else 0.0),
        }
        if self._cache_route is not None: self._cache_route[key] = data
        return data

    def progress_point_by_time(self, start: Tuple[float, float], end: Tuple[float, float], elapsed_s: float) -> Tuple[float, float]:
        """route_full()의 누적시간(cum_durs) 기반 선형 보간"""
        info = self.route_full(start, end)
        coords: List[List[float]] = info["coords"]
        cum: List[float] = info["cum_durs"]
        if not coords or len(coords) < 2:
            return end
        total = cum[-1] if cum else 0.0
        want = min(max(0.0, elapsed_s), total)
        import bisect as _bis
        i = _bis.bisect_right(cum, want) - 1
        i = max(0, min(i, len(coords) - 2))
        t0, t1 = cum[i], cum[i + 1]
        ratio = 0.0 if (t1 - t0) <= 0 else (want - t0) / (t1 - t0)
        x1, y1 = coords[i]
        x2, y2 = coords[i + 1]
        return (x1 + (x2 - x1) * ratio, y1 + (y2 - y1) * ratio)

    def oneway_duration_sec(self, o_lon: float, o_lat: float, d_lon: float, d_lat: float) -> float:
        """OD 최단시간(초) — 우회율 분모에 사용"""
        info = self.route_full((o_lon, o_lat), (d_lon, d_lat))
        return float(info.get("total_dur", 0.0))

    # ---------- Optional: table ----------
    def table_durations(self, coords: List[Tuple[float, float]]) -> List[List[float]]:
        if not coords:
            return []
        key = _fmt_coords(coords)
        if self._cache_table is not None and key in self._cache_table:
            return self._cache_table[key]
        url = f"{self.base_url}/table/v1/{self.profile}/{key}"
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        js = r.json()
        durations = js.get("durations", []) or []
        mat = [[0.0 if x is None else float(x) for x in row] for row in durations]
        if self._cache_table is not None:
            self._cache_table[key] = mat
        return mat