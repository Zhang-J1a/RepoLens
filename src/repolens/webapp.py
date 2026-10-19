"""Local browser UI and loopback API for RepoLens."""

from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sqlite3
import threading
import webbrowser
from typing import Any
from urllib.parse import urlsplit

from repolens import __version__
from repolens.config import data_directory
from repolens.context import EvidenceContextPacker
from repolens.domain import RepoLensError
from repolens.impact import analyze_impact
from repolens.index import IndexStore
from repolens.ingestion import ingest_or_reuse
from repolens.pipeline import QuestionAnswerPipeline
from repolens.provider import DeepSeekProvider, MockProvider
from repolens.graph.workflow import inspect_graph, search_version


MAX_BODY_BYTES = 128 * 1024
MAX_TEXT_LENGTH = 8192


_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>RepoLens | Local Code Intelligence</title>
  <style>
    :root {
      --ink: #17202a;
      --muted: #687581;
      --line: #d8e0e5;
      --surface: #ffffff;
      --canvas: #f3f6f7;
      --sidebar: #1f2c32;
      --sidebar-muted: #a9b8bd;
      --accent: #0b7f79;
      --accent-dark: #09655f;
      --accent-soft: #e2f2f0;
      --warning: #a96714;
      --danger: #b54848;
      --shadow: 0 10px 30px rgba(23, 32, 42, .08);
      font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
      color: var(--ink);
      background: var(--canvas);
    }
    * { box-sizing: border-box; }
    body { margin: 0; min-width: 320px; background: var(--canvas); }
    button, input, textarea, select { font: inherit; }
    button { cursor: pointer; }
    .app { min-height: 100vh; display: flex; flex-direction: column; }
    .topbar {
      height: 64px; display: flex; align-items: center; justify-content: space-between;
      padding: 0 24px; background: var(--surface); border-bottom: 1px solid var(--line);
    }
    .brand { display: flex; align-items: center; gap: 10px; font-weight: 700; letter-spacing: .1px; }
    .brand-mark {
      width: 30px; height: 30px; display: grid; place-items: center; color: #fff;
      background: var(--accent); border-radius: 7px; font-weight: 800;
    }
    .brand small { color: var(--muted); font-weight: 500; margin-left: 4px; }
    .top-actions { display: flex; align-items: center; gap: 10px; }
    .status-dot { width: 8px; height: 8px; border-radius: 50%; background: #5cb85c; }
    .status-dot.offline { background: #b9c2c6; }
    .status-text { color: var(--muted); font-size: 13px; }
    .icon-button, .secondary-button, .primary-button {
      border: 1px solid var(--line); border-radius: 6px; background: var(--surface);
      color: var(--ink); padding: 8px 12px;
    }
    .icon-button:hover, .secondary-button:hover { border-color: var(--accent); color: var(--accent-dark); }
    .primary-button {
      border-color: var(--accent); background: var(--accent); color: #fff; font-weight: 650;
    }
    .primary-button:hover { background: var(--accent-dark); }
    .primary-button:disabled { opacity: .55; cursor: wait; }
    .layout { flex: 1; display: grid; grid-template-columns: 232px minmax(0, 1fr); }
    .sidebar { background: var(--sidebar); color: #fff; padding: 18px 12px; display: flex; flex-direction: column; }
    .nav-label { color: var(--sidebar-muted); text-transform: uppercase; font-size: 11px; letter-spacing: .08em; padding: 8px 12px; }
    .nav-button {
      display: flex; align-items: center; gap: 10px; width: 100%; text-align: left;
      border: 0; border-radius: 6px; background: transparent; color: #d9e3e6; padding: 11px 12px;
      margin-bottom: 3px;
    }
    .nav-button:hover { background: rgba(255,255,255,.08); }
    .nav-button.active { background: #315057; color: #fff; }
    .nav-icon { width: 20px; color: #8bd2cd; text-align: center; font-weight: 700; }
    .sidebar-footer { margin-top: auto; padding: 14px 12px 4px; color: var(--sidebar-muted); font-size: 12px; line-height: 1.55; }
    .main { padding: 28px clamp(20px, 4vw, 56px) 48px; max-width: 1280px; width: 100%; }
    .page-heading { display: flex; justify-content: space-between; align-items: end; gap: 20px; margin-bottom: 22px; }
    h1 { font-size: 26px; line-height: 1.2; margin: 0 0 6px; }
    .subtitle { color: var(--muted); font-size: 14px; margin: 0; }
    .workspace-bar {
      display: grid; grid-template-columns: minmax(260px, 1.6fr) minmax(220px, 1fr) 150px;
      gap: 12px; background: var(--surface); border: 1px solid var(--line); padding: 16px;
      border-radius: 8px; box-shadow: var(--shadow); margin-bottom: 18px;
    }
    .field { display: flex; flex-direction: column; gap: 6px; }
    .field label { color: var(--muted); font-size: 12px; font-weight: 650; }
    input, textarea, select {
      width: 100%; border: 1px solid var(--line); border-radius: 5px; background: #fff;
      color: var(--ink); padding: 9px 10px; outline: none;
    }
    input:focus, textarea:focus, select:focus { border-color: var(--accent); box-shadow: 0 0 0 2px var(--accent-soft); }
    textarea { min-height: 116px; resize: vertical; line-height: 1.55; }
    .view { display: none; }
    .view.active { display: block; }
    .panel {
      background: var(--surface); border: 1px solid var(--line); border-radius: 8px;
      padding: 20px; box-shadow: var(--shadow); margin-bottom: 18px;
    }
    .panel-heading { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 16px; }
    .panel-heading h2 { font-size: 16px; margin: 0; }
    .form-row { display: flex; justify-content: space-between; align-items: end; gap: 14px; margin-top: 14px; }
    .inline-fields { display: flex; gap: 12px; flex-wrap: wrap; }
    .compact { width: 160px; }
    .result-empty { color: var(--muted); border: 1px dashed var(--line); border-radius: 6px; padding: 24px; text-align: center; }
    .answer-summary { border-left: 3px solid var(--accent); padding: 4px 0 4px 14px; line-height: 1.7; margin-bottom: 18px; }
    .answer-status { color: var(--accent-dark); font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: .06em; margin-bottom: 6px; }
    .answer-status.abstained { color: var(--warning); }
    .claim-list, .unknown-list, .risk-list, .suggestion-list { display: grid; gap: 10px; padding: 0; margin: 0; list-style: none; }
    .claim, .risk, .suggestion { border: 1px solid var(--line); border-radius: 6px; padding: 12px 14px; line-height: 1.55; }
    .claim-citations, .meta-line { color: var(--muted); font-size: 12px; margin-top: 7px; }
    .citation-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 10px; margin-top: 12px; }
    .citation { border: 1px solid var(--line); background: #fbfcfc; border-radius: 6px; padding: 11px 12px; }
    .citation strong { color: var(--accent-dark); }
    .citation-path { font-family: Consolas, monospace; font-size: 12px; overflow-wrap: anywhere; margin-top: 5px; }
    .citation-detail { color: var(--muted); font-size: 12px; margin-top: 4px; }
    .unknown-list li { color: var(--warning); padding-left: 14px; position: relative; line-height: 1.5; }
    .unknown-list li::before { content: "!"; position: absolute; left: 0; font-weight: 700; }
    .chat-thread { display: grid; gap: 14px; max-height: 480px; overflow: auto; margin-bottom: 16px; }
    .chat-message { max-width: 86%; border-radius: 8px; padding: 12px 14px; line-height: 1.6; white-space: pre-wrap; }
    .chat-message.user { justify-self: end; background: var(--accent); color: #fff; }
    .chat-message.assistant { justify-self: start; background: #edf2f3; color: var(--ink); }
    .chat-message .message-label { display: block; font-size: 11px; opacity: .72; margin-bottom: 4px; }
    .impact-summary { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 18px; }
    .metric { border: 1px solid var(--line); border-radius: 6px; padding: 12px 14px; min-width: 120px; }
    .metric-value { display: block; font-size: 22px; font-weight: 700; color: var(--accent-dark); }
    .metric-label { color: var(--muted); font-size: 12px; }
    .table-wrap { overflow-x: auto; }
    table { border-collapse: collapse; width: 100%; font-size: 13px; }
    th, td { text-align: left; border-bottom: 1px solid var(--line); padding: 10px 8px; vertical-align: top; }
    th { color: var(--muted); font-size: 12px; font-weight: 650; }
    code, .mono { font-family: Consolas, "Courier New", monospace; }
    .tag { display: inline-block; padding: 3px 7px; border-radius: 4px; background: var(--accent-soft); color: var(--accent-dark); font-size: 11px; }
    .risk.high { border-left: 3px solid var(--danger); }
    .risk.medium { border-left: 3px solid var(--warning); }
    .error { color: var(--danger); background: #fff0f0; border: 1px solid #efc9c9; border-radius: 6px; padding: 11px 13px; margin-bottom: 14px; line-height: 1.5; }
    .success { color: var(--accent-dark); background: var(--accent-soft); border-radius: 6px; padding: 9px 11px; font-size: 13px; }
    .modal-backdrop { position: fixed; inset: 0; display: none; place-items: center; background: rgba(16, 28, 32, .4); padding: 20px; z-index: 5; }
    .modal-backdrop.open { display: grid; }
    .modal { width: min(520px, 100%); background: var(--surface); border-radius: 8px; padding: 22px; box-shadow: 0 24px 70px rgba(0,0,0,.2); }
    .modal h2 { margin: 0 0 8px; font-size: 18px; }
    .modal p { color: var(--muted); font-size: 13px; line-height: 1.55; }
    .modal-actions { display: flex; justify-content: flex-end; gap: 9px; margin-top: 18px; }
    @media (max-width: 820px) {
      .layout { grid-template-columns: 1fr; }
      .sidebar { padding: 8px; flex-direction: row; align-items: center; gap: 4px; overflow-x: auto; }
      .nav-label, .sidebar-footer { display: none; }
      .nav-button { width: auto; white-space: nowrap; margin: 0; }
      .workspace-bar { grid-template-columns: 1fr; }
      .page-heading { align-items: start; flex-direction: column; }
      .main { padding: 20px 14px 32px; }
    }
  </style>
</head>
<body>
  <div class="app">
    <header class="topbar">
      <div class="brand"><span class="brand-mark">R</span><span>RepoLens <small>Local Code Intelligence</small></span></div>
      <div class="top-actions">
        <span id="health-dot" class="status-dot offline"></span>
        <span id="health-text" class="status-text">连接中</span>
        <button id="settings-button" class="icon-button" type="button">设置</button>
      </div>
    </header>
    <div class="layout">
      <aside class="sidebar">
        <div class="nav-label">Workspace</div>
        <button class="nav-button active" data-view="ask-view" type="button"><span class="nav-icon">?</span>代码问答</button>
        <button class="nav-button" data-view="chat-view" type="button"><span class="nav-icon">↔</span>连续对话</button>
        <button class="nav-button" data-view="impact-view" type="button"><span class="nav-icon">Δ</span>变更影响</button>
        <div class="sidebar-footer">只读取本地 Git commit<br>证据与引用可回查</div>
      </aside>
      <main class="main">
        <div class="page-heading">
          <div><h1 id="view-title">代码问答</h1><p id="view-subtitle" class="subtitle">针对一个精确 Git snapshot 提问，回答会带可回查引用。</p></div>
        </div>
        <section class="workspace-bar">
          <div class="field"><label for="repository">仓库路径</label><input id="repository" placeholder="D:\projects\your-repository"></div>
          <div class="field"><label for="data-dir">索引目录</label><input id="data-dir" placeholder="留空使用 RepoLens 默认目录"></div>
          <div class="field"><label for="provider">回答模型</label><select id="provider"><option value="mock">Mock（离线）</option><option value="deepseek">DeepSeek</option><option value="langchain">LangChain + DeepSeek</option></select></div>
        </section>

        <section id="ask-view" class="view active">
          <div class="panel">
            <div class="panel-heading"><h2>向代码提问</h2><span class="tag">snapshot-scoped</span></div>
            <div class="field"><label for="question">问题</label><textarea id="question" placeholder="例如：这个项目的请求入口在哪里？它如何处理异常？"></textarea></div>
            <div class="form-row">
              <div class="inline-fields">
                <div class="field compact"><label for="ask-ref">Git ref</label><input id="ask-ref" value="HEAD"></div>
                <div class="field compact"><label for="follow-ups">追加检索</label><select id="follow-ups"><option value="1">1 次</option><option value="0">关闭</option><option value="2">2 次</option><option value="3">3 次</option></select></div>
              </div>
              <button id="ask-button" class="primary-button" type="button">提交问题</button>
            </div>
          </div>
          <div id="ask-error"></div>
          <div id="ask-result" class="panel"><div class="result-empty">提交问题后，回答和引用会显示在这里。</div></div>
        </section>

        <section id="chat-view" class="view">
          <div class="panel">
            <div class="panel-heading"><h2>连续对话</h2><button id="clear-chat" class="secondary-button" type="button">清空对话</button></div>
            <div id="chat-thread" class="chat-thread"><div class="result-empty">在同一个 snapshot 上连续追问。</div></div>
            <div class="field"><label for="chat-question">继续提问</label><textarea id="chat-question" placeholder="输入追问后按发送"></textarea></div>
            <div class="form-row"><span class="meta-line">历史只保留最近 8 条消息，引用来自当前轮 evidence。</span><button id="chat-button" class="primary-button" type="button">发送</button></div>
          </div>
          <div id="chat-error"></div>
        </section>

        <section id="impact-view" class="view">
          <div class="panel">
            <div class="panel-heading"><h2>比较两个 Git commit</h2><span class="tag">read-only</span></div>
            <div class="inline-fields">
              <div class="field compact"><label for="base-ref">Base</label><input id="base-ref" placeholder="HEAD~1"></div>
              <div class="field compact"><label for="head-ref">Head</label><input id="head-ref" value="HEAD"></div>
            </div>
            <div class="form-row"><span class="meta-line">分析文件、Python symbol、测试、文档、风险和建议测试。</span><button id="impact-button" class="primary-button" type="button">运行影响分析</button></div>
          </div>
          <div id="impact-error"></div>
          <div id="impact-result" class="panel"><div class="result-empty">选择 base/head 后运行分析。</div></div>
        </section>
      </main>
    </div>
  </div>

  <div id="settings-modal" class="modal-backdrop">
    <div class="modal">
      <h2>运行设置</h2>
      <p>DeepSeek Key 只保存在当前 RepoLens 进程内，关闭服务后失效，不写入浏览器存储、源码或日志。</p>
      <div class="field"><label for="api-key">DEEPSEEK_API_KEY</label><input id="api-key" type="password" autocomplete="off" placeholder="输入后保存到当前进程"></div>
      <div id="settings-status"></div>
      <div class="modal-actions"><button id="settings-cancel" class="secondary-button" type="button">取消</button><button id="settings-save" class="primary-button" type="button">保存设置</button></div>
    </div>
  </div>
  <script>
    const $ = (id) => document.getElementById(id);
    const state = { history: [], view: "ask-view" };
    const titles = {
      "ask-view": ["代码问答", "针对一个精确 Git snapshot 提问，回答会带可回查引用。"],
      "chat-view": ["连续对话", "在同一个代码版本上连续追问，当前轮引用保持独立。"],
      "impact-view": ["变更影响", "比较两个本地 commit，定位变化 symbol、测试、文档和潜在风险。"]
    };

    function setError(id, message) {
      const target = $(id);
      target.textContent = "";
      if (message) {
        const box = document.createElement("div");
        box.className = "error";
        box.textContent = message;
        target.appendChild(box);
      }
    }

    function value(id) { return $(id).value.trim(); }

    async function request(path, payload) {
      const response = await fetch(path, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload)
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "请求失败");
      return data;
    }

    function commonPayload() {
      return {
        repository: value("repository"),
        data_dir: value("data-dir") || null,
        provider: value("provider")
      };
    }

    function buttonBusy(button, busy) {
      button.disabled = busy;
      button.dataset.original = button.dataset.original || button.textContent;
      button.textContent = busy ? "处理中..." : button.dataset.original;
    }

    function addText(parent, className, text) {
      const node = document.createElement("div");
      node.className = className;
      node.textContent = text;
      parent.appendChild(node);
      return node;
    }

    function renderAnswer(parent, result) {
      parent.textContent = "";
      const answer = result.answer;
      const summary = document.createElement("div");
      summary.className = "answer-summary";
      addText(summary, "answer-status " + answer.status, answer.status === "answered" ? "ANSWERED" : "ABSTAINED");
      addText(summary, "", answer.summary);
      parent.appendChild(summary);
      if (answer.claims && answer.claims.length) {
        addText(parent, "meta-line", "事实声明");
        const list = document.createElement("ul");
        list.className = "claim-list";
        answer.claims.forEach((claim) => {
          const item = document.createElement("li");
          item.className = "claim";
          addText(item, "", claim.text);
          addText(item, "claim-citations", "引用: " + claim.citation_ids.join(", "));
          list.appendChild(item);
        });
        parent.appendChild(list);
      }
      if (answer.citations && answer.citations.length) {
        addText(parent, "meta-line", "证据定位");
        const grid = document.createElement("div");
        grid.className = "citation-grid";
        answer.citations.forEach((citation) => {
          const item = document.createElement("div");
          item.className = "citation";
          addText(item, "", citation.citation_id);
          addText(item, "citation-path", citation.path);
          addText(item, "citation-detail", (citation.symbol || "module") + " · lines " + citation.line_start + "-" + citation.line_end + " · " + citation.commit_sha.slice(0, 12));
          grid.appendChild(item);
        });
        parent.appendChild(grid);
      }
      if (answer.unknowns && answer.unknowns.length) {
        addText(parent, "meta-line", "未知与边界");
        const list = document.createElement("ul");
        list.className = "unknown-list";
        answer.unknowns.forEach((text) => addText(list, "", text));
        parent.appendChild(list);
      }
      addText(parent, "meta-line", "snapshot " + result.snapshot_id + " · trace " + answer.trace_id);
    }

    function persistWorkspace() {
      localStorage.setItem("repolens.repository", value("repository"));
      localStorage.setItem("repolens.data_dir", value("data-dir"));
    }

    function restoreWorkspace() {
      $("repository").value = localStorage.getItem("repolens.repository") || "";
      $("data-dir").value = localStorage.getItem("repolens.data_dir") || "";
    }

    async function runAsk() {
      const question = value("question");
      if (!value("repository") || !question) { setError("ask-error", "请填写仓库路径和问题。"); return; }
      persistWorkspace();
      const button = $("ask-button");
      buttonBusy(button, true); setError("ask-error", "");
      try {
        const result = await request("/api/ask", Object.assign(commonPayload(), {
          question: question,
          ref: value("ask-ref") || "HEAD",
          max_follow_ups: Number(value("follow-ups"))
        }));
        renderAnswer($("ask-result"), result);
      } catch (error) { setError("ask-error", error.message); }
      finally { buttonBusy(button, false); }
    }

    function renderChatMessage(role, text) {
      const thread = $("chat-thread");
      if (thread.querySelector(".result-empty")) thread.textContent = "";
      const item = document.createElement("div");
      item.className = "chat-message " + role;
      addText(item, "message-label", role === "user" ? "你" : "RepoLens");
      addText(item, "", text);
      thread.appendChild(item);
      thread.scrollTop = thread.scrollHeight;
    }

    async function runChat() {
      const question = value("chat-question");
      if (!value("repository") || !question) { setError("chat-error", "请填写仓库路径和追问。"); return; }
      persistWorkspace();
      const button = $("chat-button");
      buttonBusy(button, true); setError("chat-error", "");
      renderChatMessage("user", question);
      try {
        const result = await request("/api/ask", Object.assign(commonPayload(), {
          question: question,
          ref: value("ask-ref") || "HEAD",
          history: state.history,
          max_follow_ups: Number(value("follow-ups"))
        }));
        state.history.push({role: "user", content: question});
        state.history.push({role: "assistant", content: result.answer.summary.slice(0, 2000)});
        state.history = state.history.slice(-8);
        renderChatMessage("assistant", result.answer.summary);
        $("chat-question").value = "";
      } catch (error) { setError("chat-error", error.message); }
      finally { buttonBusy(button, false); }
    }

    function renderImpact(report) {
      const parent = $("impact-result");
      parent.textContent = "";
      addText(parent, "answer-summary", report.summary);
      const metrics = document.createElement("div");
      metrics.className = "impact-summary";
      [["changed_files", report.changed_files.length, "变更文件"], ["tests", report.related_tests.length, "相关测试"], ["docs", report.related_docs.length, "相关文档"], ["risks", report.risks.length, "规则风险"]].forEach((entry) => {
        const metric = document.createElement("div");
        metric.className = "metric";
        addText(metric, "metric-value", String(entry[1]));
        addText(metric, "metric-label", entry[2]);
        metrics.appendChild(metric);
      });
      parent.appendChild(metrics);
      addText(parent, "meta-line", "base " + report.base.commit_sha.slice(0, 12) + " → head " + report.head.commit_sha.slice(0, 12));
      const tableWrap = document.createElement("div");
      tableWrap.className = "table-wrap";
      const table = document.createElement("table");
      const head = document.createElement("tr");
      ["状态", "路径", "分类", "变化 symbol"].forEach((label) => addText(head, "th", label));
      table.appendChild(head);
      report.changed_files.forEach((file) => {
        const row = document.createElement("tr");
        addText(row, "td", file.status);
        addText(row, "td", file.path);
        addText(row, "td", file.category);
        addText(row, "td", file.symbols.map((symbol) => symbol.name + " (" + symbol.change + ")").join(", ") || "module-level");
        table.appendChild(row);
      });
      tableWrap.appendChild(table); parent.appendChild(tableWrap);
      if (report.risks.length) {
        addText(parent, "meta-line", "潜在风险（规则推断）");
        const list = document.createElement("ul"); list.className = "risk-list";
        report.risks.forEach((risk) => {
          const item = document.createElement("li"); item.className = "risk " + risk.severity;
          addText(item, "", "[" + risk.severity + "] " + risk.reason);
          addText(item, "meta-line", risk.path + " · inference: " + risk.inference);
          list.appendChild(item);
        });
        parent.appendChild(list);
      }
      if (report.suggested_tests.length) {
        addText(parent, "meta-line", "建议测试");
        const list = document.createElement("ul"); list.className = "suggestion-list";
        report.suggested_tests.forEach((suggestion) => {
          const item = document.createElement("li"); item.className = "suggestion";
          addText(item, "", suggestion.text);
          list.appendChild(item);
        });
        parent.appendChild(list);
      }
      if (report.unknowns.length) {
        addText(parent, "meta-line", "未知与边界");
        const list = document.createElement("ul"); list.className = "unknown-list";
        report.unknowns.forEach((text) => addText(list, "", text));
        parent.appendChild(list);
      }
      addText(parent, "meta-line", "schema " + report.schema_version + " · trace " + report.trace_id);
    }

    async function runImpact() {
      if (!value("repository") || !value("base-ref")) { setError("impact-error", "请填写仓库路径和 base commit/ref。"); return; }
      persistWorkspace();
      const button = $("impact-button");
      buttonBusy(button, true); setError("impact-error", "");
      try {
        const result = await request("/api/impact", Object.assign(commonPayload(), {
          base: value("base-ref"), head: value("head-ref") || "HEAD"
        }));
        renderImpact(result);
      } catch (error) { setError("impact-error", error.message); }
      finally { buttonBusy(button, false); }
    }

    async function checkHealth() {
      try {
        const response = await fetch("/api/health");
        const data = await response.json();
        $("health-dot").classList.remove("offline");
        $("health-text").textContent = "本地服务已连接 · v" + data.version;
        $("settings-status").textContent = data.key_configured ? "当前进程已有 DeepSeek Key。" : "当前未设置 DeepSeek Key。";
      } catch (error) {
        $("health-text").textContent = "服务不可用";
      }
    }

    document.querySelectorAll(".nav-button").forEach((button) => button.addEventListener("click", () => {
      document.querySelectorAll(".nav-button").forEach((item) => item.classList.remove("active"));
      document.querySelectorAll(".view").forEach((item) => item.classList.remove("active"));
      button.classList.add("active");
      state.view = button.dataset.view;
      $(state.view).classList.add("active");
      $("view-title").textContent = titles[state.view][0];
      $("view-subtitle").textContent = titles[state.view][1];
    }));
    $("ask-button").addEventListener("click", runAsk);
    $("chat-button").addEventListener("click", runChat);
    $("impact-button").addEventListener("click", runImpact);
    $("clear-chat").addEventListener("click", () => { state.history = []; $("chat-thread").innerHTML = '<div class="result-empty">在同一个 snapshot 上连续追问。</div>'; setError("chat-error", ""); });
    $("settings-button").addEventListener("click", () => $("settings-modal").classList.add("open"));
    $("settings-cancel").addEventListener("click", () => $("settings-modal").classList.remove("open"));
    $("settings-save").addEventListener("click", async () => {
      const button = $("settings-save"); buttonBusy(button, true);
      try {
        const result = await request("/api/settings", {api_key: $("api-key").value});
        $("settings-status").textContent = result.key_configured ? "已保存到当前进程。" : "已清除当前进程中的 Key。";
        $("api-key").value = "";
        setTimeout(() => $("settings-modal").classList.remove("open"), 500);
        checkHealth();
      } catch (error) { $("settings-status").textContent = error.message; }
      finally { buttonBusy(button, false); }
    });
    $("question").addEventListener("keydown", (event) => { if ((event.ctrlKey || event.metaKey) && event.key === "Enter") runAsk(); });
    $("chat-question").addEventListener("keydown", (event) => { if ((event.ctrlKey || event.metaKey) && event.key === "Enter") runChat(); });
    restoreWorkspace(); checkHealth();
  </script>
</body>
</html>"""


def _bounded_int(value: Any, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise RepoLensError(f"{name} must be between {minimum} and {maximum}.")
    return value


def _text(payload: dict[str, Any], name: str, *, required: bool = True, maximum: int = MAX_TEXT_LENGTH) -> str:
    value = payload.get(name)
    if value is None and not required:
        return ""
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        requirement = "required" if required else "optional"
        raise RepoLensError(f"{name} must be {requirement} text of at most {maximum} characters.")
    return value.strip()


def _history(payload: dict[str, Any]) -> tuple[dict[str, str], ...]:
    value = payload.get("history", [])
    if not isinstance(value, list):
        raise RepoLensError("history must be an array.")
    return tuple(value)


class _RepoLensHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, handler, default_data_dir: Path):
        super().__init__(address, handler)
        self.default_data_dir = default_data_dir
        self.runtime_api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip() or None


class _HTTPTransport(BaseHTTPRequestHandler):
    server: _RepoLensHTTPServer

    def log_message(self, format, *args):
        return

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self) -> None:
        body = _HTML.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        length = self.headers.get("Content-Length")
        try:
            size = int(length or "0")
        except ValueError as exc:
            raise RepoLensError("Request body length is invalid.") from exc
        if size < 1 or size > MAX_BODY_BYTES:
            raise RepoLensError("Request body must be between 1 byte and 128 KiB.")
        raw = self.rfile.read(size)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RepoLensError("Request body must be UTF-8 JSON.") from exc
        if not isinstance(payload, dict):
            raise RepoLensError("Request body must be a JSON object.")
        return payload

class WebOperations:
    """Transport-independent adapters shared by the legacy UI and V5 API."""

    def _directory(self, payload: dict[str, Any]) -> Path:
        value = payload.get("data_dir")
        if value is None or value == "":
            return self.server.default_data_dir
        if not isinstance(value, str) or len(value) > 4096:
            raise RepoLensError("data_dir must be a path of at most 4096 characters.")
        return data_directory(value)

    def _provider(self, payload: dict[str, Any]):
        name = payload.get("provider", "mock")
        if name == "mock":
            return MockProvider()
        if name not in ("deepseek", "langchain"):
            raise RepoLensError("provider must be mock, deepseek or langchain.")
        if not self.server.runtime_api_key:
            raise RepoLensError("DeepSeek API key is missing; set it in 设置 or DEEPSEEK_API_KEY.")
        model = payload.get("model")
        if model is not None and (not isinstance(model, str) or not model.strip() or len(model) > 128):
            raise RepoLensError("model must be non-empty text of at most 128 characters.")
        if name == "langchain":
            try:
                from repolens.langchain_integration import LangChainDeepSeekProvider
            except ImportError:
                raise RepoLensError("LangChain support is optional; install the 'langchain' extra first.") from None

            return LangChainDeepSeekProvider(self.server.runtime_api_key,
                                             model=model or DeepSeekProvider.DEFAULT_MODEL)
        return DeepSeekProvider(self.server.runtime_api_key, model=model or DeepSeekProvider.DEFAULT_MODEL)

    def _answer(self, payload: dict[str, Any]) -> dict[str, Any]:
        repository = _text(payload, "repository", maximum=4096)
        question = _text(payload, "question", maximum=4000)
        ref = _text(payload, "ref", required=False, maximum=512) or "HEAD"
        directory = self._directory(payload)
        limit = _bounded_int(payload.get("limit", 8), "limit", 1, 100)
        context_tokens = _bounded_int(payload.get("context_tokens", 1600), "context_tokens", 1, 100_000)
        output_tokens = _bounded_int(payload.get("output_tokens", 1024), "output_tokens", 1, 8192)
        follow_ups = _bounded_int(payload.get("max_follow_ups", 1), "max_follow_ups", 0, 3)
        strategy = payload.get("retrieval", "hybrid")
        if strategy not in ("keyword", "vector", "hybrid", "graph"):
            raise RepoLensError("retrieval must be keyword, vector, hybrid, or graph.")
        path_prefix = payload.get("path_prefix")
        if path_prefix is not None and (not isinstance(path_prefix, str) or len(path_prefix) > 4096):
            raise RepoLensError("path_prefix must be text of at most 4096 characters.")
        provider = self._provider(payload)
        ingestion = ingest_or_reuse(repository, directory, ref)
        with IndexStore(directory) as store:
            result = QuestionAnswerPipeline(
                store,
                ingestion["snapshot_id"],
                provider,
                context_packer=EvidenceContextPacker(context_tokens),
                max_output_tokens=output_tokens,
                max_follow_up_searches=follow_ups,
                retrieval_strategy=strategy,
                retriever_factory=getattr(provider, "retriever_factory", None),
            ).answer(
                question,
                limit=limit,
                path_prefix=path_prefix or None,
                history=_history(payload),
            ).to_dict()
        result["workflow"] = {
            "repository": ingestion["root"],
            "ref": ref,
            "snapshot_id": ingestion["snapshot_id"],
            "commit_sha": ingestion["commit_sha"],
            "index_action": ingestion["index_action"],
        }
        return result

    def _impact(self, payload: dict[str, Any]) -> dict[str, Any]:
        repository = _text(payload, "repository", maximum=4096)
        base = _text(payload, "base", maximum=512)
        head = _text(payload, "head", required=False, maximum=512) or "HEAD"
        directory = self._directory(payload)
        context_tokens = _bounded_int(payload.get("context_tokens", 2400), "context_tokens", 1, 100_000)
        output_tokens = _bounded_int(payload.get("output_tokens", 768), "output_tokens", 1, 8192)
        with_graph = payload.get("with_graph", False)
        if type(with_graph) is not bool:
            raise RepoLensError("with_graph must be a boolean.")
        return analyze_impact(
            repository,
            directory,
            base,
            head,
            provider=self._provider(payload),
            context_tokens=context_tokens,
            output_tokens=output_tokens,
            with_graph=with_graph,
        )

    def _agent(self, payload: dict[str, Any]) -> dict[str, Any]:
        from repolens.agent import AgentBudget, ControlledAgent

        repository = _text(payload, "repository", maximum=4096)
        question = _text(payload, "question", maximum=4000)
        ref = _text(payload, "ref", required=False, maximum=512) or "HEAD"
        base = _text(payload, "base", required=False, maximum=512) or None
        settings = payload.get("budget", {})
        if not isinstance(settings, dict) or set(settings) - set(AgentBudget.__dataclass_fields__):
            raise RepoLensError("budget must contain only supported AgentBudget fields.")
        budget = AgentBudget(**settings)
        provider = self._provider(payload)
        if hasattr(provider, "max_retries"):
            provider.max_retries = 0
        return ControlledAgent(provider, budget=budget).run(
            repository, self._directory(payload), question, ref=ref, base_ref=base,
            on_event=getattr(self, "on_event", None),
        )

    def _graph(self, payload):
        commit = payload.get("commit", False)
        if not isinstance(commit, bool):
            raise RepoLensError("commit must be a boolean graph seed selector.")
        return inspect_graph(
            _text(payload, "repository", maximum=4096), self._directory(payload),
            _text(payload, "ref", required=False, maximum=512) or "HEAD",
            symbol=_text(payload, "symbol", required=False, maximum=512) or None,
            path=_text(payload, "path", required=False, maximum=4096) or None, commit=commit,
            hops=_bounded_int(payload.get("hops", 2), "hops", 1, 2),
            max_nodes=_bounded_int(payload.get("max_nodes", 100), "max_nodes", 1, 500),
            max_edges=_bounded_int(payload.get("max_edges", 200), "max_edges", 1, 2000),
        )

    def _version_search(self, payload):
        return search_version(
            _text(payload, "repository", maximum=4096), self._directory(payload),
            _text(payload, "query", maximum=4096), _text(payload, "ref", required=False, maximum=512) or "HEAD",
            strategy=payload.get("retrieval", "graph"),
            limit=_bounded_int(payload.get("limit", 10), "limit", 1, 100),
            path_prefix=_text(payload, "path_prefix", required=False, maximum=4096) or None,
        )

class RepoLensRequestHandler(_HTTPTransport, WebOperations):
    def _local_request(self, *, post=False):
        host = self.headers.get("Host", "")
        try:
            hostname = urlsplit("//" + host).hostname
        except ValueError:
            hostname = None
        origin = self.headers.get("Origin")
        if (hostname not in ("127.0.0.1", "localhost", "::1")
                or (origin and origin != "http://" + host)
                or self.headers.get("Sec-Fetch-Site") == "cross-site"):
            self.close_connection = True
            self._send_json(HTTPStatus.FORBIDDEN, {"error": "Cross-site requests are not allowed."})
            return False
        if post and self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            self.close_connection = True
            self._send_json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"error": "Request must use application/json."})
            return False
        return True

    def do_GET(self) -> None:
        try:
            if not self._local_request():
                return
            if self.path == "/" or self.path == "/index.html":
                self._send_html()
            elif self.path == "/api/health":
                self._send_json(HTTPStatus.OK, {
                    "ok": True,
                    "version": __version__,
                    "key_configured": bool(self.server.runtime_api_key),
                    "data_dir": str(self.server.default_data_dir),
                })
            else:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found."})
        except (BrokenPipeError, ConnectionResetError):
            return

    def do_POST(self) -> None:
        try:
            if not self._local_request(post=True):
                return
            payload = self._read_json()
            if self.path == "/api/settings":
                key = payload.get("api_key", "")
                if not isinstance(key, str) or len(key) > 4096:
                    raise RepoLensError("api_key must be text of at most 4096 characters.")
                self.server.runtime_api_key = key.strip() or None
                self._send_json(HTTPStatus.OK, {"ok": True, "key_configured": bool(self.server.runtime_api_key)})
            elif self.path == "/api/ask":
                self._send_json(HTTPStatus.OK, self._answer(payload))
            elif self.path == "/api/impact":
                self._send_json(HTTPStatus.OK, self._impact(payload))
            elif self.path == "/api/agent":
                self._send_json(HTTPStatus.OK, self._agent(payload))
            elif self.path == "/api/graph":
                self._send_json(HTTPStatus.OK, self._graph(payload))
            elif self.path == "/api/search":
                self._send_json(HTTPStatus.OK, self._version_search(payload))
            else:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found."})
        except RepoLensError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except (OSError, ValueError, sqlite3.Error):
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "Local operation failed; check the repository and index path."})
        except (BrokenPipeError, ConnectionResetError):
            return


def create_server(host: str = "127.0.0.1", port: int = 0, default_data_dir: Path | None = None) -> _RepoLensHTTPServer:
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise RepoLensError("The browser UI must bind to the local machine.")
    if isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= 65535:
        raise RepoLensError("UI port must be between 0 and 65535.")
    directory = (default_data_dir or data_directory()).resolve()
    return _RepoLensHTTPServer((host, port), RepoLensRequestHandler, directory)


def serve_forever(
    host: str = "127.0.0.1",
    port: int = 0,
    *,
    default_data_dir: Path | None = None,
    open_browser: bool = True,
) -> str:
    """Start the local UI and return its URL after the server is ready."""

    server = create_server(host, port, default_data_dir)
    display_host = "localhost" if host in ("127.0.0.1", "localhost") else host
    url = f"http://{display_host}:{server.server_port}/"
    if open_browser:
        threading.Timer(0.25, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return url


def launch() -> None:
    """Launch the browser UI for a double-clickable .pyw entry point."""

    serve_forever(open_browser=True)


if __name__ == "__main__":
    serve_forever()
