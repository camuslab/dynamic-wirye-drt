// src/config/dataPaths.js
export function getScenarioPaths(label) {
	// public/data 밑의 파일명 규칙을 그대로 씀
	return {
	  tripUrl: `/data/trip/trip_${label}.json`,
	  paxUrl: `/data/pax_icon/pax_icon_${label}.json`,
	  solUrl: `/data/solution_routes_${label}_osrm.json`,
	};
  }