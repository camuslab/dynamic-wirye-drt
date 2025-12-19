import React from "react";

function Pie({ size = 140, values = [], colors = [], stroke = 0 }) {
  const total = Math.max(1, values.reduce((s, v) => s + (v || 0), 0));
  const R = (size - stroke) / 2;
  const CX = size / 2, CY = size / 2;
  let acc = 0;
  const toXY = (theta) => [CX + R * Math.cos(theta), CY + R * Math.sin(theta)];
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
      <circle cx={CX} cy={CY} r={R} fill="rgba(255,255,255,0.06)" stroke="rgba(255,255,255,0.12)"/>
      {values.map((v, i) => {
        const start = (acc / total) * 2 * Math.PI - Math.PI / 2;
        acc += v || 0;
        const end = (acc / total) * 2 * Math.PI - Math.PI / 2;
        const [x1, y1] = toXY(start);
        const [x2, y2] = toXY(end);
        const largeArc = end - start > Math.PI ? 1 : 0;
        const d = `M ${CX} ${CY} L ${x1} ${y1} A ${R} ${R} 0 ${largeArc} 1 ${x2} ${y2} Z`;
        return <path key={i} d={d} fill={colors[i]} stroke={stroke ? "#000" : "none"} strokeWidth={stroke}/>;
      })}
    </svg>
  );
}

export default function Legend({ metrics }) {
  if (!metrics) return null;

  const {
    serviceRateNow = 0,
    serviceRateTotal = 0,
    fleetUtil = 0,
    stateBreakdown = {},
    vehiclesMini = [],
    avgWaitSec = 0,
    avgOccupancy = 0,
    avgDistKm = 0,
    doneCumulative = 0
  } = metrics;

  const pool    = stateBreakdown.pool   ?? 0;
  const assign  = stateBreakdown.assign ?? 0;
  const onboard = stateBreakdown.onboard?? 0;
  const done    = stateBreakdown.done   ?? 0;

  const fmtMinSec = (s) => {
    const m = Math.floor((s || 0) / 60);
    const r = Math.floor((s || 0) % 60);
    return `${m}m ${r}s`;
  };

  const card = {
    position: "absolute",
    right: 16,
    top: 72,
    width: 360,
    background: "rgba(0,0,0,0.72)",
    color: "#fff",
    padding: "18px 20px",
    borderRadius: 18,
    zIndex: 1000,
    fontFamily: "Inter, system-ui, sans-serif",
    fontSize: 15,
    lineHeight: 1.45,
    boxShadow: "0 14px 28px rgba(0,0,0,0.35)"
  };
  const section = { marginTop: 16, paddingTop: 14, borderTop: "1px solid rgba(255,255,255,0.12)" };
  const h3 = { margin: "0 0 10px 0", fontSize: 18, fontWeight: 700 };
  const h4 = { margin: "0 0 10px 0", fontSize: 16, fontWeight: 700 };

  return (
    <div style={card}>
      <h3 style={h3}>● Simulation</h3>

      <div style={{ marginBottom: 8 }}>
        <strong>Service Rate</strong>: {serviceRateNow}% [{serviceRateTotal}%]
      </div>
      <div style={{ marginBottom: 8 }}>
        <strong>Fleet Utilization</strong>: {fleetUtil}%
      </div>

      <div style={section}>
        <div>Waiting time (avg): <strong>{fmtMinSec(avgWaitSec)}</strong></div>
        <div>Occupancy (avg): <strong>{avgOccupancy}</strong> pass/veh</div>
        <div>Travel distance: <strong>{avgDistKm}</strong> km/veh</div>
      </div>

      <div style={section}>
        <h4 style={h4}>● Request States</h4>
        <div style={{ display:"grid", gridTemplateColumns:"150px 1fr", alignItems:"center", columnGap:14 }}>
          <Pie
            size={150}
            values={[pool, assign, onboard, doneCumulative]}
            colors={["#FFFFFF", "#2ECC71", "#57D2FF", "#555555"]}
          />
          <div style={{ display:"grid", gridTemplateColumns:"1fr auto", rowGap:6, fontSize:15 }}>
            <div style={{ display:"flex", alignItems:"center", gap:10 }}>
              <span style={{ width:12, height:12, background:"#FFFFFF", display:"inline-block", borderRadius:2, border:"1px solid #999" }}/>
              Pool
            </div><div>{pool}</div>

            <div style={{ display:"flex", alignItems:"center", gap:10 }}>
              <span style={{ width:12, height:12, background:"#2ECC71", display:"inline-block", borderRadius:2 }}/>
              Assigned
            </div><div>{assign}</div>

            <div style={{ display:"flex", alignItems:"center", gap:10 }}>
              <span style={{ width:12, height:12, background:"#57D2FF", display:"inline-block", borderRadius:2 }}/>
              Onboard
            </div><div>{onboard}</div>

            <div style={{ display:"flex", alignItems:"center", gap:10 }}>
              <span style={{ width:12, height:12, background:"#555555", display:"inline-block", borderRadius:2 }}/>
              Done (cum)
            </div><div>{doneCumulative}</div>
          </div>
        </div>
      </div>

      <div style={section}>
        <h4 style={h4}>● Vehicle Status</h4>
        <div style={{ maxHeight: 220, overflow: "auto" }}>
          {(vehiclesMini || []).map(v => (
            <div key={v.id} style={{ display:"flex", justifyContent:"space-between", fontSize:14, padding:"2px 0" }}>
              <span>{v.id}</span><span>{v.load}/5</span>
            </div>
          ))}
        </div>
      </div>

      <div style={{ marginTop: 12, fontSize: 12, opacity: 0.7 }}>
        Marker colors: Pool(white) / Assigned(green) / Retry(light & dark red). Onboard & Done are hidden as markers but counted in the chart.
      </div>
    </div>
  );
}
