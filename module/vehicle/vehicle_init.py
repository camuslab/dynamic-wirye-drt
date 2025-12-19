# scripts/vehicle_init.py
"""
위례신도시 지역 내 랜덤 차량 배치
"""
import random
from typing import List
from ..models.data_models import VehicleState

# 위례신도시 대략적 경계 좌표 (실제 경계에 맞게 조정 필요)
WIRYE_BOUNDS = {
    'lon_min': 127.130,  # 서쪽 경계
    'lon_max': 127.160,  # 동쪽 경계  
    'lat_min': 37.470,   # 남쪽 경계
    'lat_max': 37.490    # 북쪽 경계
}

def init_vehicles_random_distributed(fleet_size: int, seed: int = 42) -> List[VehicleState]:
    """
    위례신도시 지역 내에 차량을 무작위로 분산 배치
    """
    random.seed(seed)
    vehicles = []
    
    for i in range(fleet_size):
        # 경계 내에서 랜덤 좌표 생성
        lon = random.uniform(WIRYE_BOUNDS['lon_min'], WIRYE_BOUNDS['lon_max'])
        lat = random.uniform(WIRYE_BOUNDS['lat_min'], WIRYE_BOUNDS['lat_max'])
        
        vehicles.append(VehicleState(
            veh_id=f"v{i:03d}",
            lon=lon,
            lat=lat,
            t_avail=0.0
        ))
    
    print(f"[INIT] {fleet_size}대 차량을 위례 지역에 랜덤 배치 완료")
    return vehicles

# 더 정교한 방법: 실제 요청 데이터 기반 배치
def init_vehicles_from_request_distribution(requests: List, fleet_size: int, seed: int = 42) -> List[VehicleState]:
    """
    요청 데이터의 출발지 분포를 기반으로 차량 배치
    """
    random.seed(seed)
    
    # 요청 출발지들 수집
    origin_coords = [(r.o_lon, r.o_lat) for r in requests]
    
    vehicles = []
    for i in range(fleet_size):
        if origin_coords:
            # 실제 요청 출발지 중 하나를 선택하고 약간의 노이즈 추가
            base_lon, base_lat = random.choice(origin_coords)
            lon = base_lon + random.uniform(-0.005, 0.005)  # ±500m 정도
            lat = base_lat + random.uniform(-0.005, 0.005)
        else:
            # fallback
            lon = random.uniform(WIRYE_BOUNDS['lon_min'], WIRYE_BOUNDS['lon_max'])
            lat = random.uniform(WIRYE_BOUNDS['lat_min'], WIRYE_BOUNDS['lat_max'])
        
        vehicles.append(VehicleState(
            veh_id=f"v{i:03d}",
            lon=lon,
            lat=lat,
            t_avail=0.0
        ))
    
    return vehicles