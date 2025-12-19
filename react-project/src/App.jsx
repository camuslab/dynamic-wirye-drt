// C:\dynamic_wirye_drt\react-project\src\App.jsx
import React, { useState, useEffect } from "react";
import Trip from "./components/trip";
import Slider from "@mui/material/Slider";
import IconButton from "@mui/material/IconButton";
import PlayArrowIcon from "@mui/icons-material/PlayArrow"; // ▶
import PauseIcon from "@mui/icons-material/Pause";         // Ⅱ
import "./css/app.css";

export default function App() {
  const minTime = 6 * 3600 + 59 * 60; // 06:59:00
  const maxTime = 9 * 3600 + 10 * 60; // 09:10:00
  const [time, setTime] = useState(minTime);
  const [isPlaying, setIsPlaying] = useState(true);

  // 자동 재생 (0.2초마다 5초 진행)
  useEffect(() => {
    if (!isPlaying) return;
    const timer = setInterval(() => {
      setTime((prev) => (prev < maxTime ? prev + 5 : minTime));
    }, 100);
    return () => clearInterval(timer);
  }, [isPlaying, maxTime, minTime]);

  return (
    <div className="container">
      {/* 상단 시간 표시 */}
      <h1
        style={{
          position: "absolute",
          top: 18,
          left: "50%",
          transform: "translateX(-50%)",
          color: "white",
          fontSize: 28,
          fontWeight: "bold",
          zIndex: 1000,
          margin: 0
        }}
      >
        TIME : {String(Math.floor(time / 3600)).padStart(2, "0")} :{" "}
        {String(Math.floor((time % 3600) / 60)).padStart(2, "0")}
      </h1>

      {/* 메인 지도/시뮬 */}
      <Trip currentTime={time} />

      {/* 하단 컨트롤 바: (재생/일시정지 아이콘) + (시간 슬라이더) */}
      <div
        style={{
          position: "absolute",
          bottom: 24,
          left: "50%",
          transform: "translateX(-50%)",
          width: "60%",
          display: "flex",
          alignItems: "center",
          gap: 12,
          zIndex: 1000
        }}
      >
        <IconButton
          aria-label={isPlaying ? "pause" : "play"}
          onClick={() => setIsPlaying((v) => !v)}
          size="large"
          sx={{
            bgcolor: "rgba(255,255,255,0.15)",
            ":hover": { bgcolor: "rgba(255,255,255,0.25)" },
            borderRadius: "12px"
          }}
        >
          {isPlaying ? <PauseIcon fontSize="inherit" /> : <PlayArrowIcon fontSize="inherit" />}
        </IconButton>

        <Slider
          min={minTime}
          max={maxTime}
          value={time}
          step={10}
          onChange={(_, v) => setTime(Number(v))}
          sx={{ flexGrow: 1, color: "#2196f3" }}
        />
      </div>
    </div>
  );
}
