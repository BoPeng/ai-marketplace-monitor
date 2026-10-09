// AI Marketplace Monitor — Web UI frontend.
// Vanilla JS, no build step. Provides:
//   - Login form + session cookie handling
//   - TOML editor with line numbers and syntax highlighting (lightweight)
//   - Live log tail via WebSocket with level/text filtering + expand
//   - Listings view: every evaluated listing, with its rating and decision
//   - Save / Validate with inline error at the offending line

(() => {
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => Array.from(document.querySelectorAll(sel));

  const state = {
    csrf: null,
    fileId: "primary",
    baseMtime: null,
    originalContent: "",
    currentContent: "",
    logLevel: "ALL",
    logFilter: "",
    view: "logs", // "logs" | "listings"
    evalItem: "",
    evalStage: "",
    evalMinRating: "",
    evalFilter: "",
    evalSort: { key: "time", desc: true },
    evalRecords: [],
    evalTotal: 0,
    evalTimer: null,
    ws: null,
    records: [],
    expanded: new Set(),
    lastActivity: null, // epoch seconds of the most recent log record
    monitorState: "disconnected", // "connected" | "idle" | "disconnected"
    wsConnected: false,
    errorCount: 0, // unread ERROR-level messages (for tab badge)
    chatWs: null,
    chatActive: false,
    chatPrompt: null,
  };

  // ---------------------------------------------------------------
  // Cookies / auth
  // ---------------------------------------------------------------
  const getCookie = (name) => {
    const m = document.cookie.match(new RegExp("(?:^|; )" + name + "=([^;]*)"));
    return m ? decodeURIComponent(m[1]) : null;
  };

  const api = async (path, opts = {}) => {
    const headers = { ...(opts.headers || {}) };
    if (opts.method && opts.method !== "GET" && state.csrf) {
      headers["X-CSRF-Token"] = state.csrf;
    }
    if (opts.body && !(opts.body instanceof FormData)) {
      headers["Content-Type"] = "application/json";
    }
    const res = await fetch(path, { ...opts, headers, credentials: "same-origin" });
    if (res.status === 401) {
      showLogin();
      throw new Error("unauthenticated");
    }
    return res;
  };

  // ---------------------------------------------------------------
  // Login flow
  // ---------------------------------------------------------------
  const showLogin = async () => {
    $("#login-screen").classList.remove("hidden");
    $("#app").classList.add("hidden");
    // Fetch the auth mode so we can decide between login form and open mode.
    try {
      const info = await (await fetch("/api/auth/info", { credentials: "same-origin" })).json();
      if (info.proxy_error) {
        // a reverse proxy signs users in, and this request did not come through it: a
        // password form cannot help, so say what is missing
        const subtitle = $("#login-subtitle");
        subtitle.textContent = `${info.proxy_error} Open aimm through your reverse proxy.`;
        subtitle.hidden = false;
        // the form's CSS sets display, which would override the hidden attribute
        $("#login-form").querySelectorAll("label, #login-submit").forEach((el) => { el.style.display = "none"; });
        return;
      }
      if (info.open) {
        // Open mode — no credentials configured, auto-login as anonymous.
        const res = await fetch("/api/login", {
          method: "POST",
          body: new FormData(),
          credentials: "same-origin",
        });
        if (res.ok) {
          const data = await res.json();
          state.csrf = data.csrf || getCookie("aimm_csrf");
          hideLogin();
          await bootstrap();
          return;
        }
      }
      // Authenticated mode — show sign-in form.
      const form = $("#login-form");
      const subtitle = $("#login-subtitle");
      subtitle.textContent =
        "Sign in with the marketplace credentials from your config.";
      subtitle.hidden = false;
      $("#login-submit").textContent = "Sign in";
      if (info.username_hint) form.username.value = info.username_hint;
    } catch (err) {
      // fall back to generic login form
    }
  };
  const hideLogin = () => {
    $("#login-screen").classList.add("hidden");
    $("#app").classList.remove("hidden");
  };

  $("#login-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const form = e.target;
    const body = new FormData();
    body.set("username", form.username.value);
    body.set("password", form.password.value);
    try {
      const res = await fetch("/api/login", { method: "POST", body, credentials: "same-origin" });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Login failed" }));
        $("#login-error").textContent = err.detail || "Login failed";
        $("#login-error").hidden = false;
        return;
      }
      const data = await res.json();
      state.csrf = data.csrf || getCookie("aimm_csrf");
      $("#login-error").hidden = true;
      hideLogin();
      await bootstrap();
    } catch (err) {
      $("#login-error").textContent = String(err);
      $("#login-error").hidden = false;
    }
  });

  $("#logout-btn").addEventListener("click", async () => {
    $("#settings-modal").classList.add("hidden");
    await api("/api/logout", { method: "POST" });
    if (state.ws) state.ws.close();
    state.csrf = null;
    showLogin();
  });

  // ---------------------------------------------------------------
  // Editor — CodeMirror 5 with TOML syntax highlighting
  // ---------------------------------------------------------------
  const editorHost = $("#editor-host");

  // Thin wrapper so the rest of the code uses editor.getValue() / editor.setValue()
  // regardless of whether CodeMirror loaded successfully.
  let editor;
  let validateTimer = null;
  const onEditorChange = () => {
    state.currentContent = editor.getValue();
    const dirty = state.currentContent !== state.originalContent;
    $("#save-btn").disabled = !dirty;
    if (validateTimer) clearTimeout(validateTimer);
    if (dirty) {
      setEditorStatus("typing…");
      validateTimer = setTimeout(() => {
        validateTimer = null;
        validateConfig();
      }, 400);
    }
  };

  if (window.CodeMirror) {
    editor = CodeMirror(editorHost, {
      mode: "toml",
      theme: "default",
      lineNumbers: true,
      indentUnit: 2,
      tabSize: 2,
      indentWithTabs: false,
      lineWrapping: false,
      extraKeys: {
        "Cmd-S": () => saveConfig(),
        "Ctrl-S": () => saveConfig(),
        Tab: (cm) => cm.replaceSelection("  ", "end"),
      },
    });
    editor.on("change", onEditorChange);
    // Expose a uniform API.
    editor.getValue = editor.getValue.bind(editor);
    editor.setValue = editor.setValue.bind(editor);
    editor.getScrollInfo = editor.getScrollInfo.bind(editor);
  } else {
    // Fallback: plain textarea if CodeMirror failed to load.
    const textarea = document.createElement("textarea");
    textarea.className = "aimm-editor";
    textarea.spellcheck = false;
    editorHost.appendChild(textarea);
    editor = {
      getValue: () => textarea.value,
      setValue: (v) => { textarea.value = v; },
      getScrollInfo: () => ({ top: textarea.scrollTop }),
      on: () => {},
      refresh: () => {},
    };
    textarea.addEventListener("input", onEditorChange);
    textarea.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "s") {
        e.preventDefault();
        saveConfig();
      }
    });
  }

  // ---------------------------------------------------------------
  // Config load / save / validate
  // ---------------------------------------------------------------
  const setEditorStatus = (msg, cls = "") => {
    const el = $("#editor-status");
    el.className = "editor-status " + cls;
    el.textContent = msg;
  };

  const loadConfig = async () => {
    const files = await (await api("/api/config/files")).json();
    if (!files.files.length) return;
    const f = files.files[0];
    state.fileId = f.id;
    $("#config-name").textContent = f.path;
    $("#mtime").textContent = "mtime " + new Date(f.mtime * 1000).toLocaleString();

    const res = await (await api(`/api/config/file/${f.id}`)).json();
    state.originalContent = res.content;
    state.currentContent = res.content;
    state.baseMtime = res.mtime;
    editor.setValue(res.content);
    // Prefer the server-provided sections list, but fall back to a
    // client-side scan if the server didn't include one (e.g. user is
    // running an older aimm that hasn't been restarted yet).
    if (Array.isArray(res.sections) && res.sections.length) {
      state.sections = res.sections;
    } else {
      state.sections = scanSectionsClient(res.content);
    }
    renderGutter();
    $("#save-btn").disabled = true;
    if (res.has_masked_secrets) {
      setEditorStatus(
        `🔒 Secrets masked as "${res.mask_token}" — leave them alone to preserve, or type over to replace.`,
        "ok"
      );
    } else {
      setEditorStatus("");
    }
  };

  const validateConfig = async () => {
    setEditorStatus("validating…");
    try {
      const res = await api("/api/config/validate", {
        method: "POST",
        body: JSON.stringify({ content: state.currentContent }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setEditorStatus(
          "✗ " + (data.detail || `HTTP ${res.status}`),
          "err"
        );
        return false;
      }
      if (data.valid) {
        setEditorStatus("✓ config is valid", "ok");
        return true;
      }
      setEditorStatus("✗ " + (data.error || "invalid"), "err");
      return false;
    } catch (err) {
      console.error("validate failed", err);
      setEditorStatus("✗ validate failed: " + err.message, "err");
      return false;
    }
  };

  const saveConfig = async () => {
    // If a debounced validate is pending, cancel it — the server will
    // re-validate on PUT anyway.
    if (validateTimer) {
      clearTimeout(validateTimer);
      validateTimer = null;
    }
    setEditorStatus("saving…");
    let res, data;
    try {
      res = await api(`/api/config/file/${state.fileId}`, {
        method: "PUT",
        body: JSON.stringify({
          content: state.currentContent,
          base_mtime: state.baseMtime,
        }),
      });
      data = await res.json().catch(() => ({}));
    } catch (err) {
      console.error("save failed", err);
      setEditorStatus("✗ save failed: " + err.message, "err");
      return;
    }
    if (!res.ok || !data.ok) {
      setEditorStatus(
        "✗ " + (data.error || data.detail || `HTTP ${res.status}`),
        "err"
      );
      if (res.status === 409) {
        if (confirm("Config was modified on disk. Reload from disk and lose your changes?")) {
          await loadConfig();
        }
      }
      return;
    }
    state.originalContent = state.currentContent;
    state.baseMtime = data.mtime;
    $("#save-btn").disabled = true;
    setEditorStatus("✓ saved — monitor will reload within 1s", "ok");
    $("#mtime").textContent = "mtime " + new Date(data.mtime * 1000).toLocaleString();
  };

  $("#save-btn").addEventListener("click", saveConfig);

  // ---------------------------------------------------------------
  // Logs
  // ---------------------------------------------------------------
  const LEVEL_ORDER = { DEBUG: 10, INFO: 20, WARNING: 30, ERROR: 40, CRITICAL: 50 };

  const matchesLevel = (record) => {
    if (state.logLevel === "ALL") return true;
    return LEVEL_ORDER[record.level] >= LEVEL_ORDER[state.logLevel];
  };
  const matchesFilter = (record) => {
    if (!state.logFilter) return true;
    return record.message.toLowerCase().includes(state.logFilter.toLowerCase());
  };
  const renderDetail = (record) => {
    const lines = [];
    lines.push(
      `<dl><dt>logger</dt><dd>${esc(record.logger)}</dd>` +
        `<dt>source</dt><dd>${esc(record.location)}</dd></dl>`
    );
    if (record.extra) {
      const extra = record.extra;
      const rows = Object.entries(extra)
        .map(([k, v]) => {
          if (k === "url" && typeof v === "string") {
            return `<dt>${esc(k)}</dt><dd><a href="${esc(v)}" target="_blank" rel="noopener">${esc(v)}</a></dd>`;
          }
          return `<dt>${esc(k)}</dt><dd>${esc(typeof v === "object" ? JSON.stringify(v) : String(v))}</dd>`;
        })
        .join("");
      lines.push(`<dl>${rows}</dl>`);
    }
    if (record.exc_text) {
      lines.push(`<pre>${esc(record.exc_text)}</pre>`);
    }
    return `<div class="log-detail">${lines.join("")}</div>`;
  };

  // Long messages (AI prompts, dumped objects) are folded to a short
  // preview until the row is expanded; the text filter still searches
  // the full message.
  const FOLD_LINES = 3;
  const FOLD_CHARS = 500;
  const foldMessage = (message) => {
    const lines = message.split("\n");
    let text = message;
    const hidden = [];
    if (lines.length > FOLD_LINES) {
      text = lines.slice(0, FOLD_LINES - 1).join("\n");
      hidden.push(`${lines.length - FOLD_LINES + 1} more lines`);
    }
    // Apply both limits: the retained lines can themselves be very long.
    if (text.length > FOLD_CHARS) {
      hidden.push(`${text.length - FOLD_CHARS} more characters`);
      text = text.slice(0, FOLD_CHARS);
    }
    return { text, more: hidden.join(" and ") };
  };

  const renderLogs = () => {
    if (state.view !== "logs") return;
    const container = $("#logs");
    const atBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 16;
    const visible = state.records.filter((r) => matchesLevel(r) && matchesFilter(r));
    container.innerHTML = visible
      .map((r) => {
        const expanded = state.expanded.has(r.id);
        const kind = r.extra && r.extra.kind;
        const badge = kind
          ? `<span class="kind-badge kind-${esc(kind)}">${esc(kind.replace(/_/g, " "))}</span>`
          : "";
        return (
          `<div class="log-row level-${esc(r.level)}${expanded ? " expanded" : ""}" data-id="${r.id}">` +
          `<span class="log-time">${esc(r.iso_time)}</span>` +
          `<span class="log-level">${esc(r.level)}</span>` +
          (() => {
            const { text, more } = expanded ? { text: r.message, more: "" } : foldMessage(r.message);
            const hint = more ? `<span class="log-more">… ${esc(more)}</span>` : "";
            return `<span class="log-msg">${badge}${esc(text)}${hint}</span>`;
          })() +
          (expanded ? renderDetail(r) : "") +
          `</div>`
        );
      })
      .join("");
    if ($("#autoscroll").checked && (atBottom || state.records.length < 20)) {
      container.scrollTop = container.scrollHeight;
    }
  };

  const esc = (s) =>
    String(s)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");

  $("#logs").addEventListener("click", (e) => {
    const row = e.target.closest(".log-row");
    if (!row) return;
    const id = Number(row.dataset.id);
    if (state.expanded.has(id)) state.expanded.delete(id);
    else state.expanded.add(id);
    renderLogs();
  });

  // Every level shows errors, so the unread-error badge clears once the text
  // filter (if any) lets all of them through.
  const clearErrorBadgeIfSeen = () => {
    const isError = (r) => r.level === "ERROR" || r.level === "CRITICAL";
    if (state.logFilter && !state.records.filter(isError).every(matchesFilter)) return;
    state.errorCount = 0;
    renderErrorBadge();
  };

  $$(".level-chips .chip").forEach((btn) => {
    btn.addEventListener("click", () => {
      $$(".level-chips .chip").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      state.logLevel = btn.dataset.level;
      clearErrorBadgeIfSeen();
      renderLogs();
    });
  });

  $("#log-filter").addEventListener("input", (e) => {
    state.logFilter = e.target.value;
    clearErrorBadgeIfSeen();
    renderLogs();
  });

  const loadLogs = async () => {
    const res = await (await api("/api/logs?limit=500")).json();
    state.records = res.records;
    state.records.forEach(noteActivity);
    renderLogs();
    renderMonitorStatus();
  };

  // ---------------------------------------------------------------
  // Listings: every listing aimm evaluated, and what it decided
  // ---------------------------------------------------------------
  const STAGE_LABELS = { notified: "Notified", rejected: "Rejected by AI", excluded: "Excluded" };

  const evalQuery = (withSort = true) => {
    const params = new URLSearchParams();
    if (state.evalItem) params.set("item", state.evalItem);
    if (state.evalStage) params.set("stage", state.evalStage);
    if (state.evalMinRating) params.set("min_rating", state.evalMinRating);
    if (state.evalFilter.trim()) params.set("q", state.evalFilter.trim());
    if (withSort) {
      // the server sorts before it limits the rows, so the order covers every match
      params.set("sort", state.evalSort.key);
      params.set("order", state.evalSort.desc ? "desc" : "asc");
    }
    return params;
  };

  const formatEvalTime = (epoch) =>
    new Date(epoch * 1000).toLocaleString([], {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });

  const renderEvaluations = () => {
    const container = $("#listings");
    const arrow = (key) =>
      state.evalSort.key === key ? (state.evalSort.desc ? " ▾" : " ▴") : "";
    const header =
      `<div class="eval-row eval-head">` +
      `<button class="eval-sort" data-sort="time">Time${arrow("time")}</button>` +
      `<span>Item</span><span>Listing</span><span>Price</span>` +
      `<button class="eval-sort" data-sort="rating">Rating${arrow("rating")}</button>` +
      `<span>Decision</span></div>`;
    const rows = state.evalRecords
      .map((r) => {
        const stage = STAGE_LABELS[r.stage] ? r.stage : "excluded";
        const why = r.reason || (r.ai_comment ? `AI: ${r.ai_comment}` : "");
        const rating =
          r.rating == null
            ? `<span class="eval-rating none" title="Not rated by AI">–</span>`
            : `<span class="eval-rating r${esc(r.rating)}" title="AI rating ${esc(r.rating)} of 5">${esc(r.rating)}</span>`;
        const title = r.url
          ? `<a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.title || r.id)}</a>`
          : esc(r.title || r.id);
        return (
          `<div class="eval-row stage-${esc(stage)}">` +
          `<span class="eval-time" title="${esc(new Date(r.time * 1000).toLocaleString())}">${esc(formatEvalTime(r.time))}</span>` +
          `<span class="eval-item" title="${esc(r.item)}">${esc(r.item)}</span>` +
          `<span class="eval-title">${title}` +
          (why ? `<span class="eval-reason" title="${esc(why)}">${esc(why)}</span>` : "") +
          `</span>` +
          `<span class="eval-price">${esc(r.price || "")}</span>` +
          rating +
          `<span class="eval-stage stage-${esc(stage)}" title="${esc(why || STAGE_LABELS[stage])}">${esc(STAGE_LABELS[stage])}</span>` +
          `</div>`
        );
      })
      .join("");
    const empty = state.evalRecords.length
      ? ""
      : `<div class="eval-empty">No evaluated listings${evalQuery(false).toString() ? " match these filters" : " yet"}.</div>`;
    const more =
      state.evalTotal > state.evalRecords.length
        ? `<div class="eval-empty">Showing the first ${state.evalRecords.length} of ${state.evalTotal}. Narrow the filters, or export CSV for all.</div>`
        : "";
    container.innerHTML = header + rows + empty + more;
  };

  const updateEvalItems = (items) => {
    const select = $("#eval-item");
    const current = select.value;
    const names = new Set(items);
    if (current) names.add(current);
    select.innerHTML =
      `<option value="">Any item</option>` +
      [...names]
        .sort()
        .map((n) => `<option value="${esc(n)}">${esc(n)}</option>`)
        .join("");
    select.value = current;
  };

  // Responses can arrive out of order (a slow one for an old filter); only the
  // latest request's response is shown.
  let evalRequestSeq = 0;
  const loadEvaluations = async () => {
    const seq = ++evalRequestSeq;
    try {
      const params = evalQuery();
      params.set("limit", "500");
      const res = await api(`/api/evaluations?${params.toString()}`);
      if (seq !== evalRequestSeq || !res.ok) return;
      const data = await res.json();
      if (seq !== evalRequestSeq) return;
      state.evalRecords = data.records || [];
      state.evalTotal = data.total || 0;
      updateEvalItems(data.items || []);
      renderEvaluations();
    } catch (err) {
      console.error(err);
    }
  };

  const showView = (view) => {
    state.view = view === "listings" ? "listings" : "logs";
    const listings = state.view === "listings";
    $$(".view-switch .chip").forEach((b) => {
      const active = b.dataset.view === state.view;
      b.classList.toggle("active", active);
      b.setAttribute("aria-selected", active ? "true" : "false");
    });
    $("#logs-controls").hidden = listings;
    $("#logs").hidden = listings;
    $("#listings-controls").hidden = !listings;
    $("#listings").hidden = !listings;
    try {
      localStorage.setItem("aimm.logsView", state.view);
    } catch (_) {}
    clearInterval(state.evalTimer);
    state.evalTimer = null;
    if (listings) {
      loadEvaluations();
      state.evalTimer = setInterval(loadEvaluations, 30000);
    } else {
      renderLogs();
    }
  };

  $$(".view-switch .chip").forEach((btn) => {
    btn.addEventListener("click", () => showView(btn.dataset.view));
  });

  $("#listings").addEventListener("click", (e) => {
    const btn = e.target.closest(".eval-sort");
    if (!btn) return;
    const key = btn.dataset.sort;
    state.evalSort =
      state.evalSort.key === key ? { key, desc: !state.evalSort.desc } : { key, desc: true };
    loadEvaluations();
  });

  [
    ["#eval-item", "evalItem"],
    ["#eval-stage", "evalStage"],
    ["#eval-rating", "evalMinRating"],
  ].forEach(([sel, key]) => {
    $(sel).addEventListener("change", (e) => {
      state[key] = e.target.value;
      loadEvaluations();
    });
  });

  let evalFilterTimer = null;
  $("#eval-filter").addEventListener("input", (e) => {
    state.evalFilter = e.target.value;
    clearTimeout(evalFilterTimer);
    evalFilterTimer = setTimeout(loadEvaluations, 300);
  });

  $("#eval-export").addEventListener("click", async () => {
    const btn = $("#eval-export");
    btn.disabled = true;
    try {
      const res = await api(`/api/evaluations.csv?${evalQuery().toString()}`);
      if (!res.ok) {
        setEditorStatus("⬇ Export failed: " + res.status, "err");
        return;
      }
      const url = URL.createObjectURL(await res.blob());
      const a = document.createElement("a");
      a.href = url;
      const disposition = res.headers.get("Content-Disposition") || "";
      const match = disposition.match(/filename="([^"]+)"/);
      a.download = match ? match[1] : "evaluations.csv";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setEditorStatus("⬇ Export failed: " + err.message, "err");
    } finally {
      btn.disabled = false;
    }
  });

  // -------- Monitor status chip derived from the log stream --------
  // Track activity timestamp from any log record.
  const noteActivity = (record) => {
    state.lastActivity = record.time;
    // Track error count for the Error tab badge.
    if (record.level === "ERROR" || record.level === "CRITICAL") {
      state.errorCount++;
      renderErrorBadge();
    }
  };

  const formatAgo = (epoch) => {
    if (!epoch) return "—";
    const s = Math.max(0, Math.round(Date.now() / 1000 - epoch));
    if (s < 60) return `${s}s ago`;
    if (s < 3600) return `${Math.round(s / 60)}m ago`;
    return `${Math.round(s / 3600)}h ago`;
  };

  // Monitor status is purely about process liveness — driven by
  // WebSocket connection state, not log message content.
  const renderMonitorStatus = () => {
    const chip = $("#monitor-status");
    if (!chip) return;
    if (!state.wsConnected) {
      chip.className = "status-chip status-err";
      chip.textContent = "● monitor: disconnected";
      chip.title = "The aimm process may have stopped. Reconnecting…";
    } else if (state.monitor && state.monitor.waiting_for_login) {
      chip.className = "status-chip status-warn";
      chip.textContent = "● monitor: waiting for Facebook login";
      chip.title = "Finish logging in (CAPTCHA or security code) in the Browser tab. Searches start once you are logged in.";
    } else if (state.monitor && state.monitor.paused) {
      chip.className = "status-chip status-warn";
      chip.textContent = "● monitor: stopped";
      chip.title = "The monitor is stopped. Click ▶ to start it again with the current configuration.";
    } else if (!state.lastActivity) {
      chip.className = "status-chip status-warn";
      chip.textContent = "● monitor: connected";
      chip.title = "Connected, waiting for first log message.";
    } else {
      const ago = Math.round(Date.now() / 1000 - state.lastActivity);
      if (ago > 300) {
        chip.className = "status-chip status-warn";
        chip.textContent = `● monitor: idle · ${formatAgo(state.lastActivity)}`;
        chip.title = "Connected but no activity for 5+ minutes.";
      } else {
        chip.className = "status-chip status-ok";
        chip.textContent = `● monitor: running · ${formatAgo(state.lastActivity)}`;
        chip.title = "Process is alive and active.";
      }
    }
  };

  // Error badge on the "Error" filter chip in the logs toolbar.
  const renderErrorBadge = () => {
    const errorChip = document.querySelector('.level-chips [data-level="ERROR"]');
    if (!errorChip) return;
    if (state.errorCount > 0) {
      errorChip.dataset.badge = state.errorCount;
      errorChip.classList.add("has-badge");
    } else {
      delete errorChip.dataset.badge;
      errorChip.classList.remove("has-badge");
    }
  };

  // Tick the "Xs ago" display once a second so it stays fresh even
  // without new log records.
  setInterval(renderMonitorStatus, 1000);

  // Paused, or waiting for the Facebook login: state the log stream does not carry.
  // One button: ⏸ stops the monitor; while stopped, ▶ starts it again, which reloads the
  // configuration and searches all items now.
  const renderPauseButton = () => {
    const btn = $("#run-btn");
    if (!btn || !state.monitor) return;
    const paused = state.monitor.paused;
    btn.textContent = paused ? "▶" : "⏸";
    btn.title = paused
      ? "Start the monitor: reload the configuration and search all items now"
      : "Stop the monitor after the current listing";
    btn.setAttribute("aria-label", paused ? "Start the monitor" : "Stop the monitor");
  };

  // While aimm waits for the Facebook login, say where to finish it; in Docker the
  // browser is only reachable through noVNC, so link straight to it.
  const renderLoginBanner = () => {
    const banner = $("#login-banner");
    if (!banner) return;
    const waiting = !!(state.monitor && state.monitor.waiting_for_login);
    banner.hidden = !waiting;
    if (!waiting) return;
    $("#login-banner-text").textContent = state.monitor.login_hint || "Waiting for the Facebook login.";
    const open = $("#login-banner-open");
    open.hidden = !state.vncEnabled;
    if (state.vncEnabled) open.href = buildVncUrl();
  };

  const refreshMonitorState = async () => {
    try {
      const res = await fetch("/api/status", { credentials: "same-origin" });
      if (!res.ok) return;
      const status = await res.json();
      state.monitor = status.monitor || null;
      state.vncEnabled = !!status.vnc_enabled;
      renderPauseButton();
      renderMonitorStatus();
      renderLoginBanner();
    } catch (_) {}
  };

  // Restart button — soft-restarts the monitor by touching the config.
  const wireClick = (sel, fn) => {
    const el = $(sel);
    if (el) el.addEventListener("click", fn);
    else console.warn("missing element:", sel);
  };
  wireClick("#run-btn", async () => {
    const btn = $("#run-btn");
    const resume = !!(state.monitor && state.monitor.paused);
    if (btn) btn.disabled = true;
    try {
      const res = await api(resume ? "/api/monitor/resume" : "/api/monitor/pause", { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || data.detail || res.statusText);
      state.monitor = {
        paused: data.paused,
        waiting_for_login: data.waiting_for_login,
        login_hint: data.login_hint,
      };
      renderPauseButton();
      renderMonitorStatus();
      setEditorStatus(
        resume
          ? "▶ Started: reloading the configuration and searching all items now…"
          : "⏸ Stopping: the monitor stops after the current listing.",
        "ok"
      );
    } catch (err) {
      setEditorStatus("⏸ " + err.message, "err");
    } finally {
      if (btn) btn.disabled = false;
    }
  });

  wireClick("#export-csv-btn", async () => {
    const btn = $("#export-csv-btn");
    if (btn) btn.disabled = true;
    try {
      const res = await api("/api/found.csv");
      if (!res.ok) {
        setEditorStatus("⬇ Export failed: " + res.status, "err");
        return;
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const stamp = new Date()
        .toISOString()
        .slice(0, 19)
        .replace(/[-:T]/g, "")
        .replace(/(\d{8})(\d{6})/, "$1-$2");
      const a = document.createElement("a");
      a.href = url;
      a.download = `found-items-${stamp}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setEditorStatus("⬇ Export failed: " + err.message, "err");
    } finally {
      if (btn) btn.disabled = false;
    }
  });

  // ---------------------------------------------------------------
  // Configure chat — JSON SetupUI over WebSocket
  // ---------------------------------------------------------------
  //
  // Before a chat, the pane shows a welcome card with the section picker and
  // a Start button; the composer appears only while a chat runs. A free-text
  // prompt of just "You" (the terminal's label for the user's turn) hands the
  // turn to the user without a bubble. Choice and yes/no buttons render inside
  // the question's bubble, and a typing indicator shows while aimm works.

  const CHAT_SECTIONS = [
    "ai", "marketplace", "item", "notification", "user", "region", "translation", "monitor",
  ];
  const USER_TURN_PROMPT = "You";
  const COMPOSER_MAX_HEIGHT = 160; // px, about 8 lines

  const chatScrollToEnd = () => {
    const container = $("#chat-messages");
    container.scrollTop = container.scrollHeight;
  };

  // A small, escape-first Markdown subset: paragraphs, "-"/"*"/"1." lists,
  // **bold** and `code`. Enough for aimm's summaries; anything else stays text.
  const renderInlineMarkdown = (text) =>
    esc(text)
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  const renderMarkdown = (text) => {
    // group consecutive lines into paragraphs, bullet lists and numbered lists
    const blocks = [];
    let current = null;
    const LIST_ITEM = { ul: /^\s*[-*]\s+/, ol: /^\s*\d+[.)]\s+/ };
    String(text)
      .split("\n")
      .forEach((line) => {
        if (!line.trim()) {
          current = null;
          return;
        }
        const tag = LIST_ITEM.ul.test(line) ? "ul" : LIST_ITEM.ol.test(line) ? "ol" : "p";
        const content = tag === "p" ? line.replace(/^#+\s+/, "") : line.replace(LIST_ITEM[tag], "");
        if (!current || current.tag !== tag) {
          current = { tag, lines: [] };
          blocks.push(current);
        }
        current.lines.push(renderInlineMarkdown(content));
      });
    return blocks
      .map(({ tag, lines }) =>
        tag === "p"
          ? `<p>${lines.join("<br>")}</p>`
          : `<${tag}>${lines.map((l) => `<li>${l}</li>`).join("")}</${tag}>`
      )
      .join("");
  };

  const appendChatMessage = (role, text, kind = "info", markdown = false) => {
    removeChatTyping();
    const row = document.createElement("div");
    row.className = `chat-message chat-${role} chat-${kind}`;
    if (markdown) {
      row.classList.add("chat-markdown");
      row.innerHTML = renderMarkdown(text);
    } else {
      row.textContent = text;
    }
    $("#chat-messages").appendChild(row);
    chatScrollToEnd();
    return row;
  };

  const showChatTyping = () => {
    if ($("#chat-messages .chat-typing")) return;
    const row = document.createElement("div");
    row.className = "chat-message chat-assistant chat-typing";
    row.setAttribute("aria-label", "aimm is working");
    row.innerHTML = "<span></span><span></span><span></span>";
    $("#chat-messages").appendChild(row);
    chatScrollToEnd();
  };
  function removeChatTyping() {
    const typing = $("#chat-messages .chat-typing");
    if (typing) typing.remove();
  }

  // The welcome card starts a chat; after a chat it offers a new one.
  const renderChatWelcome = (again = false) => {
    const old = $("#chat-messages .chat-welcome");
    if (old) old.remove();
    const card = document.createElement("div");
    card.className = "chat-welcome";
    card.innerHTML =
      (again
        ? ""
        : `<p>Chat with the configuration assistant to add a search, set up notifications, or change any setting. It edits your config file for you.</p>`) +
      `<label class="chat-welcome-section">Section ` +
      `<input id="chat-section" list="chat-section-options" type="text" placeholder="optional, e.g. item.ipad" autocomplete="off" />` +
      `</label>` +
      `<datalist id="chat-section-options">${CHAT_SECTIONS.map((s) => `<option value="${s}"></option>`).join("")}</datalist>` +
      `<button type="button" class="chat-start">${again ? "Start new chat" : "Start chat"}</button>`;
    card.querySelector(".chat-start").addEventListener("click", startConfigureChat);
    card.querySelector("#chat-section").addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        startConfigureChat();
      }
    });
    $("#chat-messages").appendChild(card);
    chatScrollToEnd();
  };

  // Composer: hidden outside a chat, and while a prompt takes buttons only.
  const resizeChatInput = () => {
    const input = $("#chat-input");
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, COMPOSER_MAX_HEIGHT)}px`;
  };
  const updateChatSend = () => {
    const prompt = state.chatPrompt;
    const hasText = $("#chat-input").value.trim() !== "";
    $("#chat-send").disabled = !prompt || (!hasText && !prompt.allowEmpty);
  };
  const setComposer = ({ visible, enabled = false, placeholder = "Message the assistant…", hint = false }) => {
    $("#chat-form").hidden = !visible;
    $("#chat-hint").hidden = !hint;
    const input = $("#chat-input");
    input.disabled = !enabled;
    input.placeholder = placeholder;
    updateChatSend();
    if (visible && enabled) input.focus();
  };

  const setChatActive = (active) => {
    state.chatActive = active;
    $("#chat-end").hidden = !active;
    $("#chat-end").disabled = false;
    if (!active) {
      $("#chat-scope").textContent = "";
      setComposer({ visible: false });
    }
  };

  const clearChatPrompt = () => {
    state.chatPrompt = null;
    // buttons of an answered (or abandoned) question stay visible but inert
    $$("#chat-messages .chat-option").forEach((btn) => (btn.disabled = true));
  };

  const sendChatAnswer = (value, label, chosen = null) => {
    if (!state.chatWs || state.chatWs.readyState !== WebSocket.OPEN) return;
    state.chatWs.send(JSON.stringify({ type: "answer", value }));
    if (chosen) chosen.classList.add("chosen");
    clearChatPrompt();
    appendChatMessage("user", label);
    const input = $("#chat-input");
    input.value = "";
    resizeChatInput();
    setComposer({ visible: true, enabled: false, placeholder: "aimm is working…" });
    showChatTyping();
  };

  const defaultLabel = (msg) => {
    if (msg.prompt_type === "confirm") return msg.default === false ? "No" : "Yes";
    if (msg.default === null || msg.default === undefined || msg.default === "") return null;
    const option = (msg.options || []).find((o) => o.value === msg.default);
    return option ? option.label || option.value : String(msg.default);
  };

  const renderChatPrompt = (msg) => {
    removeChatTyping();
    const defLabel = defaultLabel(msg);
    const userTurn = msg.prompt_type === "text" && msg.prompt === USER_TURN_PROMPT;
    // an empty answer takes the default, even an empty one ("Press Enter to
    // try again"); on the user's own turn it would say nothing
    const allowEmpty = !userTurn && msg.default !== null && msg.default !== undefined;
    state.chatPrompt = { ...msg, allowEmpty, defaultLabel: defLabel ?? "(Enter)" };
    let buttons = [];
    if (msg.prompt_type === "choice") {
      buttons = (msg.options || []).map((o) => ({ value: o.value, label: o.label || o.value, hint: o.hint }));
    } else if (msg.prompt_type === "confirm") {
      buttons = [{ value: true, label: "Yes" }, { value: false, label: "No" }];
    }

    if (!userTurn) {
      const bubble = appendChatMessage("assistant", msg.prompt, "prompt");
      if (buttons.length) {
        const options = document.createElement("div");
        options.className = "chat-options";
        buttons.forEach((option) => {
          const btn = document.createElement("button");
          btn.type = "button";
          btn.className = "chat-option";
          btn.textContent = option.label;
          if (option.hint) btn.title = option.hint;
          btn.addEventListener("click", () => sendChatAnswer(option.value, option.label, btn));
          options.appendChild(btn);
        });
        bubble.appendChild(options);
        chatScrollToEnd();
      }
    }

    if (msg.prompt_type === "choice" && !msg.allow_text) {
      setComposer({ visible: false, hint: true });
      return;
    }
    const placeholder = defLabel
      ? `Message the assistant… (Enter for “${defLabel}”)`
      : allowEmpty
        ? "Press Enter to continue…"
        : buttons.length
        ? "Pick an option above, or type an answer…"
        : "Message the assistant…";
    setComposer({ visible: true, enabled: true, placeholder });
  };

  const reloadConfigAfterChat = async () => {
    const dirty = state.currentContent !== state.originalContent;
    if (dirty && !confirm("Reload the config file and discard unsaved editor changes?")) {
      return;
    }
    await loadConfig();
  };

  // the chat is over (finished, ended, or disconnected): offer a new one
  const finishChat = (text, kind) => {
    removeChatTyping();
    if (text) appendChatMessage("system", text, kind);
    clearChatPrompt();
    setChatActive(false);
    state.chatWs = null;
    renderChatWelcome(true);
  };

  function startConfigureChat() {
    if (state.chatWs) state.chatWs.close();
    const sectionInput = $("#chat-section");
    const section = sectionInput ? sectionInput.value.trim() : "";
    state.chatPrompt = null;
    $("#chat-messages").innerHTML = "";
    setChatActive(true);
    $("#chat-scope").textContent = section;
    setComposer({ visible: true, enabled: false, placeholder: "Connecting…" });
    showChatTyping();

    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const suffix = section ? `?section=${encodeURIComponent(section)}` : "";
    const ws = new WebSocket(`${proto}//${location.host}/ws/configure${suffix}`);
    state.chatWs = ws;

    ws.onmessage = async (ev) => {
      if (state.chatWs !== ws) return;
      const msg = JSON.parse(ev.data);
      if (msg.type === "message") {
        appendChatMessage("assistant", msg.text, msg.kind || "info", !!msg.markdown || msg.kind === "assistant");
      } else if (msg.type === "prompt") {
        renderChatPrompt(msg);
      } else if (msg.type === "config_saved") {
        // the session wrote the config file; show it while the chat continues
        await reloadConfigAfterChat();
      } else if (msg.type === "done") {
        const ok = msg.exit_code === 0;
        finishChat(msg.cancelled ? "Chat ended." : ok ? "Finished." : "Stopped with errors.", ok ? "success" : "error");
      }
    };
    ws.onclose = () => {
      if (state.chatWs !== ws) return;
      finishChat("Disconnected.", "warning");
    };
    ws.onerror = () => {
      if (state.chatWs !== ws) return;
      appendChatMessage("system", "Connection error.", "error");
      ws.close();
    };
  }

  const endConfigureChat = () => {
    const ws = state.chatWs;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "cancel" }));
      $("#chat-end").disabled = true; // until the server confirms the chat ended
      clearChatPrompt();
      setComposer({ visible: false });
      showChatTyping();
      setTimeout(() => {
        if (state.chatWs === ws && ws.readyState === WebSocket.OPEN) {
          ws.close();
        }
      }, 3000);
      return;
    }
    if (ws) {
      ws.close();
    }
  };

  wireClick("#chat-end", endConfigureChat);
  $("#chat-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const prompt = state.chatPrompt;
    if (!prompt) return;
    const value = $("#chat-input").value.trim();
    if (!value && !prompt.allowEmpty) return;
    sendChatAnswer(value, value || prompt.defaultLabel);
  });
  $("#chat-input").addEventListener("keydown", (e) => {
    // Enter sends, Shift+Enter adds a line; never send mid-IME composition
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing && e.keyCode !== 229) {
      e.preventDefault();
      $("#chat-form").requestSubmit();
    }
  });
  $("#chat-input").addEventListener("input", () => {
    resizeChatInput();
    updateChatSend();
  });
  renderChatWelcome();

  // ---------------------------------------------------------------
  // Sections sidebar (AI-assisted edit / delete / add)
  // ---------------------------------------------------------------
  //
  // The backend ships a list of section headers found in the file.
  // We render them in a sidebar with a ⋯ menu per section. Clicking
  // the section name scrolls the textarea to that section. No pixel
  // measurement of the textarea is needed.

  state.sections = [];

  const SECTION_HEADER_RE = /^\s*\[([^\]\n]+)\]\s*$/;

  const scanSectionsClient = (text) => {
    const lines = text.split("\n");
    const headers = [];
    for (let i = 0; i < lines.length; i++) {
      const m = lines[i].match(SECTION_HEADER_RE);
      if (m) headers.push({ lineIdx: i, name: m[1].trim() });
    }
    return headers.map((h, i) => {
      const dot = h.name.indexOf(".");
      const lineEnd = i + 1 < headers.length ? headers[i + 1].lineIdx : lines.length;
      return {
        name: h.name,
        prefix: dot >= 0 ? h.name.slice(0, dot) : h.name,
        suffix: dot >= 0 ? h.name.slice(dot + 1) : "",
        line_start: h.lineIdx,
        line_end: lineEnd,
      };
    });
  };

  // -------- Thin gutter with ⋯ buttons aligned to section headers --------

  const getLineMetrics = () => {
    if (editor.defaultTextHeight) {
      // CodeMirror path
      const lineHeight = editor.defaultTextHeight();
      const scrollInfo = editor.getScrollInfo();
      return { lineHeight, paddingTop: 0, scrollHeight: scrollInfo.height };
    }
    // Fallback textarea path
    const el = editorHost.querySelector("textarea");
    if (!el) return { lineHeight: 20, paddingTop: 0, scrollHeight: 0 };
    const cs = window.getComputedStyle(el);
    const lineHeight = parseFloat(cs.lineHeight) || parseFloat(cs.fontSize) * 1.55;
    const paddingTop = parseFloat(cs.paddingTop) || 0;
    return { lineHeight, paddingTop, scrollHeight: el.scrollHeight };
  };

  const renderGutter = () => {
    const inner = $("#gutter-inner");
    if (!inner) return;
    inner.innerHTML = "";
    const { lineHeight, paddingTop, scrollHeight } = getLineMetrics();
    // Match gutter height to editor scroll height so the transform
    // range is correct.
    inner.style.height = scrollHeight + "px";

    state.sections.forEach((section) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "section-btn";
      btn.innerHTML = "⋯";
      btn.title = `[${section.name}]`;
      btn.style.top = (paddingTop + lineHeight * section.line_start) + "px";
      btn.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        toggleSectionMenu(section, btn);
      });
      inner.appendChild(btn);
    });
  };

  // Sync gutter scroll position with the editor.
  const syncGutter = () => {
    const inner = $("#gutter-inner");
    if (inner) inner.style.transform = `translateY(${-editor.getScrollInfo().top}px)`;
  };
  if (editor.on) {
    editor.on("scroll", syncGutter);
    editor.on("change", () => {
      if (refreshSectionsFromBuffer._t) clearTimeout(refreshSectionsFromBuffer._t);
      refreshSectionsFromBuffer._t = setTimeout(refreshSectionsFromBuffer, 150);
    });
  }

  // Re-scan sections from the buffer after edits (debounced).
  const refreshSectionsFromBuffer = () => {
    state.sections = scanSectionsClient(editor.getValue());
    renderGutter();
  };

  // -------- Popover menu (Edit / Delete / Add another) --------

  const closeSectionMenus = () => {
    document.querySelectorAll(".section-menu").forEach((m) => m.remove());
  };

  const toggleSectionMenu = (section, btn) => {
    const existing = document.querySelector(".section-menu");
    if (existing && existing.dataset.section === section.name) {
      existing.remove();
      return;
    }
    closeSectionMenus();

    const menu = document.createElement("div");
    menu.className = "section-menu";
    menu.dataset.section = section.name;

    // Position relative to the button using viewport coordinates
    // (position: fixed in CSS) so the menu can escape the sidebar's
    // overflow clip.
    const rect = btn.getBoundingClientRect();
    menu.style.top = rect.bottom + 4 + "px";
    menu.style.left = rect.left + "px";

    const addMenuItem = (label, handler, cls = "") => {
      const item = document.createElement("button");
      item.type = "button";
      item.textContent = label;
      if (cls) item.className = cls;
      item.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        closeSectionMenus();
        handler();
      });
      menu.appendChild(item);
    };

    addMenuItem("Edit", () => openEditSectionModal(section.name));
    addMenuItem("Duplicate", () => duplicateSection(section));
    const sep = document.createElement("div");
    sep.className = "menu-sep";
    menu.appendChild(sep);
    addMenuItem("Delete", () => deleteSection(section), "danger");

    document.body.appendChild(menu);
  };

  // Close popovers when clicking anywhere else.
  document.addEventListener("click", (e) => {
    if (!e.target.closest(".section-btn") && !e.target.closest(".section-menu")) {
      closeSectionMenus();
    }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeSectionMenus();
  });

  // -------- Delete section (pure client-side string op) --------

  const deleteSection = (section) => {
    const lines = editor.getValue().split("\n");
    let start = section.line_start;
    let end = section.line_end; // exclusive

    const preview = lines.slice(start, end).filter((l) => l.trim()).join("\n");
    const ok = confirm(
      `Delete [${section.name}] ?\n\n` +
        preview +
        "\n\nThis only updates the editor buffer — click Save to commit."
    );
    if (!ok) return;

    // If there's a blank line right before this section, consume it
    // too so we don't leave a double blank.
    if (start > 0 && lines[start - 1].trim() === "") {
      start--;
    }
    const next = lines.slice(0, start).concat(lines.slice(end)).join("\n");
    editor.setValue(next);
    state.currentContent = next;
    const dirty = state.currentContent !== state.originalContent;
    $("#save-btn").disabled = !dirty;
    setEditorStatus(
      `Deleted [${section.name}] — review and click Save to commit.`,
      "ok"
    );
    refreshSectionsFromBuffer();
  };

  // -------- Duplicate section --------
  // Opens the Add form pre-populated with the original section's values
  // and a unique auto-generated name.

  const duplicateSection = (section) => {
    const schema = findFormSchema(section.name);
    if (!schema) {
      alert(`No form defined for [${section.name}] — duplicate manually in the TOML editor.`);
      return;
    }

    // Get the original fields (server-provided or client-parsed).
    let fields = (section && section.fields) || {};
    if (!Object.keys(fields).length && window.tomlEdit) {
      try {
        const parsed = window.tomlEdit.parse(state.currentContent);
        const parts = section.name.split(".");
        let node = parsed;
        for (const p of parts) { node = node && node[p]; }
        if (node && typeof node === "object") fields = node;
      } catch (err) { /* fall through with empty fields */ }
    }

    // Generate a unique suffix: append 1, 2, 3…
    const existingNames = new Set(state.sections.map((s) => s.name));
    let newSuffix = section.suffix;
    let i = 1;
    while (existingNames.has(`${section.prefix}.${newSuffix}`)) {
      newSuffix = section.suffix + i;
      i++;
    }

    formContext = {
      sectionName: `${section.prefix}.__new__`,
      fields,
      schema,
      addMode: true,
      addPrefix: section.prefix,
      nameValue: newSuffix,
    };
    activeTab = "left";
    $("#form-modal-title").textContent = `Duplicate [${section.name}]`;
    $("#form-modal-hint").hidden = false;
    $("#form-modal-hint").textContent =
      "Review the values copied from the original section, change what you need, and save.";
    renderForm(schema, fields);
    formModal.open();
    setTimeout(() => $("#add-section-name").focus(), 50);
  };

  // ---------------------------------------------------------------
  // Section form modal (placeholder — full form rendering coming next)
  // ---------------------------------------------------------------
  //
  // The ⋯ menu wires Edit / Add another to the two functions below.
  // For now they pop a minimal placeholder modal so the page doesn't
  // crash. The form-rendering engine that uses toml-edit-js will be
  // wired here in the next iteration.

  // ---------------------------------------------------------------
  // Form-based section editor using toml-edit-js
  // ---------------------------------------------------------------

  // Form field schema definitions per section type. Each field:
  //   key       — TOML key name
  //   label     — display name
  //   type      — "text" | "password" | "number" | "select" | "textarea"
  //   options   — for select: [{value, label}, ...]
  //   required  — boolean
  //   help      — tooltip / small hint
  //   group     — optional group header (for visual grouping)
  //   advanced  — if true, hidden by default

  const BUILT_IN_REGIONS = [
    "usa", "usa_full", "can", "mex", "bra", "arg",
    "aus", "aus_miles", "nzl", "ind", "gbr", "fra", "spa",
  ];

  // override: true means this field can also be set per-item in [item.*]
  // to override the marketplace default.
  const OV = "Can be overridden per-item in [item.*] sections.";

  const CATEGORIES = [
    { value: "", label: "(any)" },
    { value: "vehicles", label: "Vehicles" },
    { value: "propertyrentals", label: "Property rentals" },
    { value: "apparel", label: "Apparel" },
    { value: "electronics", label: "Electronics" },
    { value: "entertainment", label: "Entertainment" },
    { value: "family", label: "Family" },
    { value: "freestuff", label: "Free stuff" },
    { value: "free", label: "Free" },
    { value: "garden", label: "Garden" },
    { value: "hobbies", label: "Hobbies" },
    { value: "homegoods", label: "Home goods" },
    { value: "homeimprovement", label: "Home improvement" },
    { value: "homesales", label: "Home sales" },
    { value: "musicalinstruments", label: "Musical instruments" },
    { value: "officesupplies", label: "Office supplies" },
    { value: "petsupplies", label: "Pet supplies" },
    { value: "sportinggoods", label: "Sporting goods" },
    { value: "tickets", label: "Tickets" },
    { value: "toys", label: "Toys" },
    { value: "videogames", label: "Video games" },
  ];

  const FORM_SCHEMAS = {
    "marketplace.facebook": [
      // ---- Left column: Facebook-specific ----
      { key: "username", label: "Facebook username (email)", type: "text", column: "left",
        help: "Your Facebook login email." },
      { key: "password", label: "Facebook password", type: "password", column: "left",
        help: "Leave blank to keep the current password." },
      { key: "login_wait_time", label: "Login wait time (seconds)", type: "number", column: "left",
        help: "Seconds to wait after Facebook login for 2FA / captcha. Default: 60." },
      { key: "language", label: "Language", type: "text", column: "left", advanced: true,
        help: "Non-English Facebook locale — must match a [translation.*] section." },

      // ---- Right column: Shared — can be overridden per-item ----
      { key: "search_city", label: "Search city", type: "text", required: true, column: "right",
        help: "City code from the Facebook Marketplace URL (lowercase, e.g. 'houston')." },
      { key: "search_region", label: "Search region", type: "select", column: "right",
        options: [{ value: "", label: "(none)" }].concat(
          BUILT_IN_REGIONS.map((r) => ({ value: r, label: r }))
        ),
        help: "Pre-defined region (expands to multiple cities)." },

      // ---- Filters (advanced, overridable) ----
      { key: "category", label: "Category", type: "select", group: "Filters", advanced: true, column: "right",
        options: CATEGORIES, help: "Marketplace listing category." },
      { key: "condition", label: "Condition", type: "checkboxes", advanced: true, column: "right",
        options: [
          { value: "new", label: "New" },
          { value: "used_like_new", label: "Used — like new" },
          { value: "used_good", label: "Used — good" },
          { value: "used_fair", label: "Used — fair" },
        ],
        help: "Filter by item condition. " + OV },
      { key: "availability", label: "Availability", type: "checkboxes", advanced: true, column: "right",
        options: [
          { value: "all", label: "All" },
          { value: "in", label: "In stock" },
          { value: "out", label: "Out of stock" },
        ] },
      { key: "date_listed", label: "Date listed", type: "checkboxes", advanced: true, column: "right",
        options: [
          { value: "1", label: "Last 24 hours" },
          { value: "7", label: "Last 7 days" },
          { value: "30", label: "Last 30 days" },
        ] },
      { key: "delivery_method", label: "Delivery method", type: "checkboxes", advanced: true, column: "right",
        options: [
          { value: "local_pick_up", label: "Local pick-up" },
          { value: "shipping", label: "Shipping" },
        ] },
      { key: "seller_locations", label: "Seller locations", type: "text", advanced: true, column: "right",
        help: "Comma-separated location names to filter by." },
      { key: "exclude_sellers", label: "Exclude sellers", type: "text", advanced: true, column: "right",
        help: "Comma-separated seller names to skip." },
      { key: "keywords", label: "Keywords (include)", type: "text", advanced: true, column: "right",
        help: "Boolean expression, e.g. 'drone AND (DJI OR Orqa)'" },
      { key: "antikeywords", label: "Anti-keywords (exclude)", type: "text", advanced: true, column: "right",
        help: "Boolean expression for exclusion." },

      // ---- Pricing ----
      { key: "min_price", label: "Min price", type: "text", group: "Pricing", advanced: true, column: "right",
        help: "e.g. '50' or '50 USD'" },
      { key: "max_price", label: "Max price", type: "text", advanced: true, column: "right",
        help: "e.g. '300' or '300 USD'" },

      // ---- Location ----
      { key: "radius", label: "Search radius (km)", type: "text", group: "Location", advanced: true, column: "right",
        help: "Comma-separated radius per city (must match search_city count)." },
      { key: "currency", label: "Currency", type: "text", advanced: true, column: "right",
        help: "Comma-separated currency code per city, e.g. 'USD, CAD'." },

      // ---- AI evaluation ----
      { key: "ai", label: "AI backends", type: "text", group: "AI evaluation", advanced: true, column: "right",
        help: "Comma-separated [ai.*] names." },
      { key: "rating", label: "AI rating threshold", type: "text", advanced: true, column: "right",
        help: "1–5 (or two values: initial, subsequent)." },
      { key: "prompt", label: "AI prompt", type: "textarea", advanced: true, column: "right",
        help: "Custom evaluation prompt (replaces default)." },
      { key: "extra_prompt", label: "Extra prompt", type: "textarea", advanced: true, column: "right",
        help: "Additional text appended before the rating prompt." },
      { key: "rating_prompt", label: "Rating prompt", type: "textarea", advanced: true, column: "right",
        help: "Custom rating instructions (replaces default 1–5 scale)." },

      // ---- Notification ----
      { key: "notify", label: "Notify users", type: "text", group: "Notification", advanced: true, column: "right",
        help: "Comma-separated [user.*] names. Default: all users." },

      // ---- Schedule ----
      { key: "search_interval", label: "Search interval", type: "text", group: "Schedule", advanced: true, column: "right",
        help: "Duration, e.g. '30m', '1h'. Default: 30 min." },
      { key: "max_search_interval", label: "Max search interval", type: "text", advanced: true, column: "right",
        help: "Upper bound for random interval jitter. Default: 150% of search interval." },
      { key: "start_at", label: "Start at", type: "text", advanced: true, column: "right",
        help: "Comma-separated time patterns: 'HH:MM', '*:MM', '*:*:SS'." },
    ],

    // ---- Item form ----
    // Matched by prefix "item" — see the lookup logic below.
    "item.*": [
      // Left: item-specific
      { key: "search_phrases", label: "Search phrases", type: "text", required: true, column: "left",
        help: "Comma-separated. e.g. 'gopro hero 11, gopro hero 12'" },
      { key: "description", label: "Description (helps AI)", type: "textarea", column: "left",
        help: "Free-text description of what you want. The AI uses this to evaluate listings." },
      { key: "marketplace", label: "Marketplace", type: "text", column: "left", advanced: true,
        help: "Which [marketplace.*] to search. Default: first defined marketplace." },

      // Right: overrides from marketplace defaults
      { key: "search_city", label: "Search city", type: "text", column: "right",
        help: "Override marketplace's search city for this item." },
      { key: "search_region", label: "Search region", type: "select", column: "right",
        options: [{ value: "", label: "(inherit from marketplace)" }].concat(
          BUILT_IN_REGIONS.map((r) => ({ value: r, label: r }))
        ) },
      { key: "min_price", label: "Min price", type: "text", column: "right",
        help: "e.g. '50' or '50 USD'" },
      { key: "max_price", label: "Max price", type: "text", column: "right",
        help: "e.g. '300' or '300 USD'" },
      { key: "category", label: "Category", type: "select", column: "right", advanced: true,
        options: CATEGORIES },
      { key: "condition", label: "Condition", type: "checkboxes", column: "right", advanced: true,
        options: [
          { value: "new", label: "New" },
          { value: "used_like_new", label: "Used — like new" },
          { value: "used_good", label: "Used — good" },
          { value: "used_fair", label: "Used — fair" },
        ] },
      { key: "availability", label: "Availability", type: "checkboxes", column: "right", advanced: true,
        options: [
          { value: "all", label: "All" },
          { value: "in", label: "In stock" },
          { value: "out", label: "Out of stock" },
        ] },
      { key: "date_listed", label: "Date listed", type: "checkboxes", column: "right", advanced: true,
        options: [
          { value: "1", label: "Last 24 hours" },
          { value: "7", label: "Last 7 days" },
          { value: "30", label: "Last 30 days" },
        ] },
      { key: "delivery_method", label: "Delivery method", type: "checkboxes", column: "right", advanced: true,
        options: [
          { value: "local_pick_up", label: "Local pick-up" },
          { value: "shipping", label: "Shipping" },
        ] },
      { key: "keywords", label: "Keywords (include)", type: "text", column: "right", advanced: true,
        help: "Boolean expression, e.g. 'drone AND (DJI OR Orqa)'" },
      { key: "antikeywords", label: "Anti-keywords (exclude)", type: "text", column: "right", advanced: true },
      { key: "seller_locations", label: "Seller locations", type: "text", column: "right", advanced: true,
        help: "Comma-separated." },
      { key: "exclude_sellers", label: "Exclude sellers", type: "text", column: "right", advanced: true },
      { key: "notify", label: "Notify users", type: "text", column: "right", advanced: true,
        help: "Comma-separated [user.*] names. Default: inherit from marketplace." },
      { key: "ai", label: "AI backends", type: "text", group: "AI", column: "right", advanced: true },
      { key: "rating", label: "AI rating threshold", type: "text", column: "right", advanced: true,
        help: "1–5 (or initial,subsequent)." },
      { key: "prompt", label: "AI prompt", type: "textarea", column: "right", advanced: true },
      { key: "extra_prompt", label: "Extra prompt", type: "textarea", column: "right", advanced: true },
      { key: "rating_prompt", label: "Rating prompt", type: "textarea", column: "right", advanced: true },
      { key: "search_interval", label: "Search interval", type: "text", group: "Schedule", column: "right", advanced: true,
        help: "Duration, e.g. '30m', '1h'." },
      { key: "max_search_interval", label: "Max search interval", type: "text", column: "right", advanced: true },
      { key: "start_at", label: "Start at", type: "text", column: "right", advanced: true,
        help: "Comma-separated time patterns." },
    ],

    // ---- User form ----
    "user.*": [
      { key: "pushbullet_token", label: "Pushbullet token", type: "password",
        help: "Get your token from pushbullet.com → Settings → Access tokens." },
      { key: "pushover_user_key", label: "Pushover user key", type: "password", group: "Pushover" },
      { key: "pushover_api_token", label: "Pushover API token", type: "password" },
      { key: "telegram_token", label: "Telegram bot token", type: "password", group: "Telegram",
        help: "Format: 123456789:ABCdef..." },
      { key: "telegram_chat_id", label: "Telegram chat ID", type: "text",
        help: "Numeric ID or @username." },
      { key: "ntfy_server", label: "ntfy server URL", type: "text", group: "ntfy",
        help: "e.g. https://ntfy.sh" },
      { key: "ntfy_topic", label: "ntfy topic", type: "text" },
      { key: "unitysvc_api_key", label: "UnitySVC API key", type: "password", group: "UnitySVC",
        help: "Your svcpass_ key, or ${UNITYSVC_API_KEY}." },
      { key: "unitysvc_service", label: "UnitySVC service", type: "text", advanced: true,
        help: "Default: notify (inbox plus your saved destination), or e.g. labs/msg-to-discord." },
      { key: "email", label: "Email address", type: "text", group: "Email",
        help: "Comma-separated list of recipient addresses." },
      { key: "smtp_server", label: "SMTP server", type: "text", advanced: true },
      { key: "smtp_port", label: "SMTP port", type: "number", advanced: true,
        help: "Default: 587" },
      { key: "smtp_username", label: "SMTP username", type: "text", advanced: true },
      { key: "smtp_password", label: "SMTP password (app password)", type: "password", advanced: true },
      { key: "smtp_from", label: "SMTP from address", type: "text", advanced: true },
      { key: "notify_with", label: "Notification sections", type: "text", group: "Other", advanced: true,
        help: "Comma-separated [notification.*] section names for shared credentials." },
      { key: "remind", label: "Remind interval", type: "text", advanced: true,
        help: "Resend after this interval, e.g. '1d', '6h'. Default: one-time." },
    ],

    // ---- AI backend form ----
    "ai.*": [
      { key: "api_key", label: "API key", type: "password",
        help: "If left blank, the env var for the provider is used (e.g. ${OPENAI_API_KEY}, ${ANTHROPIC_API_KEY}, ${DEEPSEEK_API_KEY})." },
      { key: "model", label: "Model", type: "text",
        help: "e.g. 'gpt-4o', 'deepseek-chat', 'deepseek-r1:14b', 'claude-sonnet-5-5'" },
      { key: "provider", label: "Provider override", type: "text", advanced: true,
        help: "Override the provider (auto-detected from section name). Only needed for custom OpenAI-compatible endpoints." },
      { key: "base_url", label: "Base URL", type: "text", advanced: true,
        help: "Custom API endpoint. Required for Ollama (e.g. http://localhost:11434/v1)." },
      { key: "timeout", label: "Timeout (seconds)", type: "number", advanced: true },
      { key: "max_retries", label: "Max retries", type: "number", advanced: true,
        help: "Default: 10" },
    ],
  };

  // Look up a schema for a section name. Exact match first, then
  // prefix-wildcard (e.g. "item.gopro" → "item.*").
  const findFormSchema = (sectionName) => {
    if (FORM_SCHEMAS[sectionName]) return FORM_SCHEMAS[sectionName];
    const dot = sectionName.indexOf(".");
    if (dot >= 0) {
      const wildcard = sectionName.slice(0, dot) + ".*";
      if (FORM_SCHEMAS[wildcard]) return FORM_SCHEMAS[wildcard];
    }
    return null;
  };

  // Tracks which section is currently being edited.
  let formContext = { sectionName: "", fields: {}, schema: [] };
  let showAdvanced = false;

  const formModal = {
    el: () => $("#form-modal"),
    open() { this.el().classList.remove("hidden"); },
    close() {
      this.el().classList.add("hidden");
      $("#form-error").hidden = true;
      const form = $("#section-form");
      if (form) form.innerHTML = "";
    },
  };

  // Which tab is selected (for two-tab forms).
  let activeTab = "left";

  // Render form fields into #section-form.
  const renderForm = (schema, fields) => {
    const form = $("#section-form");
    form.innerHTML = "";

    // Always render the section name field first. In edit mode it shows
    // the current suffix (editable for rename); in add/duplicate mode
    // it shows the suggested new name.
    const currentPrefix = formContext.addMode ? formContext.addPrefix : formContext.sectionName.split(".")[0];
    // For AI sections, show a dropdown of known providers instead of a
    // free-text name input.
    const aiAutoName = currentPrefix === "ai";
    const nameWrapper = document.createElement("div");
    nameWrapper.className = "form-field";
    const currentSuffix = formContext.nameValue ??
      (formContext.addMode ? "" : (formContext.sectionName.split(".").slice(1).join(".") || formContext.sectionName));
    if (aiAutoName) {
      const aiProviders = [
        { value: "openai", label: "OpenAI" },
        { value: "deepseek", label: "DeepSeek" },
        { value: "anthropic", label: "Anthropic" },
        { value: "ollama", label: "Ollama" },
      ];
      const opts = aiProviders.map((p) =>
        `<option value="${p.value}" ${currentSuffix === p.value ? "selected" : ""}>${p.label}</option>`
      ).join("");
      nameWrapper.innerHTML =
        `<label class="form-label">AI Provider <span class="required">*</span></label>` +
        `<select id="add-section-name">${opts}</select>` +
        `<p class="form-help">[ai.<em>provider</em>]</p>`;
      const nameSelect = nameWrapper.querySelector("select");
      nameSelect.addEventListener("change", () => { formContext.nameValue = nameSelect.value; });
      // Set initial value.
      if (!currentSuffix) {
        formContext.nameValue = nameSelect.value;
      }
    } else {
      nameWrapper.innerHTML =
        `<label class="form-label">Section name <span class="required">*</span></label>` +
        `<input type="text" id="add-section-name" value="${esc(currentSuffix)}" ` +
        `placeholder="e.g. gopro, me" />` +
        `<p class="form-help">[${esc(currentPrefix)}.<em>name</em>]</p>`;
      const nameInput = nameWrapper.querySelector("input");
      nameInput.addEventListener("input", () => { formContext.nameValue = nameInput.value; });
    }
    form.appendChild(nameWrapper);

    const hasColumns = schema.some((f) => f.column);
    const hasAdvanced = schema.some((f) => f.advanced);

    // If the schema uses columns, render tabs.
    if (hasColumns) {
      // Choose tab labels based on what kind of section we're editing.
      const prefix = formContext.sectionName.split(".")[0];
      const leftLabel =
        prefix === "marketplace" ? "Facebook Login" : "Item Settings";
      const rightLabel =
        prefix === "marketplace"
          ? "Search Defaults (overridable per item)"
          : "Override Marketplace Defaults";

      const tabBar = document.createElement("div");
      tabBar.className = "form-tab-bar";
      const leftBtn = document.createElement("button");
      leftBtn.type = "button";
      leftBtn.className = "form-tab" + (activeTab === "left" ? " active" : "");
      leftBtn.textContent = leftLabel;
      leftBtn.addEventListener("click", () => { activeTab = "left"; renderForm(schema, fields); });
      const rightBtn = document.createElement("button");
      rightBtn.type = "button";
      rightBtn.className = "form-tab" + (activeTab === "right" ? " active" : "");
      rightBtn.textContent = rightLabel;
      rightBtn.addEventListener("click", () => { activeTab = "right"; renderForm(schema, fields); });
      tabBar.appendChild(leftBtn);
      tabBar.appendChild(rightBtn);
      form.appendChild(tabBar);
    }

    // Toggle for advanced fields.
    const visibleFields = hasColumns
      ? schema.filter((f) => (f.column || "left") === activeTab)
      : schema;
    const tabHasAdvanced = visibleFields.some((f) => f.advanced);
    if (tabHasAdvanced) {
      const toggle = document.createElement("label");
      toggle.className = "form-label";
      toggle.style.cursor = "pointer";
      toggle.innerHTML =
        `<input type="checkbox" id="show-advanced" ${showAdvanced ? "checked" : ""} /> ` +
        `Show advanced fields`;
      toggle.querySelector("input").addEventListener("change", (e) => {
        showAdvanced = e.target.checked;
        renderForm(schema, fields);
      });
      form.appendChild(toggle);
    }

    let lastGroup = null;
    visibleFields.forEach((fieldDef) => {
      if (fieldDef.advanced && !showAdvanced) return;

      // Group header.
      if (fieldDef.group && fieldDef.group !== lastGroup) {
        lastGroup = fieldDef.group;
        const groupEl = document.createElement("div");
        groupEl.className = "form-group-title";
        groupEl.textContent = fieldDef.group;
        form.appendChild(groupEl);
      }

      const wrapper = document.createElement("div");
      wrapper.className = "form-field";

      const label = document.createElement("label");
      label.className = "form-label";
      label.innerHTML =
        esc(fieldDef.label) +
        (fieldDef.required
          ? ' <span class="required">*</span>'
          : ' <span class="optional">optional</span>');
      wrapper.appendChild(label);

      let input;
      const rawVal = fields[fieldDef.key];
      // Flatten arrays to comma-separated for text fields.
      const currentVal =
        Array.isArray(rawVal) ? rawVal.join(", ") : rawVal ?? "";
      // For checkboxes, track which values are currently selected.
      const checkedSet = new Set(
        Array.isArray(rawVal) ? rawVal.map(String) : currentVal ? [String(currentVal)] : []
      );

      if (fieldDef.type === "checkboxes") {
        // Render a group of checkboxes for multi-value fields.
        input = document.createElement("div");
        input.className = "checkboxes";
        input.dataset.key = fieldDef.key;
        (fieldDef.options || []).forEach((opt) => {
          const cb = document.createElement("input");
          cb.type = "checkbox";
          cb.value = opt.value;
          cb.checked = checkedSet.has(String(opt.value));
          cb.id = `field-${fieldDef.key}-${opt.value}`;
          const lbl = document.createElement("label");
          lbl.htmlFor = cb.id;
          lbl.appendChild(cb);
          lbl.append(` ${opt.label}`);
          input.appendChild(lbl);
        });
      } else if (fieldDef.type === "select") {
        input = document.createElement("select");
        (fieldDef.options || []).forEach((opt) => {
          const o = document.createElement("option");
          o.value = opt.value;
          o.textContent = opt.label;
          if (String(currentVal) === String(opt.value)) o.selected = true;
          input.appendChild(o);
        });
      } else if (fieldDef.type === "textarea") {
        input = document.createElement("textarea");
        input.rows = 3;
        input.value = currentVal;
      } else {
        input = document.createElement("input");
        input.type = fieldDef.type || "text";
        // A ${VAR} reference is not a secret (the secret is in the environment
        // variable), so show it as text: the user can see which variable is used.
        if (fieldDef.type === "password" && /^\$\{[A-Za-z_][A-Za-z0-9_]*\}$/.test(String(currentVal))) {
          input.type = "text";
        }
        // For password fields with <REDACTED>, show placeholder instead.
        if (fieldDef.type === "password" && String(currentVal) === "<REDACTED>") {
          input.value = "";
          input.placeholder = "(unchanged — leave blank to keep current)";
        } else {
          input.value = currentVal;
        }
        if (fieldDef.type === "number") {
          input.min = "0";
          input.step = "1";
        }
      }
      if (fieldDef.type !== "checkboxes") {
        input.name = fieldDef.key;
        input.dataset.key = fieldDef.key;
        label.htmlFor = fieldDef.key;
        input.id = "field-" + fieldDef.key;
      }
      wrapper.appendChild(input);

      if (fieldDef.help) {
        const help = document.createElement("p");
        help.className = "form-help";
        help.textContent = fieldDef.help;
        wrapper.appendChild(help);
      }
      form.appendChild(wrapper);
    });

    // For AI sections in add mode, set the API key to the env var
    // reference matching the selected provider.
    if (aiAutoName && formContext.addMode) {
      const envVarMap = {
        openai: "${OPENAI_API_KEY}",
        deepseek: "${DEEPSEEK_API_KEY}",
        anthropic: "${ANTHROPIC_API_KEY}",
        ollama: "${OLLAMA_API_KEY}",
      };
      const nameSelect = $("#add-section-name");
      const apiKeyInput = form.querySelector('[data-key="api_key"]');
      if (nameSelect && apiKeyInput) {
        const syncApiKey = () => {
          const envRef = envVarMap[nameSelect.value] || "";
          // Only auto-fill if the user hasn't typed something custom.
          if (!apiKeyInput.value || apiKeyInput.value.startsWith("${")) {
            apiKeyInput.value = envRef;
          }
        };
        nameSelect.addEventListener("change", syncApiKey);
        syncApiKey();
      }
    }

  };

  // Collect form field values into a {key: coerced_value} dict.
  const collectFormValues = () => {
    const form = $("#section-form");
    const errors = [];
    const values = {};

    formContext.schema.forEach((fieldDef) => {
      if (fieldDef.advanced && !showAdvanced) return;
      const input = form.querySelector(`[data-key="${fieldDef.key}"]`);
      if (!input) return;

      let newVal;
      if (fieldDef.type === "checkboxes") {
        const checked = Array.from(input.querySelectorAll("input:checked")).map(
          (cb) => cb.value
        );
        newVal = checked.length ? checked.join(", ") : "";
      } else {
        newVal = input.value.trim();
      }

      if (fieldDef.required && !newVal) {
        errors.push(`${fieldDef.label} is required.`);
        return;
      }
      if (!newVal) return;
      if (fieldDef.type === "password" && !newVal) return;

      // Type coercion.
      let value;
      if (fieldDef.type === "number" && newVal) {
        value = parseInt(newVal, 10);
        if (isNaN(value)) { errors.push(`${fieldDef.label} must be a number.`); return; }
      } else if (newVal.includes(",") && fieldDef.type === "text") {
        const original = formContext.fields[fieldDef.key];
        if (Array.isArray(original) || newVal.includes(",")) {
          value = newVal.split(",").map((s) => s.trim()).filter(Boolean);
        } else {
          value = newVal;
        }
      } else {
        value = newVal;
      }
      values[fieldDef.key] = value;
    });
    return { values, errors };
  };

  // Generate a TOML section block as text for "add" mode.
  const generateSectionToml = (sectionFullName, values) => {
    const lines = [`[${sectionFullName}]`];
    for (const [key, val] of Object.entries(values)) {
      if (Array.isArray(val)) {
        const items = val.map((v) =>
          typeof v === "number" ? String(v) : `"${String(v).replace(/"/g, '\\"')}"`
        );
        lines.push(`${key} = [${items.join(", ")}]`);
      } else if (typeof val === "number") {
        lines.push(`${key} = ${val}`);
      } else if (typeof val === "boolean") {
        lines.push(`${key} = ${val}`);
      } else {
        lines.push(`${key} = "${String(val).replace(/"/g, '\\"')}"`);
      }
    }
    return lines.join("\n") + "\n";
  };

  // Save handler — works for both edit and add modes.
  const saveForm = async () => {
    const form = $("#section-form");
    const { values, errors } = collectFormValues();

    // ---- Add mode: generate a new section block and append ----
    if (formContext.addMode) {
      const nameInput = $("#add-section-name");
      const sectionSuffix = (nameInput ? nameInput.value.trim() : "").replace(/[^a-zA-Z0-9_\-]/g, "_");
      if (!sectionSuffix) {
        errors.push("Section name is required.");
      }
      if (errors.length) {
        $("#form-error").textContent = errors.join(" ");
        $("#form-error").hidden = false;
        return;
      }

      const fullName = `${formContext.addPrefix}.${sectionSuffix}`;
      // Check for duplicate.
      if (state.sections.some((s) => s.name === fullName)) {
        $("#form-error").textContent = `Section [${fullName}] already exists.`;
        $("#form-error").hidden = false;
        return;
      }

      const block = generateSectionToml(fullName, values);
      let buffer = state.currentContent;
      // Append after the last section of the same type, or at end.
      const samePrefixSections = state.sections.filter(
        (s) => s.prefix === formContext.addPrefix
      );
      if (samePrefixSections.length) {
        const last = samePrefixSections[samePrefixSections.length - 1];
        const lines = buffer.split("\n");
        const insertAt = last.line_end;
        lines.splice(insertAt, 0, "", ...block.split("\n"));
        buffer = lines.join("\n");
      } else {
        buffer = buffer.replace(/\n*$/, "") + "\n\n" + block;
      }

      editor.setValue(buffer);
      state.currentContent = buffer;
      const dirty = state.currentContent !== state.originalContent;
      $("#save-btn").disabled = !dirty;
      refreshSectionsFromBuffer();
      formModal.close();
      if (dirty) await saveConfig();
      return;
    }

    // ---- Edit mode ----
    // Check if the user renamed the section.
    const nameInput = $("#add-section-name");
    const newSuffix = nameInput ? nameInput.value.trim().replace(/[^a-zA-Z0-9_\-]/g, "_") : "";
    if (!newSuffix) {
      errors.push("Section name is required.");
    }
    const prefix = formContext.sectionName.split(".")[0];
    const newFullName = prefix + "." + newSuffix;
    const renamed = newFullName !== formContext.sectionName;

    if (renamed && state.sections.some((s) => s.name === newFullName)) {
      errors.push(`Section [${newFullName}] already exists.`);
    }
    if (errors.length) {
      $("#form-error").textContent = errors.join(" ");
      $("#form-error").hidden = false;
      return;
    }

    // For rename: delete the old section, then generate a fresh block
    // with the new name + all form values. This avoids fragile line-
    // patching and reuses the same code path as "add mode".
    if (renamed) {
      const section = state.sections.find((s) => s.name === formContext.sectionName);
      if (section) {
        const lines = state.currentContent.split("\n");
        let start = section.line_start;
        if (start > 0 && lines[start - 1].trim() === "") start--;
        const after = lines.slice(0, start).concat(lines.slice(section.line_end));
        state.currentContent = after.join("\n");
      }
      // Now append the new section (same logic as add mode).
      const block = generateSectionToml(newFullName, values);
      let buffer = state.currentContent;
      const samePrefixSections = scanSectionsClient(buffer).filter(
        (s) => s.prefix === prefix
      );
      if (samePrefixSections.length) {
        const last = samePrefixSections[samePrefixSections.length - 1];
        const lines = buffer.split("\n");
        lines.splice(last.line_end, 0, "", ...block.split("\n"));
        buffer = lines.join("\n");
      } else {
        buffer = buffer.replace(/\n*$/, "") + "\n\n" + block;
      }
      editor.setValue(buffer);
      state.currentContent = buffer;
    } else {
      // No rename — patch fields in place via tomlEdit.edit().
      if (!window.tomlEdit) {
        $("#form-error").textContent =
          "TOML editor library failed to load — edit the TOML directly.";
        $("#form-error").hidden = false;
        return;
      }
      let buffer = state.currentContent;
      const editErrors = [];
      formContext.schema.forEach((fieldDef) => {
        if (fieldDef.advanced && !showAdvanced) return;
        if (fieldDef.key in values) {
          try {
            buffer = window.tomlEdit.edit(
              buffer, formContext.sectionName + "." + fieldDef.key, values[fieldDef.key]
            );
          } catch (err) {
            editErrors.push(`Failed to set ${fieldDef.key}: ${err.message}`);
          }
        }
      });
      if (editErrors.length) {
        $("#form-error").textContent = editErrors.join(" ");
        $("#form-error").hidden = false;
        return;
      }
      editor.setValue(buffer);
      state.currentContent = buffer;
    }

    const dirty = state.currentContent !== state.originalContent;
    $("#save-btn").disabled = !dirty;
    refreshSectionsFromBuffer();
    formModal.close();
    if (dirty) await saveConfig();
  };

  // Open the Edit form for a specific section.
  const openEditSectionModal = (sectionName) => {
    // Find the section in state.sections (populated from the server
    // or the client-side scanner).
    const section = state.sections.find((s) => s.name === sectionName);
    let fields = (section && section.fields) || {};

    // If the server didn't provide parsed fields (e.g. aimm wasn't
    // restarted), try parsing the textarea content with tomlEdit.
    if (!Object.keys(fields).length && window.tomlEdit) {
      try {
        const parsed = window.tomlEdit.parse(state.currentContent);
        // Navigate the nested dict: "marketplace.facebook" → parsed.marketplace.facebook
        const parts = sectionName.split(".");
        let node = parsed;
        for (const p of parts) { node = node && node[p]; }
        if (node && typeof node === "object") fields = node;
      } catch (err) {
        console.warn("tomlEdit.parse failed for form:", err);
      }
    }

    // Look up the schema. If we don't have one for this section type,
    // show a "raw TOML only" message.
    const schema = findFormSchema(sectionName);
    if (!schema) {
      $("#form-modal-title").textContent = `Edit [${sectionName}]`;
      $("#form-modal-hint").hidden = false;
      $("#form-modal-hint").textContent =
        `No form defined for [${sectionName}] yet — edit the TOML directly ` +
        "in the editor. (Forms for item, user, and AI sections are coming soon.)";
      $("#section-form").innerHTML = "";
      formModal.open();
      return;
    }

    const dot = sectionName.indexOf(".");
    const suffix = dot >= 0 ? sectionName.slice(dot + 1) : sectionName;
    formContext = { sectionName, fields, schema, nameValue: suffix };
    $("#form-modal-title").textContent = `Edit [${sectionName}]`;
    $("#form-modal-hint").hidden = true;
    renderForm(schema, fields);
    formModal.open();
  };

  // Open form in "add" mode: empty fields + a name input at top.
  const openAddSectionModal = (prefix) => {
    const schema = findFormSchema(prefix + ".*") || findFormSchema(prefix + ".facebook");
    if (!schema) {
      alert(`No form defined for [${prefix}.*] — add it manually in the TOML editor.`);
      return;
    }
    // Build a placeholder section name from the prefix.
    const existingNames = state.sections
      .filter((s) => s.prefix === prefix)
      .map((s) => s.suffix);
    let suggestedName = prefix === "marketplace" ? "facebook" : "";

    formContext = {
      sectionName: `${prefix}.__new__`,
      fields: {},
      schema,
      addMode: true,
      addPrefix: prefix,
      nameValue: suggestedName,
    };
    activeTab = "left";
    $("#form-modal-title").textContent = `Add a new [${prefix}.*] section`;
    $("#form-modal-hint").hidden = false;
    $("#form-modal-hint").textContent =
      "Choose a name and fill in the fields. The new section will be " +
      "appended to the end of your config.";
    renderForm(schema, {});
    formModal.open();
    setTimeout(() => {
      const nameInput = $("#add-section-name");
      if (nameInput && !nameInput.value) nameInput.focus();
    }, 50);
  };

  wireClick("#form-modal-close", () => formModal.close());
  wireClick("#form-cancel", () => formModal.close());
  wireClick("#form-save", () => saveForm());
  const backdrop = document.querySelector("#form-modal .modal-backdrop");
  if (backdrop) backdrop.addEventListener("click", () => formModal.close());

  // -------- "+ Add" dropdown in the header --------
  wireClick("#add-btn", () => {
    const menu = $("#add-menu");
    if (menu) menu.classList.toggle("hidden");
  });
  // Close dropdown when clicking outside.
  document.addEventListener("click", (e) => {
    if (!e.target.closest("#add-dropdown")) {
      const menu = $("#add-menu");
      if (menu) menu.classList.add("hidden");
    }
  });
  // Wire each menu item to openAddSectionModal.
  document.querySelectorAll("#add-menu button[data-prefix]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const menu = $("#add-menu");
      if (menu) menu.classList.add("hidden");
      openAddSectionModal(btn.dataset.prefix);
    });
  });

  const connectWs = () => {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${proto}//${location.host}/ws/stream`);
    state.ws = ws;
    ws.onopen = () => {
      state.wsConnected = true;
      $("#ws-status").textContent = "● streaming";
      renderMonitorStatus();
    };
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.type === "log") {
        state.records.push(msg.record);
        noteActivity(msg.record);
        if (state.records.length > 5000) state.records.shift();
        renderLogs();
        renderMonitorStatus();
      }
    };
    ws.onclose = () => {
      state.wsConnected = false;
      $("#ws-status").textContent = "● disconnected — retrying…";
      renderMonitorStatus();
      setTimeout(connectWs, 2000);
    };
    ws.onerror = () => {
      ws.close();
    };
  };

  // ---------------------------------------------------------------
  // Boot
  // ---------------------------------------------------------------
  // The running aimm version, and a newer release found by the monitor's
  // update check (once a day). The header shows a chip when there is one;
  // Settings > About says how to update (in Docker, aimm installs it itself).
  const refreshUpdateBadge = async () => {
    try {
      const res = await fetch("/api/status", { credentials: "same-origin" });
      if (!res.ok) return;
      const status = await res.json();
      if (status.version) {
        ["aimm-version", "settings-version"].forEach((id) => {
          const el = document.getElementById(id);
          if (el) el.textContent = `v${status.version}`;
        });
      }
      state.version = status.version;
      state.update = status.update || null;
      state.updateInPlace = !!(status.update && status.self_update && status.self_update.available);
      // there is nothing to log out of on 127.0.0.1
      const logoutRow = document.getElementById("logout-row");
      if (logoutRow) logoutRow.hidden = !!status.open;
      // the user signed in by aimm or, behind a reverse proxy, by the proxy
      const signedIn = document.getElementById("signed-in-row");
      if (signedIn) {
        const proxied = status.open && status.user;
        signedIn.hidden = !status.user;
        $("#signed-in-text").textContent = status.user
          ? `Signed in as ${status.user}${proxied ? ` by your reverse proxy (${status.auth_mode})` : ""}.`
          : "";
      }
      const badge = document.getElementById("update-badge");
      if (badge) {
        badge.hidden = !state.update;
        if (state.update) badge.textContent = `⬆ aimm ${state.update.latest} available`;
      }
      renderUpdateInfo();
    } catch (_) {}
  };

  const renderUpdateInfo = () => {
    const info = document.getElementById("update-info");
    const updateBtn = document.getElementById("update-btn");
    if (!info || !updateBtn) return;
    const update = state.update;
    if (!update) {
      info.textContent = "No newer release is known. The monitor checks for one once a day.";
      if (!state.updating) updateBtn.hidden = true;
      return;
    }
    const changelog = `<a href="${esc(update.changelog)}" target="_blank" rel="noopener">What's new</a>`;
    if (state.updateInPlace) {
      info.innerHTML = `aimm ${esc(update.latest)} is available. ${changelog}`;
      if (!state.updating) {
        state.updateTarget = update.latest;
        updateBtn.hidden = false;
        updateBtn.disabled = false;
        updateBtn.textContent = `⬆ Update to ${update.latest}`;
        updateBtn.title = `Install aimm ${update.latest} in this container and restart it`;
      }
      return;
    }
    updateBtn.hidden = true;
    const note = update.note ? ` ${esc(update.note)}.` : "";
    info.innerHTML =
      `aimm ${esc(update.latest)} is available (you have ${esc(update.current)}). ` +
      `Upgrade with <code>${esc(update.command)}</code>.${note} ${changelog}`;
  };

  const resetUpdateButton = (message) => {
    state.updating = false;
    setEditorStatus(`⬆ Update failed: ${message}`, "err");
    refreshUpdateBadge();
  };

  // aimm exits after installing and supervisord starts the new version: wait
  // until the server answers as another version, then reload the page. (Not
  // `=== version`: older releases do not report their version.)
  const waitForRestart = (runningVersion) => {
    const started = Date.now();
    const poll = async () => {
      try {
        const res = await fetch("/api/status", { credentials: "same-origin" });
        if (res.status === 401) {
          window.location.reload(); // restarted, and the session went with it
          return;
        }
        if (res.ok) {
          const status = await res.json();
          if (status.version !== runningVersion) {
            window.location.reload();
            return;
          }
          if (status.self_update && status.self_update.state === "failed") {
            resetUpdateButton(status.self_update.error || "unknown error");
            return;
          }
        }
      } catch (_) {} // the server is restarting
      if (Date.now() - started < 10 * 60 * 1000) {
        setTimeout(poll, 3000);
      } else {
        resetUpdateButton("aimm did not come back with the new version; check `docker logs aimm`.");
      }
    };
    setTimeout(poll, 3000);
  };

  wireClick("#update-btn", async () => {
    const btn = $("#update-btn");
    const version = state.updateTarget;
    if (!btn || !version) return;
    if (!confirm(`Install aimm ${version} and restart it? Searches pause while it installs and restarts.`)) {
      return;
    }
    state.updating = true;
    btn.disabled = true;
    btn.textContent = `⬆ Updating to ${version}…`;
    try {
      const res = await api("/api/update", { method: "POST" });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || res.statusText);
      setEditorStatus(`⬆ Installing aimm ${version}. The page reloads when aimm restarts.`, "ok");
      waitForRestart(state.version);
    } catch (err) {
      resetUpdateButton(err.message);
    }
  });

  // ---------------------------------------------------------------
  // Settings dialog: version and update, test notifications, cache, account
  // ---------------------------------------------------------------
  // What each type of cache entry is, and what clearing it does.
  const CACHE_TYPES = {
    "listing-details": {
      label: "Listing details",
      effect: "Listings are fetched from Facebook again the next time a search finds them.",
    },
    "ai-inquiries": {
      label: "AI ratings",
      effect: "Listings are rated by the AI again, which means new AI calls (and their cost).",
    },
    "user-notifications": {
      label: "Notified records",
      effect: "Listings you were already notified about can be sent to you again.",
    },
    counters: {
      label: "Counters",
      effect: "The statistics (searches, listings, notifications) start again from zero.",
    },
    "update-check": {
      label: "Update check",
      effect: "aimm checks for a newer release again.",
    },
    evaluations: {
      label: "Evaluation history",
      effect: "The Listings view starts empty and fills again as aimm evaluates listings.",
    },
  };

  const showSettingsTab = (tab) => {
    $$("#settings-nav button").forEach((b) => b.classList.toggle("active", b.dataset.settingsTab === tab));
    $$("#settings-modal [data-settings-section]").forEach((sec) => {
      sec.hidden = sec.dataset.settingsSection !== tab;
    });
    if (tab === "notifications") loadSettingsUsers();
    if (tab === "cache") loadCacheStatus();
  };

  const settingsModal = {
    el: () => $("#settings-modal"),
    open(tab = "about") {
      this.el().classList.remove("hidden");
      refreshUpdateBadge();
      showSettingsTab(tab);
    },
    close() { this.el().classList.add("hidden"); },
  };

  wireClick("#settings-btn", () => settingsModal.open());
  wireClick("#update-badge", () => settingsModal.open("about"));
  wireClick("#aimm-version", () => settingsModal.open("about"));
  wireClick("#settings-close", () => settingsModal.close());
  const settingsBackdrop = document.querySelector("#settings-modal .modal-backdrop");
  if (settingsBackdrop) settingsBackdrop.addEventListener("click", () => settingsModal.close());
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !settingsModal.el().classList.contains("hidden")) settingsModal.close();
  });
  $$("#settings-nav button").forEach((btn) => {
    btn.addEventListener("click", () => showSettingsTab(btn.dataset.settingsTab));
  });

  const settingsMessage = (container, text, cls = "") => {
    container.innerHTML = `<p class="settings-status ${cls}">${esc(text)}</p>`;
  };

  // One row per user: its channels, a "Send test" button and the result of
  // each channel. Other actions for a user can be added to `.settings-row-actions`.
  const renderUserRow = (user) => {
    const row = document.createElement("div");
    row.className = "settings-row settings-user";
    row.dataset.user = user.name;
    const channels = user.channels.length ? user.channels.join(", ") : "no notification channel";
    row.innerHTML =
      `<div class="settings-row-main">` +
      `<span class="settings-row-name">${esc(user.name)}</span>` +
      `${user.enabled ? "" : ' <span class="settings-dim">(disabled)</span>'}` +
      `<div class="settings-dim">${esc(channels)}</div>` +
      `<ul class="test-results"></ul>` +
      `</div>` +
      `<div class="settings-row-actions"><button class="test-btn">Send test</button></div>`;
    const btn = row.querySelector(".test-btn");
    btn.disabled = !user.channels.length;
    btn.addEventListener("click", () => sendTestNotification(user.name, btn, row.querySelector(".test-results")));
    return row;
  };

  const loadSettingsUsers = async () => {
    const container = $("#settings-users");
    settingsMessage(container, "Loading…", "settings-dim");
    try {
      const res = await api("/api/notifications/users");
      const data = await res.json();
      if (!data.ok) {
        settingsMessage(container, `The configuration cannot be loaded: ${data.error}`, "err");
        return;
      }
      if (!data.users.length) {
        settingsMessage(container, "There is no [user.*] section yet: add one in the editor or with Configure.", "settings-dim");
        return;
      }
      container.innerHTML = "";
      data.users.forEach((user) => container.appendChild(renderUserRow(user)));
    } catch (err) {
      settingsMessage(container, String(err.message || err), "err");
    }
  };

  const sendTestNotification = async (name, btn, results) => {
    btn.disabled = true;
    btn.textContent = "Sending…";
    results.innerHTML = "";
    try {
      const res = await api("/api/notifications/test", {
        method: "POST",
        body: JSON.stringify({ user: name }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || res.statusText);
      results.innerHTML = data.results.length
        ? data.results
            .map((r) =>
              r.ok
                ? `<li class="ok">✓ ${esc(r.channel)}</li>`
                : `<li class="err">✗ ${esc(r.channel)}: ${esc(r.error || "not sent")}</li>`
            )
            .join("")
        : `<li class="err">✗ no notification channel is set up</li>`;
    } catch (err) {
      results.innerHTML = `<li class="err">✗ ${esc(err.message)}</li>`;
    } finally {
      btn.disabled = false;
      btn.textContent = "Send test";
    }
  };

  const setCacheStatus = (text, cls = "") => {
    const el = $("#settings-cache-status");
    el.hidden = !text;
    el.className = `settings-status ${cls}`;
    el.textContent = text;
  };

  const loadCacheStatus = async () => {
    const container = $("#settings-cache");
    settingsMessage(container, "Loading…", "settings-dim");
    try {
      const res = await api("/api/cache");
      const data = await res.json();
      if (data.broken) {
        // only Clear all works on a cache that cannot be read
        settingsMessage(container, `The cache cannot be read (${data.error}). Clear all of it to start with an empty cache.`, "err");
        return;
      }
      container.innerHTML = "";
      Object.entries(data.counts).forEach(([type, count]) => {
        const info = CACHE_TYPES[type] || { label: type, effect: "" };
        const row = document.createElement("div");
        row.className = "settings-row";
        row.innerHTML =
          `<div class="settings-row-main"><span class="settings-row-name">${esc(info.label)}</span>` +
          ` <span class="settings-dim">${count} ${count === 1 ? "entry" : "entries"}</span>` +
          `<div class="settings-dim">${esc(info.effect)}</div></div>` +
          `<div class="settings-row-actions"><button class="danger">Clear</button></div>`;
        const btn = row.querySelector("button");
        btn.disabled = count === 0;
        btn.addEventListener("click", () => clearCacheEntries(type));
        container.appendChild(row);
      });
    } catch (err) {
      settingsMessage(container, String(err.message || err), "err");
    }
  };

  // aimm exits and supervisord starts it again: wait until the server has gone
  // away and answers again, then reload the page.
  const reloadAfterRestart = () => {
    const started = Date.now();
    let wentAway = false;
    const poll = async () => {
      try {
        const res = await fetch("/api/status", { credentials: "same-origin" });
        if (wentAway || res.status === 401) {
          window.location.reload();
          return;
        }
      } catch (_) {
        wentAway = true;
      }
      if (Date.now() - started < 10 * 60 * 1000) setTimeout(poll, 2000);
      else setCacheStatus("aimm did not come back; check `docker logs aimm`.", "err");
    };
    setTimeout(poll, 2000);
  };

  const clearCacheEntries = async (type) => {
    const describe = (t) => CACHE_TYPES[t] || { label: t, effect: "" };
    const what =
      type === "all"
        ? "Clear the whole cache?\n\n" +
          Object.values(CACHE_TYPES).map((t) => `${t.label}: ${t.effect}`).join("\n")
        : `Clear ${describe(type).label}?\n\n${describe(type).effect}`;
    if (!confirm(what)) return;
    setCacheStatus("Clearing…", "settings-dim");
    try {
      const res = await api("/api/cache/clear", { method: "POST", body: JSON.stringify({ type }) });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || res.statusText);
      if (data.restart === "restarting") {
        setCacheStatus(`${data.message} aimm is restarting to open a new cache; the page reloads when it is back.`, "ok");
        reloadAfterRestart();
        return;
      }
      if (data.restart === "needed") {
        setCacheStatus(`${data.message} Restart aimm to open a new cache.`, "err");
        return;
      }
      setCacheStatus(data.message, "ok");
      loadCacheStatus();
    } catch (err) {
      setCacheStatus(`Clear failed: ${err.message}`, "err");
    }
  };

  wireClick("#cache-clear-all", () => clearCacheEntries("all"));
  wireClick("#cache-refresh", () => {
    setCacheStatus("");
    loadCacheStatus();
  });

  const buildVncUrl = () => {
    const port = window.location.port || (window.location.protocol === "https:" ? "443" : "80");
    const params = new URLSearchParams({
      host: window.location.hostname,
      port,
      path: "ws/vnc",
      autoconnect: "1",
      resize: "scale",
    });
    return `/vnc/vnc.html?${params.toString()}`;
  };

  const bootstrap = async () => {
    refreshUpdateBadge();
    if (!state.updateTimer) state.updateTimer = setInterval(refreshUpdateBadge, 10 * 60 * 1000);
    refreshMonitorState();
    if (!state.monitorTimer) state.monitorTimer = setInterval(refreshMonitorState, 5000);
    try {
      await loadConfig();
      // CodeMirror needs a refresh after becoming visible (the editor
      // host is hidden during the login screen).
      if (editor.refresh) editor.refresh();
      await loadLogs();
      connectWs();
      let view = "logs";
      try {
        view = localStorage.getItem("aimm.logsView") || "logs";
      } catch (_) {}
      showView(view);
    } catch (err) {
      console.error(err);
    }
  };

  // If we already have a session cookie from a prior visit, try bootstrapping.
  (async () => {
    try {
      const res = await fetch("/api/status", { credentials: "same-origin" });
      if (res.ok) {
        state.csrf = getCookie("aimm_csrf");
        try {
          const status = await res.clone().json();
          const browserBtn = document.getElementById("browser-btn");
          if (browserBtn && status && status.vnc_enabled) {
            browserBtn.href = buildVncUrl();
            browserBtn.hidden = false;
          }
        } catch (_) {}
        hideLogin();
        await bootstrap();
      } else {
        showLogin();
      }
    } catch (err) {
      showLogin();
    }
  })();
})();
