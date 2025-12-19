// src/utils/timefmt.js
export function formatHHMMSS(totalSec = 0) {
	const sec = Math.max(0, Math.floor(Number(totalSec) || 0));
	const h = Math.floor(sec / 3600);
	const m = Math.floor((sec % 3600) / 60);
	const s = sec % 60;
	return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  }