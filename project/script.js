// --- STATE STATE DECLARATIONS ---
let token = localStorage.getItem("token") || "";
let theme = localStorage.getItem("theme") || "dark";
let nodes = [];
let activeJob = null;
let wsConnected = false;
let ws = null;
let reconnectTimer = null;

const API_BASE = `http://${window.location.hostname}:8000`;

// --- DOM ELEMENT CACHING ---
const loginScreen = document.getElementById("login-screen");
const dashboardView = document.getElementById("dashboard-view");
const loginForm = document.getElementById("login-form");
const usernameInput = document.getElementById("username");
const passwordInput = document.getElementById("password");
const authError = document.getElementById("auth-error");

const wsStatusDot = document.getElementById("ws-status-dot");
const wsStatusText = document.getElementById("ws-status-text");
const btnThemeToggle = document.getElementById("btn-theme-toggle");
const btnLogout = document.getElementById("btn-logout");

const nodesCountHeader = document.getElementById("nodes-count-header");
const nodesContainer = document.getElementById("nodes-container");

const addNodeForm = document.getElementById("add-node-form");
const nodeIp = document.getElementById("node-ip");
const nodeUser = document.getElementById("node-user");
const nodePort = document.getElementById("node-port");
const nodeMessage = document.getElementById("node-message");
const btnAddNode = document.getElementById("btn-add-node");

const schedulerContent = document.getElementById("scheduler-content");
const lossChartContainer = document.getElementById("loss-chart-container");
const mapChartContainer = document.getElementById("map-chart-container");
const terminalScreen = document.getElementById("terminal-screen");

// --- INITIALIZE APPLICATION ---
document.addEventListener("DOMContentLoaded", () => {
  initTheme();
  checkAuth();
  
  // Header Listeners
  btnThemeToggle.addEventListener("click", toggleTheme);
  btnLogout.addEventListener("click", handleLogout);
  
  // Auth Form Listener
  loginForm.addEventListener("submit", handleLogin);
  
  // Node Form Listener
  addNodeForm.addEventListener("submit", handleAddNode);
});

// --- THEME OPERATIONS ---
function initTheme() {
  document.documentElement.setAttribute("data-theme", theme);
  btnThemeToggle.innerText = theme === "dark" ? "☀️ Light" : "🌙 Dark";
}

function toggleTheme() {
  theme = theme === "dark" ? "light" : "dark";
  localStorage.setItem("theme", theme);
  initTheme();
}

// --- AUTHENTICATION OPERATIONS ---
function checkAuth() {
  if (token) {
    loginScreen.classList.add("hidden");
    dashboardView.classList.remove("hidden");
    initWebSocket();
  } else {
    loginScreen.classList.remove("hidden");
    dashboardView.classList.add("hidden");
    if (ws) {
      ws.close();
    }
  }
}

async function handleLogin(e) {
  e.preventDefault();
  authError.classList.add("hidden");
  
  const username = usernameInput.value;
  const password = passwordInput.value;
  
  try {
    const response = await fetch(`${API_BASE}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password })
    });
    
    const data = await response.json();
    
    if (response.ok) {
      token = data.access_token;
      localStorage.setItem("token", token);
      usernameInput.value = "";
      passwordInput.value = "";
      checkAuth();
    } else {
      authError.innerText = data.detail || "Authentication failed.";
      authError.classList.remove("hidden");
    }
  } catch (err) {
    authError.innerText = "Could not connect to API server.";
    authError.classList.remove("hidden");
  }
}

function handleLogout() {
  token = "";
  localStorage.removeItem("token");
  nodes = [];
  activeJob = null;
  checkAuth();
}

// --- WEBSOCKET CONNECTION ---
function initWebSocket() {
  if (ws) {
    ws.close();
  }
  
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  ws = new WebSocket(`${protocol}//${window.location.hostname}:8000/ws/stream`);
  
  ws.onopen = () => {
    wsConnected = true;
    updateWsUI();
    console.log("WebSocket connected.");
  };
  
  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      if (data.nodes) {
        nodes = data.nodes;
        renderNodes();
      }
      
      if (data.active_job) {
        activeJob = data.active_job;
      } else {
        activeJob = null;
      }
      renderScheduler();
      renderCharts();
      renderLogs();
    } catch (err) {
      console.error("Error parsing websocket update", err);
    }
  };
  
  ws.onclose = () => {
    wsConnected = false;
    updateWsUI();
    console.log("WebSocket disconnected. Attempting reconnect in 3s...");
    
    clearTimeout(reconnectTimer);
    reconnectTimer = setTimeout(() => {
      if (token) {
        initWebSocket();
      }
    }, 3000);
  };
}

function updateWsUI() {
  if (wsConnected) {
    wsStatusDot.className = "indicator-dot connected";
    wsStatusText.innerText = "STREAM LIVE";
  } else {
    wsStatusDot.className = "indicator-dot disconnected";
    wsStatusText.innerText = "DISCONNECTED";
  }
}

// --- CLUSTER NODES RENDERING ---
function renderNodes() {
  nodesCountHeader.innerText = `Cluster Nodes (${nodes.length})`;
  nodesContainer.innerHTML = "";
  
  if (nodes.length === 0) {
    nodesContainer.innerHTML = `
      <div class="col-12 p-xl text-center color-muted">
        No nodes added to the cluster. Use the form on the right to register node servers.
      </div>
    `;
    return;
  }
  
  nodes.forEach(node => {
    const isFailed = node.status === "failed";
    const isTraining = node.status === "training";
    
    const nodeCard = document.createElement("div");
    
    let borderClass = "";
    if (isFailed) {
      borderClass = "border-danger";
    } else if (isTraining) {
      borderClass = "border-warning";
    }
    
    nodeCard.className = `glass-card p-md ${borderClass}`;
    
    // Header
    const headerDiv = document.createElement("div");
    headerDiv.className = "flex-row justify-between align-start mb-sm";
    
    let statusText = node.status.toUpperCase();
    let badgeClass = node.status;
    
    if (node.status === "active") {
      statusText = "CONNECTED";
    } else if (node.status === "failed" || node.status === "offline") {
      statusText = "NOT CONNECTED";
    }
    
    headerDiv.innerHTML = `
      <div>
        <h4 class="font-semibold text-lg color-primary">${node.ip}</h4>
        <span class="text-xs color-muted">ssh: ${node.ssh_user}</span>
      </div>
      <span class="badge badge-${badgeClass}">${statusText}</span>
    `;
    nodeCard.appendChild(headerDiv);
    
    // Body Info
    const bodyDiv = document.createElement("div");
    bodyDiv.className = "flex-col gap-sm text-sm color-secondary mb-md";
    
    const gpuInfoStr = (node.gpu_info && node.gpu_info.length > 0) ? `(${node.gpu_info.join(", ")})` : "";
    let metricsHtml = "";
    
    if (node.latest_metric) {
      const gpuUtil = node.latest_metric.gpu_util[0] || 0;
      const vramUtil = node.latest_metric.vram_util[0] || 0;
      const temp = node.latest_metric.temp[0] || 0;
      const tempColor = temp > 78 ? "var(--danger)" : "var(--success)";
      
      metricsHtml = `
        <div class="node-metrics-box">
          <div class="metric-row">
            <span>GPU Utilization:</span>
            <span style="color: var(--text-primary); font-weight: 500;">${gpuUtil}%</span>
          </div>
          <div class="metric-progress-bg">
            <div class="metric-progress-bar" style="width: ${gpuUtil}%;"></div>
          </div>
          <div class="metric-row">
            <span>VRAM Usage:</span>
            <span style="color: var(--text-primary);">${vramUtil}%</span>
          </div>
          <div class="metric-row">
            <span>Temp:</span>
            <span style="color: ${tempColor};">${temp}°C</span>
          </div>
        </div>
      `;
    }
    
    bodyDiv.innerHTML = `
      <div><strong>GPUs:</strong> ${node.gpu_count} ${gpuInfoStr}</div>
      ${metricsHtml}
    `;
    nodeCard.appendChild(bodyDiv);
    
    // Actions Footer
    const footerDiv = document.createElement("div");
    footerDiv.className = "node-card-footer";
    
    const refreshBtn = document.createElement("button");
    refreshBtn.className = "btn-secondary";
    refreshBtn.style.padding = "6px 10px";
    refreshBtn.style.fontSize = "12px";
    refreshBtn.title = "Ping/Refresh";
    refreshBtn.innerHTML = `
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67" /></svg>
    `;
    refreshBtn.addEventListener("click", () => handleRefreshNode(node.id));
    
    const deleteBtn = document.createElement("button");
    deleteBtn.className = "btn-secondary";
    deleteBtn.style.padding = "6px 10px";
    deleteBtn.style.fontSize = "12px";
    deleteBtn.style.color = "var(--danger)";
    deleteBtn.title = "Delete";
    deleteBtn.innerHTML = `
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" /></svg>
    `;
    deleteBtn.addEventListener("click", () => handleDeleteNode(node.id));
    
    footerDiv.appendChild(refreshBtn);
    footerDiv.appendChild(deleteBtn);
    nodeCard.appendChild(footerDiv);
    
    nodesContainer.appendChild(nodeCard);
  });
}

// --- NODE MANAGEMENT ACTIONS ---
async function handleAddNode(e) {
  e.preventDefault();
  btnAddNode.disabled = true;
  btnAddNode.innerText = "Verifying...";
  nodeMessage.classList.add("hidden");
  
  const ip = nodeIp.value;
  const user = nodeUser.value;
  const port = parseInt(nodePort.value);
  
  try {
    const response = await fetch(`${API_BASE}/nodes/add`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${token}`
      },
      body: JSON.stringify({ ip, ssh_user: user, ssh_port: port })
    });
    
    const data = await response.json();
    if (response.ok) {
      nodeMessage.innerText = "Connected successfully!";
      nodeMessage.classList.remove("hidden");
      nodeMessage.classList.add("color-success");
      nodeMessage.classList.remove("color-danger");
      nodeIp.value = "";
    } else {
      nodeMessage.innerText = data.detail || "Not connected.";
      nodeMessage.classList.remove("hidden");
      nodeMessage.classList.add("color-danger");
      nodeMessage.classList.remove("color-success");
    }
  } catch (err) {
    nodeMessage.innerText = "Network error. Not connected.";
    nodeMessage.classList.remove("hidden");
    nodeMessage.classList.add("color-danger");
    nodeMessage.classList.remove("color-success");
  } finally {
    nodeMessage.classList.remove("hidden");
    btnAddNode.disabled = false;
    btnAddNode.innerHTML = `
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" /></svg>
      Add Node
    `;
  }
}

async function handleRefreshNode(nodeId) {
  try {
    await fetch(`${API_BASE}/nodes/${nodeId}/refresh`, {
      method: "POST",
      headers: { "Authorization": `Bearer ${token}` }
    });
  } catch (err) {
    console.error("Refresh failed", err);
  }
}

async function handleDeleteNode(nodeId) {
  if (!confirm("Are you sure you want to delete this node?")) return;
  try {
    await fetch(`${API_BASE}/nodes/${nodeId}`, {
      method: "DELETE",
      headers: { "Authorization": `Bearer ${token}` }
    });
  } catch (err) {
    console.error("Delete failed", err);
  }
}

// --- JOB SCHEDULER & CONTROLLER ---
function renderScheduler() {
  schedulerContent.innerHTML = "";
  
  if (activeJob) {
    const jobBox = document.createElement("div");
    jobBox.className = "flex-col gap-md";
    
    jobBox.innerHTML = `
      <div class="active-job-details">
        <div class="active-job-row">
          <strong>Active Job ID:</strong>
          <span>#${activeJob.id}</span>
        </div>
        <div class="active-job-row">
          <strong>Model:</strong>
          <span>${activeJob.model_name}</span>
        </div>
        <div class="active-job-row">
          <strong>Epoch:</strong>
          <span>${activeJob.current_epoch} / ${activeJob.epochs}</span>
        </div>
        <div class="active-job-row">
          <strong>Status:</strong>
          <span class="badge badge-training">${activeJob.status}</span>
        </div>
      </div>
    `;
    
    const stopBtn = document.createElement("button");
    stopBtn.className = "btn-danger w-full";
    stopBtn.innerHTML = `
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="4" width="16" height="16" rx="2" /></svg>
      Kill Distributed Training
    `;
    stopBtn.addEventListener("click", handleStopJob);
    jobBox.appendChild(stopBtn);
    
    schedulerContent.appendChild(jobBox);
  } else {
    // Launch Form
    const launchForm = document.createElement("form");
    launchForm.className = "flex-col gap-md";
    
    const activeNodesList = nodes.filter(n => n.status === "active");
    const activeNodesCount = activeNodesList.length;
    const isLaunchDisabled = activeNodesCount === 0;
    
    const nodesDisplayHtml = activeNodesCount > 0
      ? `<div class="p-sm text-sm" style="background: var(--status-online-dim); color: var(--success); border: 1px solid rgba(114, 169, 84, 0.3); border-radius: 4px;">
          <strong>Targeting ${activeNodesCount} Connected Node(s):</strong><br/>
          ${activeNodesList.map(n => n.ip).join(", ")}
         </div>`
      : `<div class="p-sm text-sm" style="background: var(--status-offline-dim); color: var(--danger); border: 1px solid rgba(220, 53, 69, 0.3); border-radius: 4px;">
          No connected nodes available for training. Please add nodes first.
         </div>`;
    
    launchForm.innerHTML = `
      ${nodesDisplayHtml}
      
      <div class="form-group mt-sm">
        <label class="form-label">YOLOv8 Model Configuration</label>
        <select id="job-model" class="glass-input">
          <option value="yolov8n.pt">YOLOv8 Nano (yolov8n.pt)</option>
          <option value="yolov8s.pt">YOLOv8 Small (yolov8s.pt)</option>
          <option value="yolov8m.pt">YOLOv8 Medium (yolov8m.pt)</option>
          <option value="yolov8l.pt">YOLOv8 Large (yolov8l.pt)</option>
          <option value="yolov8x.pt">YOLOv8 ExtraLarge (yolov8x.pt)</option>
        </select>
      </div>

      <div class="form-group">
        <label class="form-label">Dataset Config (yaml)</label>
        <input type="text" id="job-dataset" class="glass-input" value="coco128.yaml" required>
      </div>

      <div class="flex-row gap-sm">
        <div class="form-group flex-1">
          <label class="form-label">Epochs</label>
          <input type="number" id="job-epochs" class="glass-input" value="15" min="1" required>
        </div>
        <div class="form-group flex-1">
          <label class="form-label">Batch Size</label>
          <input type="number" id="job-batch" class="glass-input" value="16" min="1" required>
        </div>
      </div>

      <div class="form-group">
        <label class="form-label">Learning Rate</label>
        <input type="number" step="0.001" id="job-lr" class="glass-input" value="0.01" required>
      </div>

      <div id="job-message" style="font-size: 13px; color: var(--warning); display: none;"></div>
    `;
    
    const launchBtn = document.createElement("button");
    launchBtn.type = "submit";
    launchBtn.className = "btn-primary";
    launchBtn.disabled = isLaunchDisabled;
    launchBtn.innerHTML = `
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3" /></svg>
      Deploy & Launch DDP
    `;
    launchForm.appendChild(launchBtn);
    launchForm.addEventListener("submit", handleStartJob);
    
    schedulerContent.appendChild(launchForm);
  }
}

async function handleStartJob(e) {
  e.preventDefault();
  const model = document.getElementById("job-model").value;
  const dataset = document.getElementById("job-dataset").value;
  const epochs = parseInt(document.getElementById("job-epochs").value);
  const batchSize = parseInt(document.getElementById("job-batch").value);
  const lr = parseFloat(document.getElementById("job-lr").value);
  const jobMessage = document.getElementById("job-message");
  
  jobMessage.classList.add("hidden");
  
  try {
    const response = await fetch(`${API_BASE}/train/start`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${token}`
      },
      body: JSON.stringify({
        model_name: model,
        dataset_path: dataset,
        epochs: epochs,
        batch_size: batchSize,
        learning_rate: lr
      })
    });
    
    const data = await response.json();
    if (response.ok) {
      jobMessage.innerText = "Training job launched.";
      jobMessage.style.color = "var(--primary)";
    } else {
      jobMessage.innerText = data.detail || "Failed to start job.";
      jobMessage.style.color = "var(--danger)";
    }
  } catch (err) {
    jobMessage.innerText = "Network error.";
    jobMessage.style.color = "var(--danger)";
  } finally {
    jobMessage.classList.remove("hidden");
  }
}

async function handleStopJob() {
  if (!activeJob) return;
  const jobMessage = document.getElementById("job-message");
  try {
    const response = await fetch(`${API_BASE}/train/jobs/${activeJob.id}/stop`, {
      method: "POST",
      headers: { "Authorization": `Bearer ${token}` }
    });
    if (response.ok && jobMessage) {
      jobMessage.innerText = "Stop command sent.";
      jobMessage.classList.remove("hidden");
    }
  } catch (err) {
    console.error("Stop failed", err);
  }
}

// --- TELEMETRY GRAPH GENERATION (SVG) ---
function renderCharts() {
  const history = (activeJob && activeJob.metrics_history) ? activeJob.metrics_history : [];
  
  // Render Loss Chart
  if (history.length === 0) {
    lossChartContainer.innerHTML = `
      <div style="height: 150px; display: flex; align-items: center; justify-content: center; color: var(--text-muted);">
        Waiting for epoch metrics...
      </div>
    `;
    mapChartContainer.innerHTML = `
      <div style="height: 150px; display: flex; align-items: center; justify-content: center; color: var(--text-muted);">
        Waiting for accuracy metrics...
      </div>
    `;
    return;
  }
  
  const width = 450;
  const height = 150;
  const padding = 30;
  
  // 1. Loss SVG Chart
  const maxVal = Math.max(...history.map(d => d.box_loss + d.cls_loss), 1.0);
  const minVal = 0;
  
  const pointsLoss = history.map((d, index) => {
    const x = padding + (index / (history.length - 1 || 1)) * (width - 2 * padding);
    const y = height - padding - ((d.box_loss + d.cls_loss - minVal) / (maxVal - minVal)) * (height - 2 * padding);
    return `${x},${y}`;
  }).join(" ");
  
  let lossDots = "";
  let lossLabels = "";
  
  history.forEach((d, i) => {
    const x = padding + (i / (history.length - 1 || 1)) * (width - 2 * padding);
    const y = height - padding - ((d.box_loss + d.cls_loss - minVal) / (maxVal - minVal)) * (height - 2 * padding);
    lossDots += `<circle cx="${x}" cy="${y}" r="4" fill="var(--primary)" stroke="var(--bg-surface)" stroke-width="1" />`;
    lossLabels += `<text x="${x}" y="${height - 5}" fill="var(--text-muted)" font-size="9" text-anchor="middle">E${d.epoch}</text>`;
  });
  
  lossChartContainer.innerHTML = `
    <svg width="100%" height="150px" viewBox="0 0 ${width} ${height}" style="overflow: visible;">
      <line x1="${padding}" y1="${padding}" x2="${width - padding}" y2="${padding}" stroke="var(--border-default)" />
      <line x1="${padding}" y1="${height/2}" x2="${width - padding}" y2="${height/2}" stroke="var(--border-default)" />
      <line x1="${padding}" y1="${height - padding}" x2="${width - padding}" y2="${height - padding}" stroke="var(--border-strong)" />
      
      <polyline fill="none" stroke="var(--primary-light)" stroke-width="3" points="${pointsLoss}" />
      ${lossDots}
      
      <text x="${padding - 5}" y="${padding + 5}" fill="var(--text-muted)" font-size="10" text-anchor="end">${maxVal.toFixed(1)}</text>
      <text x="${padding - 5}" y="${height - padding + 5}" fill="var(--text-muted)" font-size="10" text-anchor="end">0.0</text>
      ${lossLabels}
    </svg>
  `;
  
  // 2. Accuracy mAP Chart
  const pointsMap = history.map((d, index) => {
    const x = padding + (index / (history.length - 1 || 1)) * (width - 2 * padding);
    const y = height - padding - (d.map50) * (height - 2 * padding);
    return `${x},${y}`;
  }).join(" ");
  
  let mapDots = "";
  let mapLabels = "";
  
  history.forEach((d, i) => {
    const x = padding + (i / (history.length - 1 || 1)) * (width - 2 * padding);
    const y = height - padding - (d.map50) * (height - 2 * padding);
    mapDots += `<circle cx="${x}" cy="${y}" r="4" fill="var(--primary-dark)" stroke="var(--bg-surface)" stroke-width="1" />`;
    mapLabels += `<text x="${x}" y="${height - 5}" fill="var(--text-muted)" font-size="9" text-anchor="middle">E${d.epoch}</text>`;
  });
  
  mapChartContainer.innerHTML = `
    <svg width="100%" height="150px" viewBox="0 0 ${width} ${height}" style="overflow: visible;">
      <line x1="${padding}" y1="${padding}" x2="${width - padding}" y2="${padding}" stroke="var(--border-default)" />
      <line x1="${padding}" y1="${height/2}" x2="${width - padding}" y2="${height/2}" stroke="var(--border-default)" />
      <line x1="${padding}" y1="${height - padding}" x2="${width - padding}" y2="${height - padding}" stroke="var(--border-strong)" />
      
      <polyline fill="none" stroke="var(--primary)" stroke-width="3" points="${pointsMap}" />
      ${mapDots}
      
      <text x="${padding - 5}" y="${padding + 5}" fill="var(--text-muted)" font-size="10" text-anchor="end">1.0</text>
      <text x="${padding - 5}" y="${height - padding + 5}" fill="var(--text-muted)" font-size="10" text-anchor="end">0.0</text>
      ${mapLabels}
    </svg>
  `;
}

// --- TERMINAL LOGS RENDERER ---
function renderLogs() {
  terminalScreen.innerHTML = "";
  
  if (activeJob && activeJob.logs && activeJob.logs.length > 0) {
    activeJob.logs.forEach(log => {
      const line = document.createElement("div");
      line.innerText = log;
      terminalScreen.appendChild(line);
    });
    
    // Auto scroll to bottom
    terminalScreen.scrollTop = terminalScreen.scrollHeight;
  } else {
    terminalScreen.innerHTML = `
      <div class="color-muted text-center pt-xl">
        Terminal Idle. Launch a DDP training job to view stdout logs.
      </div>
    `;
  }
}
