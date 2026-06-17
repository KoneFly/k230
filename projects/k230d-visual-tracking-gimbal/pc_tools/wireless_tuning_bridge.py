#!/usr/bin/env python3
"""PC bridge for K230D wireless tuning.

Protocol:
- Board -> PC: UDP 9001, lines like
  STAT id=k230d-tracker ex=-12 ey=6 fps=28 found=1 gx=20
- Browser -> Bridge: WebSocket JSON
  {"type":"set","params":{"gx":20,"gy":7}}
- Bridge -> Board: UDP 9002, lines like
  SET gx=20 gy=7

The implementation intentionally uses Python standard library only to keep the
demo portable across Windows machines.
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import http.server
import json
import os
import socket
import socketserver
import struct
import threading
import time
from dataclasses import dataclass, field
from typing import Any


CSV_FIELDS = [
    "host_ms", "id", "ip", "t", "ex", "ey", "tx", "ty", "ax", "ay",
    "vx", "vy", "dirx", "diry", "tvx", "tvy", "fps", "found", "run",
    "gx", "gy", "kdx", "kdy", "dead", "minx", "miny", "maxx", "maxy",
]


HTML_PAGE = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no" />
  <title>K230D 无线调参台</title>
  <style>
    :root {
      --bg: #10130f;
      --panel: rgba(244, 238, 218, 0.08);
      --panel-strong: rgba(244, 238, 218, 0.14);
      --text: #f4eeda;
      --muted: #9ba58d;
      --accent: #e7b84b;
      --danger: #ff674d;
      --ok: #73d37b;
      --line: rgba(244, 238, 218, 0.16);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      color: var(--text);
      background:
        radial-gradient(circle at 18% 12%, rgba(231,184,75,.22), transparent 28rem),
        radial-gradient(circle at 84% 18%, rgba(115,211,123,.14), transparent 26rem),
        linear-gradient(135deg, #0d100d, #181b14 52%, #0b0f0e);
      font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
    }
    .app { max-width: 1480px; margin: 0 auto; padding: 22px; }
    header { display: flex; justify-content: space-between; gap: 16px; align-items: flex-end; margin-bottom: 22px; }
    h1 { margin: 0; font-size: clamp(30px, 3.2vw, 46px); letter-spacing: -0.04em; }
    .sub { color: var(--muted); margin-top: 8px; }
    .badge {
      padding: 10px 14px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: var(--panel);
      transition: transform 160ms cubic-bezier(.4,0,.2,1), background 160ms;
    }
    .badge.ok { color: var(--ok); }
    .badge.off { color: var(--danger); }
    .grid { display: grid; grid-template-columns: minmax(0, 1.75fr) 420px; gap: 18px; align-items: start; }
    .panel {
      border: 1px solid var(--line);
      border-radius: 24px;
      background: var(--panel);
      box-shadow: 0 24px 60px rgba(0,0,0,.28);
      backdrop-filter: blur(18px);
      padding: 20px;
      animation: enter 380ms cubic-bezier(.2,.8,.2,1) both;
    }
    @keyframes enter { from { opacity: 0; transform: translateY(14px); } to { opacity: 1; transform: translateY(0); } }
    .metrics { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }
    .metric { padding: 13px 14px; border-radius: 18px; background: var(--panel-strong); border: 1px solid var(--line); min-width: 0; }
    .metric span { display: block; color: var(--muted); font-size: 14px; line-height: 1.25; }
    .metric strong { display: block; margin-top: 8px; font-size: clamp(26px, 2.1vw, 36px); line-height: 1; white-space: nowrap; }
    #found { font-size: clamp(24px, 1.8vw, 32px); }
    .chart-wrap { margin-top: 14px; padding: 12px; border: 1px solid var(--line); border-radius: 22px; background: rgba(0,0,0,.24); }
    .chart-head { display: flex; justify-content: space-between; gap: 14px; align-items: center; margin: 0 4px 12px; color: var(--muted); font-size: 16px; }
    .legend { display: flex; gap: 14px; flex-wrap: wrap; }
    .legend i { display: inline-block; width: 24px; height: 3px; margin-right: 6px; vertical-align: middle; border-radius: 999px; }
    .legend .x i { background: #e7b84b; }
    .legend .y i { background: #73d37b; }
    canvas { width: 100%; height: min(56vh, 560px); min-height: 420px; display: block; border-radius: 16px; background: rgba(0,0,0,.20); touch-action: manipulation; }
    .controls { display: grid; gap: 14px; }
    .group { padding: 14px; border: 1px solid var(--line); border-radius: 18px; background: rgba(0,0,0,.16); }
    .group-title { margin: 0 0 12px; color: var(--text); font-size: 16px; font-weight: 800; }
    .hint { display: block; margin-top: 4px; color: var(--muted); font-size: 12px; line-height: 1.35; }
    .row { display: grid; grid-template-columns: 118px 1fr 58px; gap: 12px; align-items: center; }
    label { color: var(--muted); }
    input[type="range"] { width: 100%; accent-color: var(--accent); }
    .value { text-align: right; font-variant-numeric: tabular-nums; }
    .actions { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-top: 16px; }
    .actions.wide { grid-template-columns: repeat(2, 1fr); }
    button {
      border: 0;
      border-radius: 16px;
      padding: 14px 16px;
      color: #14120d;
      background: var(--accent);
      font-weight: 700;
      cursor: pointer;
      touch-action: manipulation;
      -webkit-tap-highlight-color: transparent;
      transition: transform 120ms cubic-bezier(.4,0,.2,1), filter 120ms;
    }
    button:hover { transform: translateY(-2px); filter: brightness(1.08); }
    button:active { transform: scale(.97, 1.03); }
    button.secondary { background: #d9dcc9; }
    button.danger { background: var(--danger); color: #fff; }
    pre {
      height: 220px;
      overflow: auto;
      color: #d7dec7;
      background: rgba(0,0,0,.28);
      border-radius: 16px;
      padding: 14px;
      margin: 14px 0 0;
      font-size: 16px;
      line-height: 1.7;
    }
    @media (max-width: 860px) {
      .grid, header { grid-template-columns: 1fr; display: grid; }
      .metrics { grid-template-columns: repeat(2, 1fr); }
      .row { grid-template-columns: 110px 1fr 52px; }
      .app { padding: 16px; }
      canvas { min-height: 340px; height: 48vh; }
    }
  </style>
</head>
<body>
  <div class="app">
    <header>
      <div>
        <h1>无线调参台</h1>
        <div class="sub">UDP 遥测 · WebSocket 控制 · 兼容 K230D / ESP32 / STM32</div>
      </div>
      <div id="status" class="badge off">未连接</div>
    </header>
    <main class="grid">
      <section class="panel">
        <div class="metrics">
          <div class="metric"><span>帧率 FPS</span><strong id="fps">--</strong></div>
          <div class="metric"><span>水平误差 Error X</span><strong id="ex">--</strong></div>
          <div class="metric"><span>垂直误差 Error Y</span><strong id="ey">--</strong></div>
          <div class="metric"><span>目标状态 Target</span><strong id="found">--</strong></div>
          <div class="metric"><span>10 秒评分 Score</span><strong id="score">--</strong></div>
          <div class="metric"><span>Y轴过冲 Overshoot</span><strong id="osy">--</strong></div>
          <div class="metric"><span>Y轴抖动 Jitter</span><strong id="jy">--</strong></div>
          <div class="metric"><span>丢失次数 Lost</span><strong id="lost">--</strong></div>
        </div>
        <div class="chart-wrap">
          <div class="chart-head">
            <div>误差时间线 · 范围 ±240px · 最近 180 个采样</div>
            <div class="legend">
              <span class="x"><i></i>水平误差 X</span>
              <span class="y"><i></i>垂直误差 Y</span>
            </div>
          </div>
          <canvas id="plot" width="1200" height="520"></canvas>
        </div>
        <pre id="log"></pre>
      </section>
      <section class="panel">
        <div class="controls" id="controls"></div>
        <div class="actions">
          <button type="button" onclick="sendCmd('START')">开始 Start</button>
          <button type="button" class="danger" onclick="sendCmd('STOP')">停止 Stop</button>
          <button type="button" class="secondary" onclick="sendSet()">应用 Apply</button>
        </div>
        <div class="actions wide">
          <button type="button" class="secondary" onclick="toggleTestWindow()">开始记录 Test</button>
          <button type="button" class="secondary" onclick="downloadData()">导出CSV</button>
          <button type="button" class="secondary" onclick="downloadChartImage()">导出图像</button>
          <button type="button" class="secondary" onclick="downloadReportJson()">导出报告</button>
          <button type="button" class="secondary" onclick="clearData()">清空数据 Clear</button>
          <button type="button" class="secondary" onclick="sendCmd('STATUS')">查询状态 Status</button>
          <button type="button" class="secondary" onclick="saveParamsLocal()">保存参数 Local</button>
        </div>
      </section>
    </main>
  </div>
  <script>
    const fields = [
      { group: "响应速度 Response", hint: "追不上目标时增大 Gain 或 Min；过冲时先不要继续增大。", items: [
        ["gx", "X 增益 / Gain X", 4, 45, 20],
        ["gy", "Y 增益 / Gain Y", 2, 30, 7],
        ["minx", "X 最小速度 / Min X", 10, 160, 55],
        ["miny", "Y 最小速度 / Min Y", 10, 140, 40],
      ]},
      { group: "阻尼稳定 Damping", hint: "过冲、来回摆动时增大 KD；响应变僵硬时减小。", items: [
        ["kdx", "X 微分 / KD X", 0, 10, 2],
        ["kdy", "Y 微分 / KD Y", 0, 10, 1],
      ]},
      { group: "命中死区 Dead Zone", hint: "中心附近抖动时增大；小目标精度不足时减小。", items: [
        ["dead", "死区 / Dead Zone", 3, 30, 8],
      ]},
      { group: "速度上限 Limit", hint: "冲出目标或机械跟不上时降低 Max；追踪慢但不过冲时提高。", items: [
        ["maxx", "X 最大速度 / Max X", 60, 300, 260],
        ["maxy", "Y 最大速度 / Max Y", 60, 260, 210],
      ]},
    ];
    const controls = document.getElementById("controls");
    const values = {};
    for (const section of fields) {
      const group = document.createElement("section");
      group.className = "group";
      group.innerHTML = `<h3 class="group-title">${section.group}<span class="hint">${section.hint}</span></h3>`;
      controls.appendChild(group);
      for (const [key, name, min, max, val] of section.items) {
        values[key] = val;
        const row = document.createElement("div");
        row.className = "row";
        row.innerHTML = `<label>${name}</label><input id="${key}" type="range" min="${min}" max="${max}" value="${val}"><div class="value" id="${key}v">${val}</div>`;
        group.appendChild(row);
        row.querySelector("input").addEventListener("input", e => {
          values[key] = Number(e.target.value);
          document.getElementById(key + "v").textContent = e.target.value;
        });
      }
    }
    restoreParamsLocal();

    const statusEl = document.getElementById("status");
    const logEl = document.getElementById("log");
    const points = [];
    const telemetryRows = [];
    let recordingTest = false;
    let testStartTime = "";
    let lastScore = null;
    let ws;
    const csvColumns = [
      "host_time", "id", "ip", "t", "ex", "ey", "tx", "ty", "ax", "ay",
      "vx", "vy", "dirx", "diry", "tvx", "tvy", "fps", "found", "run",
      "gx", "gy", "kdx", "kdy", "dead", "minx", "miny", "maxx", "maxy",
      "score", "avg_ex", "avg_ey", "max_ex", "max_ey", "lost",
      "overshoot_x", "overshoot_y", "jitter_x", "jitter_y", "test"
    ];

    function connect() {
      ws = new WebSocket(`ws://${location.host}/ws`);
      ws.onopen = () => setStatus(true, "已连接");
      ws.onclose = () => { setStatus(false, "未连接"); setTimeout(connect, 1000); };
      ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        if (msg.type === "stat") updateStat(msg.data, msg.score);
        if (msg.type === "log") appendLog(msg.message);
        if (msg.type === "snapshot") appendLog(`${msg.name}: ${JSON.stringify(msg.data)}`);
      };
    }
    function setStatus(ok, text) {
      statusEl.className = ok ? "badge ok" : "badge off";
      statusEl.textContent = text;
    }
    function appendLog(text) {
      const time = new Date().toLocaleTimeString();
      logEl.textContent = `[${time}] ${text}\n` + logEl.textContent.slice(0, 5000);
    }
    function updateStat(d, score) {
      document.getElementById("fps").textContent = d.fps ?? "--";
      document.getElementById("ex").textContent = d.ex ?? "--";
      document.getElementById("ey").textContent = d.ey ?? "--";
      document.getElementById("found").textContent = Number(d.found) ? "有目标" : "无目标";
      if (score && score.score !== undefined) {
        lastScore = score;
        document.getElementById("score").textContent = score.score;
        document.getElementById("osy").textContent = score.overshoot_y;
        document.getElementById("jy").textContent = score.jitter_y;
        document.getElementById("lost").textContent = score.lost;
      }
      for (const [from, to] of [["gx","gx"],["gy","gy"],["kdx","kdx"],["kdy","kdy"],["dead","dead"],["minx","minx"],["miny","miny"],["maxx","maxx"],["maxy","maxy"]]) {
        if (d[from] !== undefined && document.activeElement?.id !== to) {
          values[to] = Number(d[from]);
          document.getElementById(to).value = values[to];
          document.getElementById(to + "v").textContent = values[to];
        }
      }
      recordTelemetry(d, score);
      points.push({ ex: Number(d.ex || 0), ey: Number(d.ey || 0) });
      if (points.length > 180) points.shift();
      drawPlot();
    }
    function sendSet() {
      ws?.send(JSON.stringify({ type: "set", params: values }));
      appendLog("SET " + Object.entries(values).map(([k,v]) => `${k}=${v}`).join(" "));
    }
    function sendCmd(cmd) {
      ws?.send(JSON.stringify({ type: "cmd", cmd }));
      appendLog(cmd);
    }
    function recordTelemetry(d, score) {
      const row = { host_time: new Date().toISOString(), ...d };
      row.test = recordingTest ? 1 : 0;
      if (score) {
        row.score = score.score;
        row.avg_ex = score.avg_ex;
        row.avg_ey = score.avg_ey;
        row.max_ex = score.max_ex;
        row.max_ey = score.max_ey;
        row.lost = score.lost;
        row.overshoot_x = score.overshoot_x;
        row.overshoot_y = score.overshoot_y;
        row.jitter_x = score.jitter_x;
        row.jitter_y = score.jitter_y;
      }
      telemetryRows.push(row);
      if (telemetryRows.length > 30000) telemetryRows.shift();
    }
    function toggleTestWindow() {
      recordingTest = !recordingTest;
      testStartTime = recordingTest ? new Date().toISOString() : testStartTime;
      appendLog(recordingTest ? `开始记录测试段：${testStartTime}` : "测试段记录结束");
    }
    function saveParamsLocal() {
      localStorage.setItem("k230d_tuner_params", JSON.stringify(values));
      appendLog("参数已保存到浏览器本地 LocalStorage");
    }
    function restoreParamsLocal() {
      const saved = JSON.parse(localStorage.getItem("k230d_tuner_params") || "null");
      if (!saved) return;
      for (const [key, value] of Object.entries(saved)) {
        const slider = document.getElementById(key);
        const label = document.getElementById(key + "v");
        if (!slider || !label) continue;
        values[key] = Number(value);
        slider.value = values[key];
        label.textContent = values[key];
      }
    }
    function clearData() {
      telemetryRows.length = 0;
      points.length = 0;
      drawPlot();
      appendLog("本地遥测数据已清空");
    }
    function makeCsvFilename() {
      const stamp = new Date().toISOString().replace(/[:.]/g, "-");
      return `k230d_tracking_${stamp}.csv`;
    }
    function makeBaseFilename(ext) {
      const stamp = new Date().toISOString().replace(/[:.]/g, "-");
      return `k230d_tracking_${stamp}.${ext}`;
    }
    function getCsvTextOrWarn() {
      if (!telemetryRows.length) {
        appendLog("没有可保存的数据");
        return null;
      }
      return buildCsv(telemetryRows);
    }
    function downloadData() {
      const csvText = getCsvTextOrWarn();
      if (!csvText) return;
      const filename = makeCsvFilename();
      downloadBlob(filename, new Blob([csvText], { type: "text/csv;charset=utf-8" }));
      appendLog(`数据已下载到浏览器默认下载目录：${filename}`);
    }
    async function saveDataAs() {
      const csvText = getCsvTextOrWarn();
      if (!csvText) return;
      const filename = makeCsvFilename();
      if (window.showSaveFilePicker) {
        try {
          const handle = await window.showSaveFilePicker({
            suggestedName: filename,
            types: [{ description: "CSV 数据文件", accept: { "text/csv": [".csv"] } }]
          });
          const writable = await handle.createWritable();
          await writable.write(new Blob([csvText], { type: "text/csv;charset=utf-8" }));
          await writable.close();
          appendLog(`数据已保存：${filename}`);
          return;
        } catch (err) {
          if (err && err.name === "AbortError") {
            appendLog("已取消保存");
            return;
          }
          appendLog(`另存为失败，改用浏览器下载：${err}`);
        }
      }
      downloadData();
    }
    function downloadChartImage() {
      const canvas = document.getElementById("plot");
      const filename = makeBaseFilename("png");
      canvas.toBlob(blob => {
        if (!blob) {
          appendLog("图像导出失败");
          return;
        }
        downloadBlob(filename, blob);
        appendLog(`曲线图已下载：${filename}`);
      }, "image/png");
    }
    function downloadReportJson() {
      if (!telemetryRows.length) {
        appendLog("没有可保存的报告数据");
        return;
      }
      const report = {
        exported_at: new Date().toISOString(),
        device: "k230d-tracker",
        params: { ...values },
        score: lastScore,
        test_start_time: testStartTime,
        sample_count: telemetryRows.length,
        latest_sample: telemetryRows[telemetryRows.length - 1],
        recent_samples: telemetryRows.slice(-300),
      };
      const filename = makeBaseFilename("json");
      downloadBlob(filename, new Blob([JSON.stringify(report, null, 2)], { type: "application/json;charset=utf-8" }));
      appendLog(`报告已下载：${filename}`);
    }
    function downloadBlob(filename, blob) {
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    }
    function buildCsv(rows) {
      const lines = [csvColumns.join(",")];
      for (const row of rows) {
        lines.push(csvColumns.map(key => csvEscape(row[key])).join(","));
      }
      return "\ufeff" + lines.join("\n");
    }
    function csvEscape(value) {
      if (value === undefined || value === null) return "";
      const text = String(value);
      if (/[",\n\r]/.test(text)) return `"${text.replace(/"/g, '""')}"`;
      return text;
    }
    function drawPlot() {
      const c = document.getElementById("plot");
      const ctx = c.getContext("2d");
      const w = c.width;
      const h = c.height;
      const padL = 58;
      const padR = 18;
      const padT = 22;
      const padB = 42;
      const plotW = w - padL - padR;
      const plotH = h - padT - padB;
      const maxErr = 240;
      ctx.clearRect(0, 0, c.width, c.height);
      ctx.font = "13px Segoe UI, Microsoft YaHei, sans-serif";
      ctx.fillStyle = "rgba(244,238,218,.72)";
      ctx.strokeStyle = "rgba(244,238,218,.13)";
      ctx.lineWidth = 1;
      for (const tick of [-240, -120, 0, 120, 240]) {
        const y = padT + (maxErr - tick) / (maxErr * 2) * plotH;
        ctx.beginPath();
        ctx.moveTo(padL, y);
        ctx.lineTo(w - padR, y);
        ctx.stroke();
        ctx.fillText(`${tick}px`, 10, y + 4);
      }
      for (let i = 0; i <= 6; i++) {
        const x = padL + i / 6 * plotW;
        ctx.beginPath();
        ctx.moveTo(x, padT);
        ctx.lineTo(x, h - padB);
        ctx.stroke();
      }
      ctx.strokeStyle = "rgba(244,238,218,.42)";
      ctx.beginPath();
      ctx.rect(padL, padT, plotW, plotH);
      ctx.stroke();
      ctx.fillStyle = "rgba(244,238,218,.62)";
      ctx.fillText("时间 →", w - 86, h - 14);
      ctx.save();
      ctx.translate(18, 122);
      ctx.rotate(-Math.PI / 2);
      ctx.fillText("追踪误差(px)", 0, 0);
      ctx.restore();
      drawLine("ex", "#e7b84b");
      drawLine("ey", "#73d37b");
      drawLatest();
      function drawLine(key, color) {
        ctx.strokeStyle = color;
        ctx.lineWidth = 2;
        ctx.beginPath();
        points.forEach((p, i) => {
          const x = padL + i * plotW / Math.max(1, points.length - 1);
          const clipped = Math.max(-maxErr, Math.min(maxErr, p[key]));
          const y = padT + (maxErr - clipped) / (maxErr * 2) * plotH;
          if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        });
        ctx.stroke();
      }
      function drawLatest() {
        if (!points.length) return;
        const p = points[points.length - 1];
        const x = padL + plotW;
        for (const [key, color, label] of [["ex", "#e7b84b", "EX"], ["ey", "#73d37b", "EY"]]) {
          const clipped = Math.max(-maxErr, Math.min(maxErr, p[key]));
          const y = padT + (maxErr - clipped) / (maxErr * 2) * plotH;
          ctx.fillStyle = color;
          ctx.beginPath();
          ctx.arc(x, y, 5, 0, Math.PI * 2);
          ctx.fill();
          ctx.fillText(`${label}:${p[key]}`, x - 86, y - 8);
        }
      }
    }
    connect();
  </script>
</body>
</html>
"""


@dataclass
class BridgeState:
    board_addr: tuple[str, int] | None = None
    latest: dict[str, Any] = field(default_factory=dict)
    clients: list[socket.socket] = field(default_factory=list)
    samples: list[dict[str, Any]] = field(default_factory=list)
    best_score: dict[str, Any] | None = None
    csv_writer: csv.DictWriter | None = None
    csv_file: Any = None
    log_dir: str = ""
    csv_path: str = ""
    marks_path: str = ""
    lock: threading.Lock = field(default_factory=threading.Lock)


def parse_kv_line(line: str) -> tuple[str, dict[str, Any]]:
    parts = line.strip().split()
    if not parts:
        return "", {}
    kind = parts[0].upper()
    data: dict[str, Any] = {}
    for part in parts[1:]:
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        try:
            if "." in value:
                data[key] = float(value)
            else:
                data[key] = int(value)
        except ValueError:
            data[key] = value
    return kind, data


def to_float(value: Any, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def compute_score(samples: list[dict[str, Any]]) -> dict[str, Any]:
    if not samples:
        return {}

    valid = [s for s in samples if int(to_float(s.get("found"))) == 1 and int(to_float(s.get("run"))) == 1]
    if not valid:
        return {
            "score": 0,
            "avg_ex": 0,
            "avg_ey": 0,
            "max_ex": 0,
            "max_ey": 0,
            "lost": sum(1 for s in samples if int(to_float(s.get("found"))) == 0),
            "overshoot_x": 0,
            "overshoot_y": 0,
            "jitter_x": 0,
            "jitter_y": 0,
            "avg_fps": 0,
            "count": 0,
        }

    errors = [(abs(to_float(s.get("ex"))), abs(to_float(s.get("ey")))) for s in valid]
    avg_ex = sum(e[0] for e in errors) / len(errors)
    avg_ey = sum(e[1] for e in errors) / len(errors)
    max_ex = max(e[0] for e in errors)
    max_ey = max(e[1] for e in errors)
    lost = sum(1 for s in samples if int(to_float(s.get("found"))) == 0)
    fps_values = [to_float(s.get("fps")) for s in valid if to_float(s.get("fps")) > 0]
    avg_fps = sum(fps_values) / len(fps_values) if fps_values else 0.0

    overshoot_x = count_zero_cross_overshoot(valid, "ex")
    overshoot_y = count_zero_cross_overshoot(valid, "ey")
    jitter_x = avg_delta(valid, "ex")
    jitter_y = avg_delta(valid, "ey")

    score = (
        avg_ex * 0.8 + avg_ey * 1.1 +
        max_ex * 0.08 + max_ey * 0.12 +
        lost * 8.0 +
        overshoot_x * 4.0 + overshoot_y * 7.0 +
        jitter_x * 0.25 + jitter_y * 0.35
    )
    return {
        "score": round(score, 2),
        "avg_ex": round(avg_ex, 1),
        "avg_ey": round(avg_ey, 1),
        "max_ex": round(max_ex, 1),
        "max_ey": round(max_ey, 1),
        "lost": lost,
        "overshoot_x": overshoot_x,
        "overshoot_y": overshoot_y,
        "jitter_x": round(jitter_x, 1),
        "jitter_y": round(jitter_y, 1),
        "avg_fps": round(avg_fps, 1),
        "count": len(valid),
    }


def count_zero_cross_overshoot(samples: list[dict[str, Any]], key: str) -> int:
    count = 0
    last = 0.0
    armed = False
    for sample in samples:
        value = to_float(sample.get(key))
        if abs(value) > 8:
            armed = True
        if armed and last != 0 and value != 0 and (last > 0) != (value > 0):
            count += 1
            armed = False
        last = value
    return count


def avg_delta(samples: list[dict[str, Any]], key: str) -> float:
    if len(samples) < 2:
        return 0.0
    total = 0.0
    last = to_float(samples[0].get(key))
    for sample in samples[1:]:
        value = to_float(sample.get(key))
        total += abs(value - last)
        last = value
    return total / (len(samples) - 1)


def params_from_sample(sample: dict[str, Any]) -> dict[str, Any]:
    keys = ("gx", "gy", "kdx", "kdy", "dead", "minx", "miny", "maxx", "maxy")
    return {key: sample[key] for key in keys if key in sample}


def encode_ws_payload(payload: dict[str, Any]) -> bytes:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    if len(body) < 126:
        return bytes([0x81, len(body)]) + body
    if len(body) < 65536:
        return bytes([0x81, 126]) + struct.pack("!H", len(body)) + body
    return bytes([0x81, 127]) + struct.pack("!Q", len(body)) + body


def recv_ws_text(conn: socket.socket) -> str | None:
    header = conn.recv(2)
    if len(header) < 2:
        return None
    opcode = header[0] & 0x0F
    if opcode == 0x8:
        return None
    length = header[1] & 0x7F
    if length == 126:
        length = struct.unpack("!H", conn.recv(2))[0]
    elif length == 127:
        length = struct.unpack("!Q", conn.recv(8))[0]
    mask = conn.recv(4)
    payload = bytearray(conn.recv(length))
    for i in range(length):
        payload[i] ^= mask[i % 4]
    return payload.decode("utf-8")


def udp_receiver(state: BridgeState, stat_port: int) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("", stat_port))
    print(f"[UDP] listening on 0.0.0.0:{stat_port}")
    while True:
        data, addr = sock.recvfrom(1024)
        text = data.decode("utf-8", errors="ignore").strip()
        kind, parsed = parse_kv_line(text)
        if kind != "STAT":
            continue
        parsed["host_ms"] = int(time.time() * 1000)
        score = {}
        with state.lock:
            state.board_addr = addr
            state.latest = parsed
            state.samples.append(parsed)
            cutoff = parsed["host_ms"] - 10000
            state.samples = [s for s in state.samples if int(s.get("host_ms", 0)) >= cutoff]
            score = compute_score(state.samples)
            write_csv_row(state, parsed)
        broadcast(state, {"type": "stat", "data": parsed, "score": score})


def write_csv_row(state: BridgeState, row: dict[str, Any]) -> None:
    if state.csv_writer is None:
        return
    state.csv_writer.writerow({key: row.get(key, "") for key in CSV_FIELDS})
    if state.csv_file:
        state.csv_file.flush()


def broadcast(state: BridgeState, payload: dict[str, Any]) -> None:
    frame = encode_ws_payload(payload)
    dead: list[socket.socket] = []
    with state.lock:
        clients = list(state.clients)
    for client in clients:
        try:
            client.sendall(frame)
        except OSError:
            dead.append(client)
    if dead:
        with state.lock:
            state.clients = [c for c in state.clients if c not in dead]


def send_board_command(state: BridgeState, cmd_port: int, text: str) -> bool:
    with state.lock:
        addr = state.board_addr
    if not addr:
        return False
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.sendto(text.encode("utf-8"), (addr[0], cmd_port))
        return True
    finally:
        sock.close()


def append_jsonl(path: str, data: dict[str, Any]) -> None:
    with open(path, "a", encoding="utf-8") as file:
        file.write(json.dumps(data, ensure_ascii=False) + "\n")


class RequestHandler(http.server.BaseHTTPRequestHandler):
    state: BridgeState
    cmd_port: int

    def do_GET(self) -> None:
        if self.path == "/":
            body = HTML_PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/ws":
            self.handle_websocket()
            return
        self.send_error(404)

    def handle_websocket(self) -> None:
        key = self.headers.get("Sec-WebSocket-Key")
        if not key:
            self.send_error(400)
            return
        accept = base64.b64encode(hashlib.sha1(
            (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()
        ).digest()).decode()
        self.send_response(101, "Switching Protocols")
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", accept)
        self.end_headers()
        conn = self.connection
        with self.state.lock:
            self.state.clients.append(conn)
            latest = dict(self.state.latest)
        if latest:
            conn.sendall(encode_ws_payload({"type": "stat", "data": latest}))
        try:
            while True:
                text = recv_ws_text(conn)
                if text is None:
                    break
                self.handle_ws_message(text)
        except OSError:
            pass
        finally:
            with self.state.lock:
                self.state.clients = [c for c in self.state.clients if c is not conn]

    def handle_ws_message(self, text: str) -> None:
        try:
            msg = json.loads(text)
        except json.JSONDecodeError:
            return
        if msg.get("type") == "set":
            params = msg.get("params") or {}
            command = "SET " + " ".join(f"{key}={int(value)}" for key, value in params.items())
        elif msg.get("type") == "cmd":
            command = str(msg.get("cmd", "")).upper()
            if command not in {"START", "STOP", "STATUS"}:
                return
        elif msg.get("type") in {"snapshot", "mark_good"}:
            self.save_mark(msg)
            return
        elif msg.get("type") == "csv_path":
            broadcast(self.state, {
                "type": "log",
                "message": f"csv: {self.state.csv_path}",
            })
            return
        else:
            return
        ok = send_board_command(self.state, self.cmd_port, command)
        broadcast(self.state, {
            "type": "log",
            "message": ("sent: " if ok else "no board: ") + command,
        })

    def save_mark(self, msg: dict[str, Any]) -> None:
        payload = {
            "host_ms": int(time.time() * 1000),
            "type": msg.get("type"),
            "name": msg.get("name", ""),
            "params": msg.get("params") or {},
            "score": msg.get("score") or {},
        }
        try:
            append_jsonl(self.state.marks_path, payload)
            broadcast(self.state, {
                "type": "snapshot",
                "name": msg.get("type"),
                "data": payload,
            })
        except OSError as exc:
            broadcast(self.state, {
                "type": "log",
                "message": f"save mark failed: {exc}",
            })

    def log_message(self, format: str, *args: Any) -> None:
        return


def make_handler(state: BridgeState, cmd_port: int) -> type[RequestHandler]:
    class BoundHandler(RequestHandler):
        pass
    BoundHandler.state = state
    BoundHandler.cmd_port = cmd_port
    return BoundHandler


class ReuseThreadingTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--http-port", type=int, default=8088)
    parser.add_argument("--stat-port", type=int, default=9001)
    parser.add_argument("--cmd-port", type=int, default=9002)
    parser.add_argument("--log-dir", default=os.path.join(os.getcwd(), "tuning_logs"))
    args = parser.parse_args()

    state = BridgeState()
    os.makedirs(args.log_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    state.log_dir = args.log_dir
    state.csv_path = os.path.join(args.log_dir, f"telemetry_{stamp}.csv")
    state.marks_path = os.path.join(args.log_dir, f"marks_{stamp}.jsonl")
    state.csv_file = open(state.csv_path, "w", newline="", encoding="utf-8")
    state.csv_writer = csv.DictWriter(state.csv_file, fieldnames=CSV_FIELDS)
    state.csv_writer.writeheader()
    threading.Thread(target=udp_receiver, args=(state, args.stat_port), daemon=True).start()

    handler = make_handler(state, args.cmd_port)
    with ReuseThreadingTCPServer((args.host, args.http_port), handler) as server:
        local_ip = socket.gethostbyname(socket.gethostname())
        print(f"[WEB] http://127.0.0.1:{args.http_port}")
        print(f"[WEB] http://{local_ip}:{args.http_port}")
        print(f"[LOG] csv: {state.csv_path}")
        print(f"[LOG] marks: {state.marks_path}")
        print("[INFO] Keep this bridge running while tuning.")
        try:
            server.serve_forever()
        finally:
            if state.csv_file:
                state.csv_file.close()


if __name__ == "__main__":
    main()

