// src/utils/dataLoader.js

export async function loadJSON(path) {
	const r = await fetch(path, { cache: 'no-store' });
	if (!r.ok) throw new Error(`HTTP ${r.status} for ${path}`);
	const ct = r.headers.get('content-type') || '';
	if (!ct.includes('application/json')) {
	  const txt = await r.text();
	  throw new Error(`Not JSON at ${path} (content-type=${ct}). First 120 chars: ${txt.slice(0,120)}`);
	}
	return r.json();
  }
  
  /** tracks.json (네 포맷: {veh_id, points:[{t,lon,lat,load}]}) → deck.gl 표준으로 정규화 */
  export function normalizeTracks(raw) {
	const out = [];
	if (!Array.isArray(raw)) return out;
	for (const tr of raw) {
	  const vid = tr.veh_id ?? tr.vehicle_id ?? tr.id ?? '';
	  const pts = Array.isArray(tr.points) ? tr.points : tr.path; // 혹시 path로도 올 수 있으니 보조
	  if (!Array.isArray(pts)) continue;
	  const path = [];
	  for (const p of pts) {
		const lon = +(p.lon ?? p.lng ?? p.x);
		const lat = +(p.lat ?? p.y);
		const t   = +(p.t ?? p.time ?? p.ts);
		if (Number.isFinite(lon) && Number.isFinite(lat) && Number.isFinite(t)) {
		  path.push([lon, lat, t]);
		}
	  }
	  if (path.length >= 2) out.push({ vehicle_id: vid, color: tr.color, path });
	}
	return out;
  }
  
  /** moves.json (네 포맷: 구간단위 {veh_id,t_start,t_end,lon1,lat1,lon2,lat2}) → tracks로 생성 */
  export function buildTracksFromMoves(moves) {
	if (!Array.isArray(moves)) return [];
	const byVeh = new Map();
	for (const m of moves) {
	  const vid = m.veh_id ?? m.vehicle_id ?? m.id;
	  if (!vid) continue;
	  const s = +m.t_start, e = +m.t_end;
	  const lon1 = +(m.lon1 ?? m.x1), lat1 = +(m.lat1 ?? m.y1);
	  const lon2 = +(m.lon2 ?? m.x2), lat2 = +(m.lat2 ?? m.y2);
	  if (!Number.isFinite(s) || !Number.isFinite(e) ||
		  !Number.isFinite(lon1) || !Number.isFinite(lat1) ||
		  !Number.isFinite(lon2) || !Number.isFinite(lat2)) continue;
	  if (!byVeh.has(vid)) byVeh.set(vid, []);
	  byVeh.get(vid).push([s, e, lon1, lat1, lon2, lat2]);
	}
  
	const out = [];
	for (const [vid, segs] of byVeh.entries()) {
	  segs.sort((a,b) => a[0] - b[0]); // t_start 기준
	  const path = [];
	  let lastT = -Infinity, lastLon = null, lastLat = null;
  
	  for (const [s, e, lon1, lat1, lon2, lat2] of segs) {
		// 시작점
		if (s !== lastT || lon1 !== lastLon || lat1 !== lastLat) {
		  path.push([lon1, lat1, s]);
		}
		// 끝점
		path.push([lon2, lat2, e]);
		lastT = e; lastLon = lon2; lastLat = lat2;
	  }
	  if (path.length >= 2) out.push({ vehicle_id: vid, path });
	}
	return out;
  }
  
  /** events.json (네 포맷: type=ASSIGN|PICKUP|DROPOFF …) → 화면용 pickup/dropoff만 추출 */
  export function normalizeEvents(raw) {
	if (!Array.isArray(raw)) return [];
	const out = [];
	for (const e of raw) {
	  const t = +e.t;
	  const lon = +(e.lon ?? e.lng ?? e.x);
	  const lat = +(e.lat ?? e.y);
	  const typ = String(e.type || '').toUpperCase();
	  if (!Number.isFinite(t)) continue;
	  if ((typ === 'PICKUP' || typ === 'DROPOFF') && Number.isFinite(lon) && Number.isFinite(lat)) {
		out.push({
		  event: typ === 'PICKUP' ? 'pickup' : 'dropoff',
		  t, lon, lat,
		  vehicle_id: e.veh_id ?? e.vehicle_id ?? e.vid ?? null,
		  pax_id: e.req_id ?? null
		});
	  }
	}
	return out;
  }
  
  /** (정규화된 tracks) 전체 시간 범위 */
  export function getTimeBoundsFromTracks(tracks) {
	let tMin = Infinity, tMax = -Infinity;
	for (const tr of tracks || []) {
	  const path = tr?.path;
	  if (!Array.isArray(path)) continue;
	  for (const p of path) {
		const t = +p[2];
		if (Number.isFinite(t)) {
		  if (t < tMin) tMin = t;
		  if (t > tMax) tMax = t;
		}
	  }
	}
	return Number.isFinite(tMin) && Number.isFinite(tMax) ? [tMin, tMax] : [0, 0];
  }
  
  export function formatHHMMSS(t) {
	const sec = Math.max(0, Math.floor(t % 86400));
	const h = String(Math.floor(sec/3600)).padStart(2,'0');
	const m = String(Math.floor((sec%3600)/60)).padStart(2,'0');
	const s = String(sec%60).padStart(2,'0');
	return `${h}:${m}:${s}`;
  }
  