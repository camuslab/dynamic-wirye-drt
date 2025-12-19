# 파일명: scripts/loaders.py
# 설명:
# - 요청 Parquet 읽기
# - 컬럼 자동 매핑(폭넓은 후보 지원)
# - t_request(초) 타입/단위 보정(밀리초→초 자동 판별)
# - 시간창 필터(SIM_START/END), 샘플링(LIMIT_N, LIMIT_RANDOM, LIMIT_SEED)
# - t_request 오름차순 정렬 보장
# - 필요 시 명시적 컬럼명 인자 지원

from __future__ import annotations
from typing import List, Optional
import numpy as np
import pandas as pd

from ..config.config import (
    ServiceParams,
    SIM_START_SEC, SIM_END_SEC,
    LIMIT_N, LIMIT_RANDOM, LIMIT_SEED,
)
from ..models.data_models import Request


# ---- 내부 유틸 ----
def _pick_first(df: pd.DataFrame, candidates: list[str]) -> Optional[str]:
    for c in candidates:
        if c in df.columns:
            return c
    return None

def _ensure_seconds(x: pd.Series) -> pd.Series:
    """
    시각열을 float(초)로 변환. ms/μs처럼 큰 값이면 자동으로 나눠서 초로 맞춤.
    """
    s = pd.to_numeric(x, errors="coerce").astype(float)
    med = np.nanmedian(s)
    if np.isnan(med):
        return s
    # 아주 큰 값은 ms 또는 μs로 간주
    if med > 1e12:       # μs 근처
        s = s / 1_000_000.0
    elif med > 1e10:     # ms 근처
        s = s / 1000.0
    # 1e7~1e10: epoch seconds 가능 → 그대로
    # 1e3~1e6: 하루 내 상대초(예: 25200~32400) → 그대로
    return s

def _filter_time_window(df: pd.DataFrame, col: str) -> pd.DataFrame:
    start = SIM_START_SEC
    end   = SIM_END_SEC
    if start is not None:
        df = df[df[col] >= float(start)]
    if end is not None:
        df = df[df[col] <  float(end)]
    return df

def _apply_sampling(df: pd.DataFrame) -> pd.DataFrame:
    if LIMIT_N is None:
        return df
    n = int(LIMIT_N)
    if n <= 0:
        return df.iloc[0:0]
    if LIMIT_RANDOM:
        import math
        seed = 42 if LIMIT_SEED is None else int(LIMIT_SEED)
        return df.sample(n=min(n, len(df)), random_state=seed)\
                 .sort_values("t_request").reset_index(drop=True)
    else:
        return df.sort_values("t_request").head(n).reset_index(drop=True)


# ---- 메인 로더 ----
def load_requests_parquet(
    path: str,
    P: ServiceParams,
    *,
    id_col: Optional[str] = None,
    t_col: Optional[str] = None,
    o_lon_col: Optional[str] = None,
    o_lat_col: Optional[str] = None,
    d_lon_col: Optional[str] = None,
    d_lat_col: Optional[str] = None,
) -> List[Request]:
    """
    Parquet에서 요청을 읽어 프로젝트 표준 Request 리스트로 변환.
    - 명시적 컬럼명 인자를 주면 그것을 우선 사용.
    - 없으면 자동 매핑 시도.

    필수 결과 컬럼: req_id, t_request(초), o_lon/o_lat, d_lon/d_lat
    """
    df = pd.read_parquet(path)

    # --- 자동 매핑 후보 사전 ---
    id_cands = ["KEY1", "req_id", "id", "request_id", "ride_id", "trip_id"]

    t_cands  = [
        "t_request", "t_pick", "승차_timestamp", "승차시각", "pickup_ts", "request_ts",
        "timestamp", "ts", "call_time", "req_time", "requested_at",
    ]

    # 출발 좌표
    o_lon_cands = [
        "o_lon", "pickup_lon", "승차경도", "출발_lon", "start_lon", "lon_o",
        "origin_lon", "orig_lon", "O_LON", "o_lng", "pulon", "PULongitude",
    ]
    o_lat_cands = [
        "o_lat", "pickup_lat", "승차위도", "출발_lat", "start_lat", "lat_o",
        "origin_lat", "orig_lat", "O_LAT", "o_latitude", "pulat", "PULatitude",
    ]
    # 도착 좌표
    d_lon_cands = [
        "d_lon", "dropoff_lon", "하차경도", "도착_lon", "end_lon", "lon_d",
        "dest_lon", "dst_lon", "D_LON", "d_lng", "dolon", "DOLongitude",
    ]
    d_lat_cands = [
        "d_lat", "dropoff_lat", "하차위도", "도착_lat", "end_lat", "lat_d",
        "dest_lat", "dst_lat", "D_LAT", "d_latitude", "dolat", "DOLatitude",
    ]

    # --- 컬럼명 결정(명시적 인자 우선) ---
    if id_col is None:     id_col = _pick_first(df, id_cands)
    if t_col is None:      t_col  = _pick_first(df, t_cands)
    if o_lon_col is None:  o_lon_col = _pick_first(df, o_lon_cands)
    if o_lat_col is None:  o_lat_col = _pick_first(df, o_lat_cands)
    if d_lon_col is None:  d_lon_col = _pick_first(df, d_lon_cands)
    if d_lat_col is None:  d_lat_col = _pick_first(df, d_lat_cands)

    # id 없으면 인덱스로 대체
    if id_col is None:
        df = df.copy()
        df["__RID__"] = df.index.astype(str)
        id_col = "__RID__"

    missing_t = (t_col is None)
    missing_o = (o_lon_col is None or o_lat_col is None)
    missing_d = (d_lon_col is None or d_lat_col is None)

    if missing_t or missing_o or missing_d:
        cols_preview = ", ".join(map(str, df.columns.tolist()))
        msg = []
        if missing_t: msg.append(f"[시각] 후보 미발견: {t_cands}")
        if missing_o: msg.append(f"[출발좌표] 후보 미발견: lon={o_lon_cands}, lat={o_lat_cands}")
        if missing_d: msg.append(f"[도착좌표] 후보 미발견: lon={d_lon_cands}, lat={d_lat_cands}")
        raise ValueError(
            "원/목적 좌표(또는 시각) 컬럼을 찾지 못했습니다.\n"
            + "\n".join(msg)
            + f"\n\n원본 컬럼 목록:\n{cols_preview}\n\n"
            + "해결법:\n"
            + " - load_requests_parquet(…, o_lon_col='원본명', o_lat_col='원본명', d_lon_col='원본명', d_lat_col='원본명', t_col='원본명') 처럼 명시적으로 넘겨주세요."
        )

    # --- 필요한 컬럼만 취해 표준명으로 리네임 ---
    df = df[[id_col, t_col, o_lon_col, o_lat_col, d_lon_col, d_lat_col]].copy()
    df.rename(columns={
        id_col: "req_id",
        t_col: "t_request",
        o_lon_col: "o_lon", o_lat_col: "o_lat",
        d_lon_col: "d_lon", d_lat_col: "d_lat",
    }, inplace=True)

    # --- 타입/단위 보정 ---
    df["t_request"] = _ensure_seconds(df["t_request"])
    df["o_lon"] = pd.to_numeric(df["o_lon"], errors="coerce").astype(float)
    df["o_lat"] = pd.to_numeric(df["o_lat"], errors="coerce").astype(float)
    df["d_lon"] = pd.to_numeric(df["d_lon"], errors="coerce").astype(float)
    df["d_lat"] = pd.to_numeric(df["d_lat"], errors="coerce").astype(float)

    # 결측 제거
    df = df.dropna(subset=["t_request", "o_lon", "o_lat", "d_lon", "d_lat"]).reset_index(drop=True)

    # --- 시간창 필터 ---
    df = _filter_time_window(df, "t_request")

    # --- 정렬 보장 ---
    df = df.sort_values("t_request").reset_index(drop=True)

    # --- 샘플링 적용 ---
    df = _apply_sampling(df)

    # --- 디버그 로그(원인추적) ---
    if not df.empty:
        head_vals = df["t_request"].head(10).tolist()
        deltas = [round(head_vals[i+1] - head_vals[i], 1) for i in range(min(len(head_vals)-1, 9))]
        print(f"count: {len(df)}")
        print(f"min/max: {float(df['t_request'].min())} {float(df['t_request'].max())}")
        print(f"head 10: {head_vals}")
        print(f"sorted? first 10 deltas: {deltas}")

    # --- Request 객체 변환 ---
    reqs: List[Request] = []
    for row in df.itertuples(index=False):
        reqs.append(Request(
            req_id=str(getattr(row, "req_id")),
            t_request=float(getattr(row, "t_request")),
            o_lon=float(getattr(row, "o_lon")),
            o_lat=float(getattr(row, "o_lat")),
            d_lon=float(getattr(row, "d_lon")),
            d_lat=float(getattr(row, "d_lat")),
        ))
    return reqs