// src/components/Trip.jsx
import React, { useEffect, useMemo, useState } from "react";
import DeckGL from "@deck.gl/react";
import { TripsLayer } from "@deck.gl/geo-layers";
import { IconLayer } from "@deck.gl/layers";
import { AmbientLight, LightingEffect } from "@deck.gl/core";
import Map from "react-map-gl";
import Legend from "./legend";

const MAPBOX_TOKEN =
  "pk.eyJ1IjoieW91cmNpbmR5IiwiYSI6ImNsdWpjOGQwNDA4ZnkyaXFwZWtiZnAybjEifQ.KdbpGwPgG_koJ-asO9VdpA";

const INITIAL_VIEW_STATE = {
  longitude: 127.135,
  latitude: 37.475,
  zoom: 13.3,
  pitch: 0,
  bearing: 0
};

// 색상
const HEX = {
  pool: "#FFFFFF",   // 대기(첫 시도만)
  assigned: "#2ECC71",   // 승인(배차 완료, 픽업 전)
  retry1: "#FF8A80",   // 재시도1
  retry2: "#E53935",   // 재시도2(마지막)
  done: "#555555",   // 완료(마커 숨김, 차트만)
  failed: "#9E9E9E"    // 만료/실패(짧게 페이드)
};

// ✅ base64 data URL (브라우저에서 SVG 디코드 에러 방지)
function svgPinDataUrl(color = "#FFFFFF") {
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">
      <g>
        <path d="M32 4c-11 0-20 9-20 20 0 16 20 36 20 36s20-20 20-36c0-11-9-20-20-20z" fill="${color}"/>
        <circle cx="32" cy="24" r="7" fill="#ffffff"/>
      </g>
    </svg>`;
  const b64 = typeof window !== "undefined"
    ? window.btoa(unescape(encodeURIComponent(svg)))
    : Buffer.from(svg, "utf-8").toString("base64");
  return `data:image/svg+xml;base64,${b64}`;
}

/* -----------------------
   공통 파서
------------------------*/
function getTimes(p) {
  const tReq = Number(p.t_req ?? p.request_time ?? NaN);
  const tAsg = Number(p.t_asg ?? NaN);
  let tPick = Number(p.t_pick ?? NaN);
  let tDrop = Number(p.t_drop ?? NaN);
  if (isNaN(tPick) && Array.isArray(p.timestamp)) tPick = Number(p.timestamp[0]);
  if (isNaN(tDrop) && Array.isArray(p.timestamp) && p.timestamp.length > 1) tDrop = Number(p.timestamp[1]);
  return { tReq, tAsg, tPick, tDrop };
}
function parseHist(p) {
  const hist = Array.isArray(p.assign_history) ? p.assign_history : [];
  return hist.map(h => ({
    ts: Number(h.t ?? h.ts ?? h.time ?? h.timestamp ?? h.start_ts ?? NaN),
    end: Number(h.end_ts ?? NaN),
    attempt: Number(h.attempt ?? NaN),
    result: String(h.result || "").toLowerCase()
  })).filter(x => !isNaN(x.ts)).sort((a, b) => a.ts - b.ts);
}
const isAcceptWord = s =>
  ["accept", "accepted", "assign", "assigned", "approve", "approved"].includes(String(s).toLowerCase());

/* -----------------------
   거리/시간 유틸
------------------------*/
function haversineMeters([lon1, lat1], [lon2, lat2]) {
  const R = 6371000;
  const toRad = d => (d * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  return R * c;
}

/* -----------------------
   상태 분류(마커)
------------------------*/
function classifyPaxStory(p, nowSec) {
  const { tReq, tAsg, tPick, tDrop } = getTimes(p);
  if (isNaN(tReq) || nowSec < tReq) return { show: false };

  const maxWait = Number(p.max_wait_sec ?? 600);
  const tExpire = !isNaN(tReq) ? tReq + maxWait : NaN;
  const hist = parseHist(p);
  const histUpToNow = hist.filter(h => h.ts <= nowSec);
  const maxAttempts = Number(p.max_attempt ?? 3);

  const everAccepted =
    !isNaN(tAsg) || !isNaN(tPick) || !isNaN(tDrop) ||
    histUpToNow.some(h => isAcceptWord(h.result));

  // max_attempt로 재시도 횟수 판단
  const attemptsDone = maxAttempts;
  const last = histUpToNow[histUpToNow.length - 1];
  const lastFail = !!last && ["timeout", "reject", "rejected", "cancel", "fail", "failed"].includes(last.result);

  // 최종 실패 → 잠깐 페이드 후 제거
  if (!everAccepted && attemptsDone >= maxAttempts && (lastFail || maxAttempts === 0)) {
    const tFail = !isNaN(last?.end) ? last.end : (!isNaN(last?.ts) ? last.ts : (isNaN(tExpire) ? nowSec : tExpire));
    const FAIL_FADE = 2.0;
    const alpha = Math.max(0, 1 - (nowSec - tFail) / FAIL_FADE);
    if (alpha <= 0) return { show: false };
    return { show: true, state: "failed", pos: p.pickup_location, alpha };
  }
  // 일반 만료
  if (!everAccepted && !isNaN(tExpire) && nowSec >= tExpire) {
    const FAIL_FADE = 2.0;
    const alpha = Math.max(0, 1 - (nowSec - tExpire) / FAIL_FADE);
    if (alpha <= 0) return { show: false };
    return { show: true, state: "failed", pos: p.pickup_location, alpha };
  }

  // 완료/탑승 → 지도에서는 숨김 (요청사항)
  if (!isNaN(tDrop) && nowSec >= tDrop) return { show: false };
  if (!isNaN(tPick) && nowSec >= tPick && (isNaN(tDrop) || nowSec < tDrop)) return { show: false };

  // 재시도 색
  if (attemptsDone >= 3) return { show: true, state: "retry2", pos: p.pickup_location, alpha: 1 };
  if (attemptsDone === 2) return { show: true, state: "retry1", pos: p.pickup_location, alpha: 1 };

  // 승인(배차) or 풀(첫 시도)
  const hasAnyAssignNow =
    (!isNaN(tAsg) && tAsg <= nowSec) ||
    histUpToNow.some(h => isAcceptWord(h.result));
  if (hasAnyAssignNow) return { show: true, state: "assigned", pos: p.pickup_location, alpha: 1 };

  return { show: true, state: "pool", pos: p.pickup_location, alpha: 1 };
}

export default function Trip({ currentTime, fleetLabel }) {
  const [localCount, setLocalCount] = useState(10);
  const countToUse = fleetLabel ?? localCount;

  const [trips, setTrips] = useState([]);
  const [paxData, setPaxData] = useState([]);

  useEffect(() => {
    let gone = false;
    Promise.all([
      fetch(`/data/trip/trip_${countToUse}.json`).then(r => r.json()).catch(() => []),
      fetch(`/data/pax_icon/pax_icon_${countToUse}.json`).then(r => r.json()).catch(() => [])
    ]).then(([tripJs, paxJs]) => {
      if (gone) return;
      setTrips(Array.isArray(tripJs) ? tripJs : []);
      setPaxData(Array.isArray(paxJs) ? paxJs : []);
    });
    return () => { gone = true; };
  }, [countToUse]);

  // 현재 탑승중 차량 set (경로 강조용)
  const occupiedSet = useMemo(() => {
    const set = new Set();
    for (const p of paxData) {
      const { tPick, tDrop } = getTimes(p);
      if (!isNaN(tPick) && !isNaN(tDrop) && currentTime >= tPick && currentTime < tDrop && p.vehicle_id) {
        set.add(p.vehicle_id);
      }
    }
    return set;
  }, [paxData, currentTime]);

  // 마커
  const markers = useMemo(() => {
    const out = [];
    const isPos = (pt) =>
      Array.isArray(pt) && pt.length === 2 &&
      Number.isFinite(pt[0]) && Number.isFinite(pt[1]);
    for (const p of paxData) {
      const st = classifyPaxStory(p, currentTime);
      if (!st.show || !isPos(st.pos)) continue;
      out.push({
        id: p.pax_ID || p.request_id,
        position: st.pos,
        state: st.state,
        alpha: Number.isFinite(st.alpha) ? st.alpha : 1
      });
    }
    return out;
  }, [paxData, currentTime]);

  // 메트릭 (pool/assigned/onboard/done)
  const metrics = useMemo(() => {
    if (!paxData.length) return null;

    let pool = 0, assigned = 0, onboard = 0, done = 0;
    const vehLoads = {};

    for (const p of paxData) {
      const { tPick, tDrop } = getTimes(p);
      const st = classifyPaxStory(p, currentTime);
      if (st.show) {
        if (st.state === "pool") pool++;
        else if (st.state === "assigned" || st.state === "retry1" || st.state === "retry2") assigned++;
      }
      if (!isNaN(tPick) && (isNaN(tDrop) || tDrop > currentTime) && tPick <= currentTime) {
        onboard++;
        if (p.vehicle_id) vehLoads[p.vehicle_id] = (vehLoads[p.vehicle_id] || 0) + 1;
      }
      if (!isNaN(tDrop) && tDrop <= currentTime) done++;
    }

    const vehicleIds = [...new Set(trips.map(t => t.vehicle_id))];
    const vehiclesMini = vehicleIds.map(id => ({ id, load: vehLoads[id] || 0 }));
    const activeLoads = Object.values(vehLoads);
    const avgOccupancy = activeLoads.length
      ? activeLoads.reduce((s, v) => s + v, 0) / activeLoads.length
      : 0;

    // 서비스율
    let releasedNow = 0, acceptedNow = 0, finishedNow = 0;
    let releasedTotal = 0, acceptedTotal = 0;
    for (const p of paxData) {
      const { tReq, tAsg, tPick, tDrop } = getTimes(p);
      if (isNaN(tReq)) continue;
      const hist = parseHist(p);
      const acceptedEver =
        !isNaN(tAsg) || !isNaN(tPick) || !isNaN(tDrop) ||
        hist.some(h => isAcceptWord(h.result));
      releasedTotal++;
      if (acceptedEver) acceptedTotal++;
      if (tReq <= currentTime) {
        releasedNow++;
        const acceptedSoFar =
          (!isNaN(tAsg) && tAsg <= currentTime) ||
          (!isNaN(tPick) && tPick <= currentTime) ||
          (!isNaN(tDrop) && tDrop <= currentTime) ||
          hist.some(h => isAcceptWord(h.result) && h.ts <= currentTime);
        if (acceptedSoFar) acceptedNow++;
        if (!isNaN(tDrop) && tDrop <= currentTime) finishedNow++;
      }
    }
    const serviceRateNow = releasedNow ? Math.round((acceptedNow / releasedNow) * 100) : 0;
    const serviceRateTotal = releasedTotal ? Math.round((acceptedTotal / releasedTotal) * 100) : 0;

    // 평균 대기시간
    const waits = [];
    for (const p of paxData) {
      const { tReq, tPick } = getTimes(p);
      if (!isNaN(tReq) && !isNaN(tPick) && tPick <= currentTime) {
        waits.push(Math.max(0, tPick - tReq));
      }
    }
    const avgWaitSec = waits.length ? Math.round(waits.reduce((s, v) => s + v, 0) / waits.length) : 0;

    // 차량 평균 주행거리
    const distPerVeh = {};
    for (const t of trips) {
      const coords = t.trip || [];
      const ts = t.timestamp || [];
      if (!coords.length || !ts.length) continue;
      let sum = 0;
      for (let i = 1; i < coords.length; i++) {
        const t1 = Number(ts[i - 1]), t2 = Number(ts[i]);
        if (isNaN(t1) || isNaN(t2)) continue;
        if (t2 <= currentTime) {
          sum += haversineMeters(coords[i - 1], coords[i]);
        } else if (t1 < currentTime && currentTime < t2) {
          const ratio = (currentTime - t1) / (t2 - t1);
          sum += haversineMeters(coords[i - 1], coords[i]) * Math.max(0, Math.min(1, ratio));
          break;
        } else if (t1 >= currentTime) break;
      }
      distPerVeh[t.vehicle_id] = (distPerVeh[t.vehicle_id] || 0) + sum;
    }
    const vehDists = Object.values(distPerVeh);
    const avgDistKm = vehDists.length ? (vehDists.reduce((s, v) => s + v, 0) / vehDists.length) / 1000 : 0;

    const active = vehiclesMini.filter(v => v.load > 0);
    const fleetUtil = (active.length
      ? active.reduce((s, v) => s + v.load / 5, 0) / active.length * 100
      : 0).toFixed(0);

    return {
      serviceRateNow,
      serviceRateTotal,
      avgWaitSec,
      avgOccupancy: Number(avgOccupancy.toFixed(2)),
      avgDistKm: Number(avgDistKm.toFixed(1)),
      fleetUtil,
      stateBreakdown: { pool, assign: assigned, onboard, done },
      vehiclesMini,
      doneCumulative: done
    };
  }, [paxData, trips, currentTime]);

  const layers = [
    new TripsLayer({
      id: "vehicle-trips",
      data: trips,
      getPath: d => d.trip,
      getTimestamps: d => d.timestamp,
      getColor: d => (occupiedSet.has(d.vehicle_id) ? [33, 150, 243, 220] : [170, 170, 170, 130]),
      widthMinPixels: 3,
      trailLength: 30,
      currentTime
    }),
    new IconLayer({
      id: "story-markers",
      data: markers,
      pickable: false,
      getIcon: d => {
        const color =
          d.state === "retry2" ? HEX.retry2 :
            d.state === "retry1" ? HEX.retry1 :
              d.state === "assigned" ? HEX.assigned :
                d.state === "failed" ? HEX.failed :
                  HEX.pool;
        return { url: svgPinDataUrl(color), width: 64, height: 64, anchorY: 64 };
      },
      getPosition: d => d.position,
      sizeUnits: "pixels",
      getSize: d => {
        const base = 26;
        if (d.state === "failed") {
          const a = Math.max(0, Math.min(1, d.alpha ?? 1));
          return Math.max(10, base * a);
        }
        return base;
      },
      parameters: { depthTest: true }
    })
  ];

  return (
    <>
      {fleetLabel == null && (
        <div style={{ position: "absolute", top: 16, left: 16, zIndex: 1000, display: "flex", gap: 8 }}>
          {[10, 20, 30, 50].map(n => (
            <button key={n}
              onClick={() => setLocalCount(n)}
              style={{
                padding: "8px 14px",
                background: n === localCount ? "#00bcd4" : "#333",
                color: "#fff", border: "none", borderRadius: 10, fontWeight: 700, cursor: "pointer"
              }}>
              {n}대
            </button>
          ))}
        </div>
      )}

      <DeckGL
        initialViewState={INITIAL_VIEW_STATE}
        controller={true}
        effects={[
          new LightingEffect({
            ambientLight: new AmbientLight({ intensity: 1.0 })
          })
        ]}
        layers={layers}
      >
        <Map mapStyle="mapbox://styles/mapbox/dark-v11" mapboxAccessToken={MAPBOX_TOKEN} />
      </DeckGL>

      {metrics && <Legend metrics={metrics} />}
    </>
  );
}
