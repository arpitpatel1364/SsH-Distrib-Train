// --- ENTERPRISE DISTRIBUTED YOLO CLUSTER ORCHESTRATOR VANILLA JS ENGINE ---

// --- 1. CENTRAL STATE MANAGEMENT ---
let token = localStorage.getItem("token") || "";
let theme = localStorage.getItem("theme") || "dark";
let nodes = [];
let activeJob = null;
let historicalMetrics = []; // stores last 20 ticks of averaged metrics
let wsConnected = false;
let ws = null;
let reconnectTimer = null;
let otaTimer = null;
let deleteNodeIdPending = null;
let restInterval = null;

const API_BASE = `${window.location.protocol}//${window.location.hostname}:8000`;

// --- 2. CENTRAL ICON SYSTEM (INLINE SVG MARKUP ONLY) ---
const Icons = {
  Dashboard: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg>`,
  Nodes: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="2" width="20" height="8" rx="2" ry="2"/><rect x="2" y="14" width="20" height="8" rx="2" ry="2"/><line x1="6" y1="6" x2="6.01" y2="6"/><line x1="6" y1="18" x2="6.01" y2="18"/></svg>`,
  Training: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 3a3 3 0 0 0-3 3v12a3 3 0 0 0 3 3 3 3 0 0 0 3-3V6a3 3 0 0 0-3-3z"/><path d="M6 3a3 3 0 0 0-3 3v12a3 3 0 0 0 3 3 3 3 0 0 0 3-3V6a3 3 0 0 0-3-3z"/><path d="M10 6h4"/><path d="M10 18h4"/></svg>`,
  Monitor: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>`,
  Logs: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>`,
  History: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>`,
  Ota: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"/></svg>`,
  Settings: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>`,
  Server: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="2" width="20" height="8" rx="2" ry="2"/><rect x="2" y="14" width="20" height="8" rx="2" ry="2"/><line x1="6" y1="6" x2="6.01" y2="6"/><line x1="6" y1="18" x2="6.01" y2="18"/></svg>`,
  Gpu: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M9 1v3M15 1v3M9 20v3M15 20v3M20 9h3M20 15h3M1 9h3M1 15h3"/></svg>`,
  Activity: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>`,
  X: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>`,
  Trash: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg>`,
  Refresh: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"/></svg>`,
  AlertCircle: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>`,
  CheckCircle: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>`,
  Play: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg>`,
  Square: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/></svg>`,
  Download: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>`,
  ChevronRight: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg>`,
  Sun: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>`,
  Moon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>`,
  RotateCw: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>`,
  RefreshCw: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>`,
  UploadCloud: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="16 16 12 12 8 16"/><line x1="12" y1="12" x2="12" y2="21"/><path d="M20.39 18.39A5 5 0 0 0 18 9h-1.26A8 8 0 1 0 3 16.3"/></svg>`,
  Zap: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>`,
  UserPlus: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="8.5" cy="7" r="4"/><line x1="20" y1="8" x2="20" y2="14"/><line x1="23" y1="11" x2="17" y2="11"/></svg>`
};

function renderIcons() {
  document.querySelectorAll("[data-icon]").forEach(el => {
    const iconName = el.getAttribute("data-icon");
    if (Icons[iconName]) {
      el.innerHTML = Icons[iconName];
    }
  });
}

// --- 3. DOM ELEMENT CACHE ---
const elements = {
  initialLoading: document.getElementById("initial-loading"),
  loginScreen: document.getElementById("login-screen"),
  appLayout: document.getElementById("app-layout"),
  loginForm: document.getElementById("login-form"),
  usernameInput: document.getElementById("username"),
  passwordInput: document.getElementById("password"),
  authError: document.getElementById("auth-error"),

  wsStatusDot: document.getElementById("ws-status-dot"),
  wsStatusText: document.getElementById("ws-status-text"),
  btnThemeToggle: document.getElementById("btn-theme-toggle"),
  btnLogout: document.getElementById("btn-logout"),
  pageTitle: document.getElementById("page-title"),

  // Dashboard Views
  statClusterStatus: document.getElementById("stat-cluster-status"),
  statConnectedNodes: document.getElementById("stat-connected-nodes"),
  statActiveGpus: document.getElementById("stat-active-gpus"),
  statRunningJobs: document.getElementById("stat-running-jobs"),
  dashboardNodesList: document.getElementById("dashboard-nodes-list"),
  dashboardActiveJobContainer: document.getElementById("dashboard-active-job-container"),
  chartUtilization: document.getElementById("chart-utilization"),
  chartTemperature: document.getElementById("chart-temperature"),
  btnRefreshNodes: document.getElementById("btn-refresh-nodes"),

  // Node registration & list
  addNodeFormReal: document.getElementById("add-node-form-real"),
  nodeIpInput: document.getElementById("node-ip-input"),
  nodeUserInput: document.getElementById("node-user-input"),
  nodePortInput: document.getElementById("node-port-input"),
  nodePasswordInput: document.getElementById("node-password-input"),
  nodeInstallKeyToggle: document.getElementById("node-install-key-toggle"),
  nodeSyncCodeToggle: document.getElementById("node-sync-code-toggle"),
  nodeMessageError: document.getElementById("node-message-error"),
  btnSubmitNode: document.getElementById("btn-submit-node"),
  nodesGridTitle: document.getElementById("nodes-grid-title"),
  clusterNodesGridContainer: document.getElementById("cluster-nodes-grid-container"),

  // Launch training View
  launchTrainingForm: document.getElementById("launch-training-form"),
  jobModel: document.getElementById("job-model"),
  jobDataset: document.getElementById("job-dataset"),
  jobEpochs: document.getElementById("job-epochs"),
  jobBatch: document.getElementById("job-batch"),
  jobLr: document.getElementById("job-lr"),
  jobLaunchError: document.getElementById("job-launch-error"),
  btnLaunchDdp: document.getElementById("btn-launch-ddp"),
  trainingJobDetailsPane: document.getElementById("training-job-details-pane"),

  // Monitor large views
  monitorUtilizationChart: document.getElementById("monitor-utilization-chart"),
  monitorTemperatureChart: document.getElementById("monitor-temperature-chart"),

  // Logs view
  logsAutoscroll: document.getElementById("logs-autoscroll"),
  btnClearLogs: document.getElementById("btn-clear-logs"),
  logsConsole: document.getElementById("logs-console"),

  // History table
  historyTableBody: document.getElementById("history-table-body"),
  historyPagination: document.getElementById("history-pagination"),

  // OTA Page
  otaNodesGrid: document.getElementById("ota-nodes-grid"),
  otaDefaultRemotePath: document.getElementById("ota-default-remote-path"),
  otaLocalDir: document.getElementById("ota-local-dir"),
  otaGlobalFeedback: document.getElementById("ota-global-feedback"),
  btnOtaDeployAll: document.getElementById("btn-ota-deploy-all"),
  btnOtaSyncAll: document.getElementById("btn-ota-sync-all"),
  btnOtaValidate: document.getElementById("btn-ota-validate"),
  btnOtaRefreshList: document.getElementById("btn-ota-refresh-list"),
  otaLogModal: document.getElementById("ota-log-modal"),
  otaLogBody: document.getElementById("ota-log-body"),
  otaLogModalTitle: document.getElementById("ota-log-modal-title"),
  otaLogModalSubtitle: document.getElementById("ota-log-modal-subtitle"),
  btnCloseOtaLog: document.getElementById("btn-close-ota-log"),

  // Package Worker
  btnPackageWorker: document.getElementById("btn-package-worker"),
  btnPackageWorkerLabel: document.getElementById("btn-package-worker-label"),
  pkgStatusError: document.getElementById("pkg-status-error"),
  pkgStatusSuccess: document.getElementById("pkg-status-success"),

  // Settings view
  settingsBackendHost: document.getElementById("settings-backend-host"),

  // Modals
  confirmDeleteModal: document.getElementById("confirm-delete-modal"),
  deleteModalTitle: document.getElementById("delete-modal-title"),
  deleteModalBodyText: document.getElementById("delete-modal-body-text"),
  btnCloseDeleteModal: document.getElementById("btn-close-delete-modal"),
  btnCancelDelete: document.getElementById("btn-cancel-delete"),
  btnConfirmDelete: document.getElementById("btn-confirm-delete")
};

// --- 4. INITIALIZATION ROUTINE ---
document.addEventListener("DOMContentLoaded", () => {
  initTheme();
  setupNavigation();
  setupEventListeners();
  checkAuth();

  // Setup Settings
  if (elements.settingsBackendHost) {
    elements.settingsBackendHost.textContent = API_BASE;
  }
});

// --- 5. THEME SWITCHER ---
function initTheme() {
  document.documentElement.setAttribute("data-theme", theme);
  if (elements.btnThemeToggle) {
    // In dark mode show Sun (to switch to light), in light mode show Moon (to switch to dark)
    elements.btnThemeToggle.innerHTML = theme === "dark"
      ? '<span class="icon-slot" data-icon="Sun"></span>'
      : '<span class="icon-slot" data-icon="Moon"></span>';
    elements.btnThemeToggle.title = theme === "dark" ? "Switch to Light Mode" : "Switch to Dark Mode";
    renderIcons();
  }
}

function toggleTheme() {
  theme = theme === "dark" ? "light" : "dark";
  localStorage.setItem("theme", theme);
  initTheme();
}

// --- 6. NAVIGATION ROUTING SYSTEM ---
function setupNavigation() {
  document.querySelectorAll(".nav-item").forEach(button => {
    button.addEventListener("click", () => {
      const targetView = button.getAttribute("data-view");

      // Update sidebar visual active states
      document.querySelectorAll(".nav-item").forEach(b => b.classList.remove("active"));
      button.classList.add("active");

      // Switch screen visibility
      document.querySelectorAll(".view-section").forEach(view => {
        if (view.id === `view-${targetView}`) {
          view.classList.remove("hidden");
        } else {
          view.classList.add("hidden");
        }
      });

      // Update browser tab header title
      let title = "Cluster Dashboard";
      if (targetView === "nodes") title = "Cluster Node Registry";
      if (targetView === "training") title = "Deploy DDP Training Job";
      if (targetView === "monitor") title = "Telemetry Monitor Console";
      if (targetView === "logs") title = "System Output Terminal";
      if (targetView === "history") title = "Executed Run Database";
      if (targetView === "ota") title = "OTA Node Updates";
      if (targetView === "settings") title = "System Settings Configuration";

      elements.pageTitle.textContent = title;

      // Hook special initial fetches
      if (targetView === "history") fetchJobHistory();
      if (targetView === "ota") loadOtaNodes();
    });
  });
}

// --- 7. EVENT LISTENERS HOOKS ---
function setupEventListeners() {
  if (elements.btnThemeToggle) elements.btnThemeToggle.addEventListener("click", toggleTheme);
  if (elements.btnLogout) elements.btnLogout.addEventListener("click", handleLogout);

  // Forms
  if (elements.loginForm) elements.loginForm.addEventListener("submit", handleLogin);
  if (elements.addNodeFormReal) elements.addNodeFormReal.addEventListener("submit", handleAddNode);
  if (elements.launchTrainingForm) elements.launchTrainingForm.addEventListener("submit", handleLaunchTraining);

  const btnTestCluster = document.getElementById("btn-test-cluster");
  if (btnTestCluster) btnTestCluster.addEventListener("click", handleTestCluster);

  // Actions
  if (elements.btnRefreshNodes) elements.btnRefreshNodes.addEventListener("click", triggerNodesRefresh);
  if (elements.btnClearLogs) {
    elements.btnClearLogs.addEventListener("click", () => {
      elements.logsConsole.innerHTML = "";
    });
  }
  // OTA bulk buttons
  const btnRefreshHistory = document.getElementById("btn-refresh-history");
  if (btnRefreshHistory) btnRefreshHistory.addEventListener("click", fetchJobHistory);

  // Status filter pills
  document.querySelectorAll("#history-filter-bar .filter-pill").forEach(pill => {
    pill.addEventListener("click", () => {
      document.querySelectorAll("#history-filter-bar .filter-pill").forEach(p => p.classList.remove("active"));
      pill.classList.add("active");
      historyActiveFilter = pill.getAttribute("data-filter");
      historyCurrentPage = 1;
      renderHistoryPage();
    });
  });

  if (elements.btnOtaDeployAll) elements.btnOtaDeployAll.addEventListener("click", otaDeployAll);
  if (elements.btnOtaSyncAll) elements.btnOtaSyncAll.addEventListener("click", otaSyncAll);
  if (elements.btnOtaValidate) elements.btnOtaValidate.addEventListener("click", otaValidatePaths);
  if (elements.btnOtaRefreshList) elements.btnOtaRefreshList.addEventListener("click", loadOtaNodes);
  if (elements.btnCloseOtaLog) elements.btnCloseOtaLog.addEventListener("click", closeOtaLogModal);
  if (elements.btnPackageWorker) elements.btnPackageWorker.addEventListener("click", packageWorker);

  // Modal buttons
  if (elements.btnCloseDeleteModal) elements.btnCloseDeleteModal.addEventListener("click", closeDeleteModal);
  if (elements.btnCancelDelete) elements.btnCancelDelete.addEventListener("click", closeDeleteModal);
  if (elements.btnConfirmDelete) elements.btnConfirmDelete.addEventListener("click", handleConfirmDeleteNode);

  // Initial svg loading icon triggers
  renderIcons();
}

// --- 8. AUTHENTICATION & SESSION HANDLING ---
function checkAuth() {
  // Hide loading spinner first
  if (elements.initialLoading) {
    elements.initialLoading.style.opacity = "0";
    setTimeout(() => {
      elements.initialLoading.classList.add("hidden");
    }, 300);
  }

  if (token) {
    elements.loginScreen.classList.add("hidden");
    elements.appLayout.classList.remove("hidden");
    initWebSocket();
  } else {
    elements.loginScreen.classList.remove("hidden");
    elements.appLayout.classList.add("hidden");
    if (ws) {
      ws.close();
    }
  }
}

async function handleLogin(e) {
  e.preventDefault();
  elements.authError.classList.add("hidden");

  const username = elements.usernameInput.value.trim();
  const password = elements.passwordInput.value;

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
      elements.usernameInput.value = "";
      elements.passwordInput.value = "";
      checkAuth();
    } else {
      elements.authError.textContent = data.detail || "Authentication credentials rejected.";
      elements.authError.classList.remove("hidden");
    }
  } catch (err) {
    elements.authError.textContent = "Error: Cannot reach orchestrator API server.";
    elements.authError.classList.remove("hidden");
  }
}

function handleLogout() {
  token = "";
  localStorage.removeItem("token");
  nodes = [];
  activeJob = null;
  historicalMetrics = [];
  if (restInterval) {
    clearInterval(restInterval);
    restInterval = null;
  }
  checkAuth();
}

// --- 9. WEBSOCKET REAL-TIME DUPLEX METRICS & REST FALLBACK ---
function initWebSocket() {
  if (ws) {
    ws.close();
  }

  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  ws = new WebSocket(`${protocol}//${window.location.hostname}:8000/ws/stream`);

  ws.onopen = () => {
    wsConnected = true;
    updateWsUI();
    if (restInterval) {
      clearInterval(restInterval);
      restInterval = null;
    }
  };

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      if (data.nodes) {
        nodes = data.nodes;
        processTelemetryHeartbeat();
        renderNodesGrid();
        renderDashboardNodes();
      }

      if (data.active_job) {
        activeJob = data.active_job;
        renderActiveJobPanel();
        if (data.active_job.logs) {
          appendLogsToConsole(data.active_job.logs);
        }
      } else {
        activeJob = null;
        renderActiveJobPanel();
      }

      updateStatistics();
      renderIcons();
    } catch (err) {
      console.error("Error processing cluster metrics payload: ", err);
    }
  };

  ws.onclose = () => {
    wsConnected = false;
    updateWsUI();
    startRestPolling();

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
    elements.wsStatusDot.className = "indicator-dot connected";
    elements.wsStatusText.textContent = "STREAM LIVE";
    elements.wsStatusText.className = "font-semibold text-xs color-success";
  } else {
    elements.wsStatusDot.className = "indicator-dot disconnected";
    elements.wsStatusText.textContent = "OFFLINE POLLING";
    elements.wsStatusText.className = "font-semibold text-xs color-danger";
  }
}

function startRestPolling() {
  if (restInterval) return; // already active

  restInterval = setInterval(async () => {
    if (wsConnected) {
      clearInterval(restInterval);
      restInterval = null;
      return;
    }
    await pollStatusREST();
  }, 5000);

  // trigger one immediate poll
  pollStatusREST();
}

async function pollStatusREST() {
  if (!token) return;

  try {
    // 1. Fetch cluster nodes
    const nodesRes = await fetch(`${API_BASE}/nodes/`, {
      headers: { "Authorization": `Bearer ${token}` }
    });
    if (!nodesRes.ok) {
      if (nodesRes.status === 401) {
        handleLogout();
        return;
      }
      throw new Error("HTTP " + nodesRes.status);
    }

    nodes = await nodesRes.json();
    processTelemetryHeartbeat();
    renderNodesGrid();
    renderDashboardNodes();

    // 2. Fetch jobs list to locate any running / pending DDP tasks
    const jobsRes = await fetch(`${API_BASE}/train/jobs`, {
      headers: { "Authorization": `Bearer ${token}` }
    });

    if (!jobsRes.ok) {
      if (jobsRes.status === 401) {
        handleLogout();
        return;
      }
      throw new Error("HTTP " + jobsRes.status);
    }

    if (jobsRes.ok) {
      const jobs = await jobsRes.json();
      const runningJob = jobs.find(j => j.status === "running" || j.status === "pending");

      if (runningJob) {
        let logs = [];
        let metrics_history = [];

        // Fetch logs
        try {
          const logsRes = await fetch(`${API_BASE}/train/jobs/${runningJob.id}/logs`, {
            headers: { "Authorization": `Bearer ${token}` }
          });
          if (logsRes.ok) {
            const logsData = await logsRes.json();
            logs = logsData.logs || [];
          }
        } catch (e) {
          console.warn("Could not retrieve active job logs: ", e);
        }

        // Fetch metrics history
        try {
          const metricsRes = await fetch(`${API_BASE}/train/jobs/${runningJob.id}/metrics`, {
            headers: { "Authorization": `Bearer ${token}` }
          });
          if (metricsRes.ok) {
            const metricsData = await metricsRes.json();
            metrics_history = metricsData.map(m => ({
              epoch: m.epoch,
              box_loss: m.box_loss,
              cls_loss: m.cls_loss,
              dfl_loss: m.dfl_loss,
              map50: m.map50,
              map50_95: m.map50_95
            }));
          }
        } catch (e) {
          console.warn("Could not retrieve active job metrics: ", e);
        }

        activeJob = {
          ...runningJob,
          logs,
          metrics_history
        };

        renderActiveJobPanel();
        appendLogsToConsole(logs);
      } else {
        activeJob = null;
        renderActiveJobPanel();
      }
    }

    updateStatistics();
    renderIcons();
  } catch (err) {
    console.warn("REST fallback polling failure: ", err);
  }
}

// --- 10. TELEMETRY ACCUMULATION & CUSTOM DRAWING ---
function processTelemetryHeartbeat() {
  // Calculate average gpu and vram metrics across active nodes
  const activeNodesList = nodes.filter(n => n.status !== "failed" && n.status !== "offline");
  let totalGpu = 0;
  let totalVram = 0;
  let count = 0;

  activeNodesList.forEach(node => {
    if (node.latest_metric) {
      totalGpu += node.latest_metric.gpu_util[0] || 0;
      totalVram += node.latest_metric.vram_util[0] || 0;
      count++;
    }
  });

  const avgGpu = count > 0 ? Math.round(totalGpu / count) : 0;
  const avgVram = count > 0 ? Math.round(totalVram / count) : 0;
  const timestamp = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });

  // Append to historical metrics array
  historicalMetrics.push({ timestamp, gpu: avgGpu, vram: avgVram });
  if (historicalMetrics.length > 20) {
    historicalMetrics.shift();
  }

  // Render Custom SVG charts
  drawUtilizationChart(elements.chartUtilization, historicalMetrics);
  drawUtilizationChart(elements.monitorUtilizationChart, historicalMetrics);

  drawTemperatureChart(elements.chartTemperature, nodes);
  drawTemperatureChart(elements.monitorTemperatureChart, nodes);
}

function updateStatistics() {
  // 1. Cluster status
  const totalCount = nodes.length;
  const connectedCount = nodes.filter(n => n.status === "active" || n.status === "training").length;

  let statusText = "INACTIVE";
  if (activeJob) {
    statusText = "TRAINING DDP";
  } else if (connectedCount > 0) {
    statusText = "HEALTHY";
  }

  elements.statClusterStatus.textContent = statusText;
  elements.statConnectedNodes.textContent = `${connectedCount} / ${totalCount}`;

  // 2. Active GPUs
  let totalGpus = 0;
  nodes.forEach(n => {
    totalGpus += n.gpu_count || 0;
  });
  elements.statActiveGpus.textContent = totalGpus;

  // 3. Running jobs
  if (activeJob) {
    elements.statRunningJobs.textContent = activeJob.id.substring(0, 8);
    elements.statRunningJobs.className = "stat-val color-warning";
  } else {
    elements.statRunningJobs.textContent = "NONE";
    elements.statRunningJobs.className = "stat-val color-primary";
  }
}

// --- 11. CUSTOM SVG AREA CHART RENDERING (LIBRARY FREE) ---
function drawUtilizationChart(container, data) {
  if (!container) return;
  const width = container.clientWidth || 450;
  const height = 200;
  const paddingLeft = 40;
  const paddingRight = 16;
  const paddingTop = 20;
  const paddingBottom = 30;

  const chartWidth = width - paddingLeft - paddingRight;
  const chartHeight = height - paddingTop - paddingBottom;

  if (data.length === 0) {
    container.innerHTML = `
      <div style="height:100%; display:flex; align-items:center; justify-content:center; color:var(--text-muted); font-size:var(--text-sm);">
        Awaiting cluster telemetry heartbeats...
      </div>
    `;
    return;
  }

  // Calculate SVG paths
  const maxPoints = 20;
  const dx = chartWidth / (maxPoints - 1);

  let gpuPoints = [];
  let vramPoints = [];

  // Pad data with 0s if it has less than 20 elements, to maintain chart width integrity
  const paddedData = [];
  for (let i = 0; i < maxPoints - data.length; i++) {
    paddedData.push({ gpu: 0, vram: 0 });
  }
  paddedData.push(...data);

  paddedData.forEach((d, index) => {
    const x = paddingLeft + index * dx;
    const yGpu = paddingTop + chartHeight - (d.gpu / 100) * chartHeight;
    const yVram = paddingTop + chartHeight - (d.vram / 100) * chartHeight;
    gpuPoints.push({ x, y: yGpu });
    vramPoints.push({ x, y: yVram });
  });

  // Generate Line & Area paths
  let linePathGpu = `M ${gpuPoints[0].x} ${gpuPoints[0].y} `;
  let areaPathGpu = `M ${gpuPoints[0].x} ${paddingTop + chartHeight} L ${gpuPoints[0].x} ${gpuPoints[0].y} `;

  let linePathVram = `M ${vramPoints[0].x} ${vramPoints[0].y} `;
  let areaPathVram = `M ${vramPoints[0].x} ${paddingTop + chartHeight} L ${vramPoints[0].x} ${vramPoints[0].y} `;

  for (let i = 1; i < gpuPoints.length; i++) {
    linePathGpu += `L ${gpuPoints[i].x} ${gpuPoints[i].y} `;
    areaPathGpu += `L ${gpuPoints[i].x} ${gpuPoints[i].y} `;

    linePathVram += `L ${vramPoints[i].x} ${vramPoints[i].y} `;
    areaPathVram += `L ${vramPoints[i].x} ${vramPoints[i].y} `;
  }

  areaPathGpu += `L ${gpuPoints[gpuPoints.length - 1].x} ${paddingTop + chartHeight} Z`;
  areaPathVram += `L ${vramPoints[vramPoints.length - 1].x} ${paddingTop + chartHeight} Z`;

  // Build Grid lines
  let gridLines = "";
  for (let p = 0; p <= 100; p += 25) {
    const yVal = paddingTop + chartHeight - (p / 100) * chartHeight;
    gridLines += `
      <line x1="${paddingLeft}" y1="${yVal}" x2="${width - paddingRight}" y2="${yVal}" stroke="var(--border-default)" stroke-dasharray="3,3" />
      <text x="${paddingLeft - 10}" y="${yVal + 4}" fill="var(--text-muted)" font-size="10px" text-anchor="end">${p}%</text>
    `;
  }

  // Time labels (render every 4th point)
  let timeLabels = "";
  paddedData.forEach((d, index) => {
    if (index % 4 === 0 && d.timestamp) {
      const x = paddingLeft + index * dx;
      timeLabels += `
        <text x="${x}" y="${height - 10}" fill="var(--text-muted)" font-size="10px" text-anchor="middle">${d.timestamp}</text>
      `;
    }
  });

  container.innerHTML = `
    <svg width="100%" height="100%" viewBox="0 0 ${width} ${height}" style="overflow:visible;">
      <defs>
        <linearGradient id="gpuGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="var(--primary)" stop-opacity="0.25"/>
          <stop offset="100%" stop-color="var(--primary)" stop-opacity="0.00"/>
        </linearGradient>
        <linearGradient id="vramGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="var(--info)" stop-opacity="0.25"/>
          <stop offset="100%" stop-color="var(--info)" stop-opacity="0.00"/>
        </linearGradient>
      </defs>
      
      <!-- Grid -->
      ${gridLines}
      
      <!-- GPU Area & Line -->
      <path d="${areaPathGpu}" fill="url(#gpuGrad)" />
      <path d="${linePathGpu}" fill="none" stroke="var(--primary)" stroke-width="2" />
      
      <!-- VRAM Area & Line -->
      <path d="${areaPathVram}" fill="url(#vramGrad)" />
      <path d="${linePathVram}" fill="none" stroke="var(--info)" stroke-width="2" />
      
      <!-- X-axis timeline labels -->
      ${timeLabels}
    </svg>
  `;
}

// --- 12. CUSTOM BAR CHART FOR TEMPERATURES ---
function drawTemperatureChart(container, nodeList) {
  if (!container) return;
  const width = container.clientWidth || 450;
  const height = 200;
  const paddingLeft = 40;
  const paddingRight = 16;
  const paddingTop = 20;
  const paddingBottom = 30;

  const chartWidth = width - paddingLeft - paddingRight;
  const chartHeight = height - paddingTop - paddingBottom;

  // Filter only connected nodes
  const activeNodes = nodeList.filter(n => n.status !== "failed" && n.status !== "offline");

  if (activeNodes.length === 0) {
    container.innerHTML = `
      <div style="height:100%; display:flex; align-items:center; justify-content:center; color:var(--text-muted); font-size:var(--text-sm);">
        No connected cluster nodes online to profile.
      </div>
    `;
    return;
  }

  // Grid Lines
  let gridLines = "";
  for (let t = 0; t <= 100; t += 25) {
    const yVal = paddingTop + chartHeight - (t / 100) * chartHeight;
    gridLines += `
      <line x1="${paddingLeft}" y1="${yVal}" x2="${width - paddingRight}" y2="${yVal}" stroke="var(--border-default)" stroke-dasharray="3,3" />
      <text x="${paddingLeft - 10}" y="${yVal + 4}" fill="var(--text-muted)" font-size="10px" text-anchor="end">${t}°C</text>
    `;
  }

  // Draw bars
  const barWidth = Math.min(32, (chartWidth / activeNodes.length) * 0.5);
  const barSpacing = (chartWidth - barWidth * activeNodes.length) / (activeNodes.length + 1);

  let barsMarkup = "";
  activeNodes.forEach((node, index) => {
    const x = paddingLeft + barSpacing + index * (barWidth + barSpacing);
    const tempVal = (node.latest_metric && node.latest_metric.temp) ? node.latest_metric.temp[0] : 0;
    const barHeight = (tempVal / 100) * chartHeight;
    const y = paddingTop + chartHeight - barHeight;

    // Threshold colors
    let barColor = "var(--success)";
    if (tempVal >= 80) {
      barColor = "var(--danger)";
    } else if (tempVal >= 60) {
      barColor = "var(--warning)";
    }

    // Node Label last IP octet
    const octets = node.ip.split(".");
    const label = octets[octets.length - 1] || "node";

    barsMarkup += `
      <!-- Bar Rect -->
      <rect x="${x}" y="${y}" width="${barWidth}" height="${barHeight}" fill="${barColor}" rx="3" />
      <!-- Value Text -->
      <text x="${x + barWidth / 2}" y="${y - 6}" fill="var(--text-primary)" font-size="10px" font-weight="600" text-anchor="middle">${tempVal}°C</text>
      <!-- Label IP -->
      <text x="${x + barWidth / 2}" y="${height - 10}" fill="var(--text-muted)" font-size="10px" font-family="var(--font-mono)" text-anchor="middle">.${label}</text>
    `;
  });

  container.innerHTML = `
    <svg width="100%" height="100%" viewBox="0 0 ${width} ${height}" style="overflow:visible;">
      ${gridLines}
      ${barsMarkup}
    </svg>
  `;
}

// --- 13. CLUSTER NODES UI RENDERING ---
function renderDashboardNodes() {
  if (!elements.dashboardNodesList) return;
  elements.dashboardNodesList.innerHTML = "";

  if (nodes.length === 0) {
    elements.dashboardNodesList.innerHTML = `
      <div class="p-md text-center color-muted text-xs">
        No registered cluster targets. Go to the "Cluster Nodes" view to add one.
      </div>
    `;
    return;
  }

  nodes.forEach(node => {
    let statusClass = "badge-offline";
    if (node.status === "active") statusClass = "badge-active";
    if (node.status === "training") statusClass = "badge-training";
    if (node.status === "failed") statusClass = "badge-failed";

    const gCount = node.gpu_count || 0;
    const gInfo = node.gpu_info.join(", ") || "CPU";

    const div = document.createElement("div");
    div.className = "node-item-mini";
    div.innerHTML = `
      <div class="flex-col">
        <span class="font-semibold text-sm color-primary">${node.ip}</span>
        <span class="text-xs color-muted mt-xs">${gCount}x ${gInfo} • Port ${node.ssh_port}</span>
      </div>
      <span class="badge ${statusClass}">${node.status}</span>
    `;
    elements.dashboardNodesList.appendChild(div);
  });
}

function renderNodesGrid() {
  if (!elements.clusterNodesGridContainer) return;
  elements.clusterNodesGridContainer.innerHTML = "";

  elements.nodesGridTitle.textContent = `Registered Nodes (${nodes.length})`;

  if (nodes.length === 0) {
    elements.clusterNodesGridContainer.innerHTML = `
      <div class="col-12 p-xl text-center color-muted text-sm">
        No nodes configured. Enter connection parameters on the left to spawn nodes.
      </div>
    `;
    return;
  }

  nodes.forEach(node => {
    const isOffline = node.status === "offline" || node.status === "failed";
    const gpuUtil = (!isOffline && node.latest_metric) ? node.latest_metric.gpu_util[0] || 0 : 0;
    const vramUtil = (!isOffline && node.latest_metric) ? node.latest_metric.vram_util[0] || 0 : 0;
    const temp = (!isOffline && node.latest_metric) ? node.latest_metric.temp[0] || 0 : 0;

    // Status border colors
    let cardLeftColor = "var(--border-strong)";
    let statusClass = "badge-offline";
    if (node.status === "active") {
      cardLeftColor = "var(--success)";
      statusClass = "badge-active";
    } else if (node.status === "training") {
      cardLeftColor = "var(--warning)";
      statusClass = "badge-training";
    } else if (node.status === "failed") {
      cardLeftColor = "var(--danger)";
      statusClass = "badge-failed";
    }

    // Metric progress bars threshold styling
    const gpuColor = gpuUtil > 80 ? "var(--danger)" : (gpuUtil > 50 ? "var(--warning)" : "var(--primary)");
    const vramColor = vramUtil > 80 ? "var(--danger)" : (vramUtil > 50 ? "var(--warning)" : "var(--primary)");

    const card = document.createElement("div");
    card.className = "glass-card flex-col gap-md";
    card.style.borderLeft = `4px solid ${cardLeftColor}`;
    card.style.padding = "20px";

    card.innerHTML = `
      <div class="flex-row justify-between align-center">
        <div class="flex-col">
          <span class="font-semibold text-sm color-primary">${node.ip}</span>
          <span class="text-xs color-muted mt-xs">${node.ssh_user}@${node.ip}:${node.ssh_port}</span>
        </div>
        <span class="badge ${statusClass}">${node.status}</span>
      </div>
      
      <div class="node-metrics-box">
        <div class="flex-col gap-xs">
          <div class="metric-row text-xs color-secondary">
            <span>GPU Utilization</span>
            <span class="font-semibold">${gpuUtil}%</span>
          </div>
          <div class="metric-progress-bg">
            <div class="metric-progress-bar" style="width: ${gpuUtil}%; background: ${gpuColor};"></div>
          </div>
        </div>
        
        <div class="flex-col gap-xs mt-sm">
          <div class="metric-row text-xs color-secondary">
            <span>VRAM Utilization</span>
            <span class="font-semibold">${vramUtil}%</span>
          </div>
          <div class="metric-progress-bg">
            <div class="metric-progress-bar" style="width: ${vramUtil}%; background: ${vramColor};"></div>
          </div>
        </div>
        
        <div class="flex-row justify-between text-xs color-muted mt-sm">
          <span>Core Temperature:</span>
          <span class="font-semibold color-primary">${isOffline ? "-" : temp + "°C"}</span>
        </div>
      </div>
      
      <div class="node-card-footer" style="display: flex; justify-content: space-between; align-items: center; margin-top: auto; padding-top: 10px; border-top: 1px solid var(--border-subtle);">
        <div style="display:flex; gap:6px;">
          <button class="btn-icon btn-icon-success" onclick="startWorkerOnNode(${node.id}, '${node.ip}')" id="btn-start-worker-${node.id}" title="Start Worker">
            <span class="icon-slot" data-icon="Play"></span>
          </button>
          <button class="btn-icon btn-icon-danger" onclick="stopWorkerOnNode(${node.id}, '${node.ip}')" id="btn-stop-worker-${node.id}" title="Stop Worker">
            <span class="icon-slot" data-icon="Square"></span>
          </button>
          <button class="btn-icon btn-icon-warning" onclick="restartWorkerOnNode(${node.id}, '${node.ip}')" id="btn-restart-worker-${node.id}" title="Restart Worker">
            <span class="icon-slot" data-icon="RotateCw"></span>
          </button>
          <button class="btn-icon btn-icon-info" onclick="checkWorkerStatus(${node.id}, '${node.ip}')" id="btn-status-worker-${node.id}" title="Check Status">
            <span class="icon-slot" data-icon="Activity"></span>
          </button>
        </div>
        <button class="btn-icon btn-icon-danger" onclick="confirmDeleteNode(${node.id}, '${node.ip}')" title="Delete Node">
          <span class="icon-slot" data-icon="Trash"></span>
        </button>
      </div>
    `;

    elements.clusterNodesGridContainer.appendChild(card);
  });

  // Re-render icons for newly added dynamic elements
  renderIcons();
}

// --- Start / Stop Worker Agent on remote node via SSH ---
async function startWorkerOnNode(nodeId, nodeIp) {
  // Ask user for master URL, pre-fill with current origin
  const defaultUrl = `${window.location.protocol}//${window.location.hostname}:8000`;
  const masterUrl = prompt(
    `Start worker agent on ${nodeIp}\n\nEnter the Master Orchestrator URL this node should connect to:`,
    defaultUrl
  );
  if (!masterUrl || !masterUrl.trim()) return;

  const btn = document.getElementById(`btn-start-worker-${nodeId}`);
  if (btn) { btn.textContent = "Starting…"; btn.disabled = true; }

  try {
    const res = await fetch(`${API_BASE}/nodes/${nodeId}/start-worker`, {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${token}`,
        "Content-Type": "application/json"
      },
      body: JSON.stringify({ master_url: masterUrl.trim() })
    });
    const data = await res.json();
    if (res.ok) {
      alert(`✅ Worker agent started on ${nodeIp}\nLogs: ${data.log_file}\nConnecting to: ${data.master_url}`);
    } else {
      alert(`❌ Failed to start worker on ${nodeIp}:\n${data.detail || JSON.stringify(data)}`);
    }
  } catch (err) {
    alert(`❌ Network error: ${err.message}`);
  } finally {
    if (btn) { btn.textContent = "Start"; btn.disabled = false; }
  }
}

async function stopWorkerOnNode(nodeId, nodeIp) {
  const btn = document.getElementById(`btn-stop-worker-${nodeId}`);
  if (btn) { btn.textContent = "Stopping…"; btn.disabled = true; }

  try {
    const res = await fetch(`${API_BASE}/nodes/${nodeId}/stop-worker`, {
      method: "POST",
      headers: { "Authorization": `Bearer ${token}` }
    });
    const data = await res.json();
    if (res.ok) {
      alert(`✅ Worker stopped on ${nodeIp}`);
      triggerSingleNodeRefresh(nodeId);
    } else {
      alert(`❌ Failed to stop worker on ${nodeIp}:\n${data.detail || JSON.stringify(data)}`);
    }
  } catch (err) {
    alert(`❌ Network error: ${err.message}`);
  } finally {
    if (btn) { btn.textContent = "Stop"; btn.disabled = false; }
  }
}

async function restartWorkerOnNode(nodeId, nodeIp) {
  const btn = document.getElementById(`btn-restart-worker-${nodeId}`);
  let originalText = "Restart";
  if (btn) {
    originalText = btn.textContent;
    btn.textContent = "Restarting...";
    btn.disabled = true;
  }

  try {
    const res = await fetch(`${API_BASE}/nodes/${nodeId}/restart-worker`, {
      method: "POST",
      headers: { "Authorization": `Bearer ${token}` }
    });
    const data = await res.json();
    if (res.ok) {
      alert(`Worker on ${nodeIp} successfully restarted.`);
      triggerSingleNodeRefresh(nodeId);
    } else {
      alert("Failed to restart worker:\n" + data.detail);
    }
  } catch (err) {
    alert("Error restarting worker on " + nodeIp + "\n" + err.message);
  } finally {
    if (btn) btn.textContent = originalText;
    btn.disabled = false;
  }
}

async function checkWorkerStatus(nodeId, nodeIp) {
  const btn = document.getElementById(`btn-status-worker-${nodeId}`);
  let originalText = "Status";
  if (btn) {
    originalText = btn.textContent;
    btn.textContent = "Checking...";
    btn.disabled = true;
  }

  try {
    const res = await fetch(`${API_BASE}/nodes/${nodeId}/worker-status`, {
      headers: { "Authorization": `Bearer ${token}` }
    });
    const data = await res.json();
    if (res.ok) {
      alert(`Worker Status on ${nodeIp}:\n\n${data.status}`);
    } else {
      alert("Failed to get status:\n" + data.detail);
    }
  } catch (err) {
    alert("Error checking status on " + nodeIp + "\n" + err.message);
  } finally {
    if (btn) btn.textContent = originalText;
    btn.disabled = false;
  }
}

async function stopWorkerOnNode(nodeId, nodeIp) {
  if (!confirm(`Stop worker agent running on ${nodeIp}?`)) return;

  const btn = document.getElementById(`btn-stop-worker-${nodeId}`);
  if (btn) { btn.textContent = "Stopping…"; btn.disabled = true; }

  try {
    const res = await fetch(`${API_BASE}/nodes/${nodeId}/stop-worker`, {
      method: "POST",
      headers: { "Authorization": `Bearer ${token}` }
    });
    const data = await res.json();
    if (res.ok) {
      alert(`✅ Worker agent stopped on ${nodeIp}.`);
    } else {
      alert(`❌ Failed to stop worker on ${nodeIp}:\n${data.detail || JSON.stringify(data)}`);
    }
  } catch (err) {
    alert(`❌ Network error: ${err.message}`);
  } finally {
    if (btn) { btn.textContent = "◼ Stop Worker"; btn.disabled = false; }
  }
}

// --- 14. ACTIVE DDP TRAINING CONTROL & PROGRESS ---
function renderActiveJobPanel() {
  const containers = [elements.dashboardActiveJobContainer, elements.trainingJobDetailsPane];

  containers.forEach(container => {
    if (!container) return;
    container.innerHTML = "";

      if (!activeJob) {
      container.innerHTML = `
        <div class="flex-col align-center justify-center p-xl text-center gap-md">
          <div class="color-muted text-sm">No active parallel processing training job is currently running.</div>
          <button class="btn-primary" onclick="navigateToLaunchView()" style="max-width: 220px;">
            <span class="icon-slot" data-icon="Play"></span> Go to Launch Wizard
          </button>
        </div>
      `;
      renderIcons();
      return;
    }

    // Compute progress percentage
    const epochsTotal = activeJob.epochs || 10;
    const epochCurrent = activeJob.current_epoch || 0;
    const progressPercent = Math.min(100, Math.round((epochCurrent / epochsTotal) * 100));

    // Extract last metrics loss
    let boxLoss = "-";
    let clsLoss = "-";
    let mAP50 = "-";

    if (activeJob.metrics_history && activeJob.metrics_history.length > 0) {
      const latest = activeJob.metrics_history[activeJob.metrics_history.length - 1];
      boxLoss = latest.box_loss ? latest.box_loss.toFixed(4) : "-";
      clsLoss = latest.cls_loss ? latest.cls_loss.toFixed(4) : "-";
      mAP50 = latest.map50 ? (latest.map50 * 100).toFixed(1) + "%" : "-";
    }

    container.innerHTML = `
      <div class="flex-col gap-md">
        <div class="flex-row justify-between align-center">
          <div class="flex-col">
            <span class="text-xs color-muted">JOB ID: <strong class="color-primary mono-text">${activeJob.id}</strong></span>
            <span class="text-md font-semibold color-primary mt-xs">${activeJob.model_name} • ${activeJob.dataset_path}</span>
          </div>
          <span class="badge badge-training">TRAINING DDP</span>
        </div>
        
        <div class="flex-col gap-xs mt-sm">
          <div class="flex-row justify-between text-xs color-secondary font-medium">
            <span>Epoch Iteration Progress</span>
            <span>Epoch ${epochCurrent} / ${epochsTotal} (${progressPercent}%)</span>
          </div>
          <div class="shimmer-progress-bg">
            <div class="shimmer-progress-bar" style="width: ${progressPercent}%;"></div>
          </div>
        </div>
        
        <div class="loss-metrics-grid">
          <div class="loss-metric-pill">
            <div class="loss-metric-val">${boxLoss}</div>
            <div class="loss-metric-lbl">Box Loss</div>
          </div>
          <div class="loss-metric-pill">
            <div class="loss-metric-val">${clsLoss}</div>
            <div class="loss-metric-lbl">Cls Loss</div>
          </div>
          <div class="loss-metric-pill">
            <div class="loss-metric-val">${mAP50}</div>
            <div class="loss-metric-lbl">mAP@50</div>
          </div>
        </div>
        
        <div class="flex-row justify-between align-center mt-md py-sm" style="border-top: 1px solid var(--border-default);">
          <span class="text-xs color-muted">Configuration: Batch Size ${activeJob.batch_size}</span>
          <button class="btn-danger" onclick="stopDDPJob()" style="padding: 8px 16px; font-size: var(--text-xs); width: auto;">
            <span class="icon-slot" data-icon="Square"></span> Terminate Training
          </button>
        </div>
      </div>
    `;
  });
}

function navigateToLaunchView() {
  const trainingBtn = document.getElementById("nav-btn-training");
  if (trainingBtn) trainingBtn.click();
}

// --- 15. SYSTEM LOGS SCREEN TERMINAL SCRAPER ---
function appendLogsToConsole(logLines) {
  if (!elements.logsConsole) return;

  const wasAtBottom = elements.logsConsole.scrollHeight - elements.logsConsole.clientHeight <= elements.logsConsole.scrollTop + 40;

  elements.logsConsole.innerHTML = "";

  logLines.forEach(line => {
    // Expected format: "[2026-06-11 16:30:00] [192.168.1.15] INFO: Epoch 3 completed"
    // Let's strip brackets or separate them nicely
    const parts = line.split(" ");
    let timeStr = "";
    let nodeStr = "MASTER";
    let message = line;

    // Check if timestamp is present
    if (line.startsWith("[")) {
      const endTimestamp = line.indexOf("]");
      if (endTimestamp !== -1) {
        timeStr = line.substring(1, endTimestamp).split(" ")[1] || "";
        const remaining = line.substring(endTimestamp + 2);

        if (remaining.startsWith("[")) {
          const endNode = remaining.indexOf("]");
          nodeStr = remaining.substring(1, endNode);
          message = remaining.substring(endNode + 2);
        } else {
          message = remaining;
        }
      }
    }

    let lineClass = "";
    if (message.toLowerCase().includes("error") || message.toLowerCase().includes("failed")) {
      lineClass = "error";
    } else if (message.toLowerCase().includes("warning") || message.toLowerCase().includes("retry")) {
      lineClass = "warning";
    }

    const row = document.createElement("div");
    row.className = "console-line";
    row.innerHTML = `
      <span class="console-time">${timeStr || "LOG"}</span>
      <span class="console-node">${nodeStr}</span>
      <span class="console-msg ${lineClass}">${message}</span>
    `;
    elements.logsConsole.appendChild(row);
  });

  if (elements.logsAutoscroll && elements.logsAutoscroll.checked && wasAtBottom) {
    elements.logsConsole.scrollTop = elements.logsConsole.scrollHeight;
  }
}

// --- 16. API CALL OPERATIONS ---

// Helper: show/hide remote path input when SCP checkbox is toggled
// A. Node registration
async function handleAddNode(e) {
  e.preventDefault();
  elements.nodeMessageError.classList.add("hidden");
  elements.nodeMessageError.className = "error-message hidden";
  elements.btnSubmitNode.disabled = true;

  const ip = elements.nodeIpInput.value.trim();
  const ssh_user = elements.nodeUserInput.value.trim();
  const ssh_port = parseInt(elements.nodePortInput.value.trim(), 10);
  const ssh_password = elements.nodePasswordInput ? elements.nodePasswordInput.value : "";
  const install_key = elements.nodeInstallKeyToggle ? elements.nodeInstallKeyToggle.checked : false;
  const scp_deploy = document.getElementById("node-scp-deploy-toggle")?.checked || false;
  const run_setup = document.getElementById("node-run-setup-toggle")?.checked || false;
  const scp_path = "worker";

  if (!ssh_password) {
    elements.nodeMessageError.textContent = "SSH Password is required.";
    elements.nodeMessageError.className = "error-message";
    elements.nodeMessageError.classList.remove("hidden");
    elements.btnSubmitNode.disabled = false;
    return;
  }

  elements.btnSubmitNode.textContent = install_key ? "Connecting & installing SSH key..." : "Verifying connection...";

  try {
    // Step 1: Register the node
    const body = { ip, ssh_user, ssh_port, ssh_password, install_key, sync_code: false, run_setup };
    const res = await fetch(`${API_BASE}/nodes/add-with-auth`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Authorization": `Bearer ${token}` },
      body: JSON.stringify(body)
    });
    const data = await res.json();

    if (!res.ok) {
      elements.nodeMessageError.className = "error-message";
      elements.nodeMessageError.textContent = data.detail || "Registration failed. Check credentials.";
      elements.nodeMessageError.classList.remove("hidden");
      return;
    }

    const registeredNodeId = data.id;
    const keyMsg = install_key ? " SSH key installed." : "";

    // Step 2 (optional): SCP deploy worker/ folder immediately
    if (scp_deploy && registeredNodeId) {
      elements.btnSubmitNode.textContent = "Deploying worker/ via SCP...";
      elements.nodeMessageError.className = "error-message color-success";
      elements.nodeMessageError.textContent = `Node ${ip} registered.${keyMsg} Starting SCP deploy…`;
      elements.nodeMessageError.classList.remove("hidden");

      try {
        const scpRes = await fetch(`${API_BASE}/ota/nodes/${registeredNodeId}/scp-deploy`, {
          method: "POST",
          headers: { "Content-Type": "application/json", "Authorization": `Bearer ${token}` },
          body: JSON.stringify({ remote_path: scp_path, local_dir: "worker" })
        });
        const scpData = await scpRes.json();
        if (scpRes.ok) {
          elements.nodeMessageError.textContent = `✅ Node ${ip} registered${keyMsg} + worker/ deployed to ${scp_path}. Use Rsync on OTA page for future updates.`;

          if (run_setup) {
            elements.btnSubmitNode.textContent = "Running Initial Setup...";
            elements.nodeMessageError.textContent = `✅ Node ${ip} registered${keyMsg} + worker/ deployed. Running initial setup...`;
            try {
              const setupRes = await fetch(`${API_BASE}/nodes/${registeredNodeId}/run-setup`, {
                method: "POST",
                headers: { "Content-Type": "application/json", "Authorization": `Bearer ${token}` }
              });
              const setupData = await setupRes.json();
              if (setupRes.ok) {
                elements.nodeMessageError.textContent = `✅ Node ${ip} registered${keyMsg} + worker/ deployed + setup completed & service started!`;
              } else {
                elements.nodeMessageError.textContent = `Node ${ip} registered + deployed, but setup failed: ${setupData.detail}.`;
                elements.nodeMessageError.className = "error-message";
              }
            } catch (setupErr) {
              elements.nodeMessageError.textContent = `Node ${ip} registered + deployed, but setup error: ${setupErr.message}.`;
              elements.nodeMessageError.className = "error-message";
            }
          }
        } else {
          elements.nodeMessageError.textContent = `Node ${ip} registered${keyMsg}, but SCP deploy failed: ${scpData.detail}. Go to OTA page to retry.`;
          elements.nodeMessageError.className = "error-message";
        }
      } catch (scpErr) {
        elements.nodeMessageError.textContent = `Node ${ip} registered${keyMsg}, but SCP deploy error: ${scpErr.message}. Go to OTA page to retry.`;
        elements.nodeMessageError.className = "error-message";
      }
    } else if (run_setup) {
      elements.nodeMessageError.className = "error-message";
      elements.nodeMessageError.textContent = `⚠️ Cannot run setup without SCP deploy. Please enable 'Upload Worker Code'.`;
    } else {
      elements.nodeMessageError.className = "error-message color-success";
      elements.nodeMessageError.textContent = `✅ Node ${ip} registered.${keyMsg} Use the OTA page to deploy the worker/ code.`;
    }

    elements.nodeMessageError.classList.remove("hidden");

    // Reset form
    elements.nodeIpInput.value = "";
    if (elements.nodePasswordInput) elements.nodePasswordInput.value = "";
    const scpToggle = document.getElementById("node-scp-deploy-toggle");
    if (scpToggle) scpToggle.checked = false;
    const runSetupToggle = document.getElementById("node-run-setup-toggle");
    if (runSetupToggle) runSetupToggle.checked = false;

    triggerNodesRefresh();

  } catch (err) {
    elements.nodeMessageError.className = "error-message";
    elements.nodeMessageError.textContent = "Error communicating with backend.";
    elements.nodeMessageError.classList.remove("hidden");
  } finally {
    elements.btnSubmitNode.disabled = false;
    elements.btnSubmitNode.textContent = "Register Node";
  }
}


// B. Global Node Health Refresh
async function triggerNodesRefresh() {
  if (elements.btnRefreshNodes) {
    elements.btnRefreshNodes.disabled = true;
    elements.btnRefreshNodes.textContent = "Refreshing Nodes...";
  }

  try {
    const res = await fetch(`${API_BASE}/nodes/`, {
      headers: { "Authorization": `Bearer ${token}` }
    });
    if (res.ok) {
      nodes = await res.json();
      renderNodesGrid();
      renderDashboardNodes();
    }
  } catch (err) {
    console.error("Failed to query nodes endpoints: ", err);
  } finally {
    if (elements.btnRefreshNodes) {
      elements.btnRefreshNodes.disabled = false;
      elements.btnRefreshNodes.textContent = "Refresh Node Health";
    }
  }
}

// C. Single Node Health Verify
async function triggerSingleNodeRefresh(nodeId) {
  try {
    await fetch(`${API_BASE}/nodes/${nodeId}/refresh`, {
      method: "POST",
      headers: { "Authorization": `Bearer ${token}` }
    });
  } catch (err) {
    console.error("Failed to refresh node: ", nodeId, err);
  }
}

// D. Delete Node Modals
window.confirmDeleteNode = function (id, ip) {
  deleteNodeIdPending = id;
  elements.deleteModalBodyText.innerHTML = `Are you sure you want to remove node <strong>${ip}</strong> from the orchestrator cluster?`;
  elements.confirmDeleteModal.classList.add("open");
};

function closeDeleteModal() {
  deleteNodeIdPending = null;
  elements.confirmDeleteModal.classList.remove("open");
}

async function handleConfirmDeleteNode() {
  if (!deleteNodeIdPending) return;

  try {
    const res = await fetch(`${API_BASE}/nodes/${deleteNodeIdPending}`, {
      method: "DELETE",
      headers: { "Authorization": `Bearer ${token}` }
    });
    if (res.ok) {
      closeDeleteModal();
      triggerNodesRefresh();
    }
  } catch (err) {
    console.error("Could not remove node: ", err);
  }
}

// E. DDP Training Job Launcher
async function handleLaunchTraining(e) {
  e.preventDefault();
  elements.jobLaunchError.classList.add("hidden");
  elements.btnLaunchDdp.disabled = true;
  elements.btnLaunchDdp.textContent = "Initializing cluster & DDP scripts...";

  const model_name = elements.jobModel.value;
  const dataset_path = elements.jobDataset.value.trim();
  const epochs = parseInt(elements.jobEpochs.value, 10);
  const batch_size = parseInt(elements.jobBatch.value, 10);
  const lr0 = parseFloat(elements.jobLr.value);

  try {
    const res = await fetch(`${API_BASE}/train/start`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${token}`
      },
      body: JSON.stringify({
        model_name,
        dataset_path,
        epochs,
        batch_size,
        learning_rate: lr0
      })
    });
    const data = await res.json();

    if (res.ok) {
      // Direct user to logs view to see setup
      const logsBtn = document.getElementById("nav-btn-logs");
      if (logsBtn) logsBtn.click();
    } else {
      elements.jobLaunchError.textContent = data.detail || "Unable to launch DDP trainer.";
      elements.jobLaunchError.classList.remove("hidden");
    }
  } catch (err) {
    elements.jobLaunchError.textContent = "Error launching job.";
    elements.jobLaunchError.classList.remove("hidden");
  } finally {
    elements.btnLaunchDdp.disabled = false;
    elements.btnLaunchDdp.textContent = "Launch DDP Cluster Job";
  }
}

async function handleTestCluster() {
  const btn = document.getElementById("btn-test-cluster");
  if (!btn) return;

  btn.disabled = true;
  btn.textContent = "Testing Cluster...";

  try {
    const res = await fetch(`${API_BASE}/train/test-cluster`, {
      method: "POST",
      headers: { "Authorization": `Bearer ${token}` }
    });

    const data = await res.json();
    if (res.ok && data.status !== "error") {
      let resultText = "Cluster Health Report:\n\n";
      data.details.forEach(d => {
        resultText += d + "\n";
      });
      alert(resultText);
    } else {
      alert(`Test Failed:\n${data.message || data.detail}`);
    }
  } catch (err) {
    alert(`Network Error during test:\n${err.message}`);
  } finally {
    btn.disabled = false;
    btn.textContent = "Test Cluster";
  }
}

// F. Terminate DDP Run
window.stopDDPJob = async function () {
  if (!activeJob) {
    alert("No active training job to stop.");
    return;
  }
  if (!confirm("Are you sure you want to stop the cluster training job? All node runtimes will be terminated immediately.")) return;

  try {
    await fetch(`${API_BASE}/train/jobs/${activeJob.id}/stop`, {
      method: "POST",
      headers: { "Authorization": `Bearer ${token}` }
    });
  } catch (err) {
    console.error("Error terminating DDP job: ", err);
  }
};

// G. Fetch History List (with client-side pagination + status filter)
const HISTORY_PAGE_SIZE = 10;
let historyAllJobs = [];
let historyCurrentPage = 1;
let historyActiveFilter = "all";

async function fetchJobHistory() {
  if (!elements.historyTableBody) return;

  elements.historyTableBody.innerHTML = `
    <tr><td colspan="7" class="text-center p-md color-muted">Loading job records...</td></tr>
  `;
  if (elements.historyPagination) elements.historyPagination.innerHTML = "";

  try {
    const res = await fetch(`${API_BASE}/train/jobs`, {
      headers: { "Authorization": `Bearer ${token}` }
    });
    if (!res.ok) {
      if (res.status === 401) { handleLogout(); return; }
      throw new Error("HTTP " + res.status);
    }
    historyAllJobs = await res.json();
    historyCurrentPage = 1;
    renderHistoryPage();
  } catch (err) {
    elements.historyTableBody.innerHTML = `
      <tr><td colspan="7" class="text-center p-md color-danger">Failed to load run history: ${err.message}</td></tr>
    `;
  }
}

function renderHistoryPage() {
  if (!elements.historyTableBody) return;
  elements.historyTableBody.innerHTML = "";

  // Apply status filter
  const filtered = historyActiveFilter === "all"
    ? historyAllJobs
    : historyAllJobs.filter(j => j.status === historyActiveFilter);

  // Update count badge
  const countEl = document.getElementById("history-filter-count");
  if (countEl) {
    countEl.textContent = filtered.length > 0
      ? `${filtered.length} job${filtered.length !== 1 ? "s" : ""}`
      : "";
  }

  if (filtered.length === 0) {
    elements.historyTableBody.innerHTML = `
      <tr><td colspan="7" class="text-center p-md color-muted">No jobs match the selected filter.</td></tr>
    `;
    if (elements.historyPagination) elements.historyPagination.innerHTML = "";
    return;
  }

  const totalPages = Math.ceil(filtered.length / HISTORY_PAGE_SIZE);
  historyCurrentPage = Math.max(1, Math.min(historyCurrentPage, totalPages));

  const start = (historyCurrentPage - 1) * HISTORY_PAGE_SIZE;
  const end   = Math.min(start + HISTORY_PAGE_SIZE, filtered.length);
  const pageJobs = filtered.slice(start, end);

  pageJobs.forEach(job => {
    let statusBadge = `<span class="badge badge-offline">${job.status}</span>`;
    if (job.status === "completed") statusBadge = `<span class="badge badge-active">${job.status}</span>`;
    else if (job.status === "failed")  statusBadge = `<span class="badge badge-failed">${job.status}</span>`;
    else if (job.status === "running") statusBadge = `<span class="badge badge-training">${job.status}</span>`;

    let downloadAction = `<span class="color-muted">—</span>`;
    if (job.status === "completed") {
      downloadAction = `<a href="${API_BASE}/train/download/${job.id}" class="btn-primary" style="padding:4px 10px;text-decoration:none;border-radius:4px;font-size:var(--text-xs);" download>Download</a>`;
    }

    const tr = document.createElement("tr");
    tr.style.borderBottom = "1px solid var(--border-default)";
    tr.innerHTML = `
      <td style="padding:12px 16px;" class="mono-text">${job.id}</td>
      <td style="padding:12px 16px;">${job.model_name}</td>
      <td style="padding:12px 16px;">${job.dataset_path}</td>
      <td style="padding:12px 16px;">${job.epochs}</td>
      <td style="padding:12px 16px;">${job.batch_size}</td>
      <td style="padding:12px 16px;">${statusBadge}</td>
      <td style="padding:12px 16px;">${downloadAction}</td>
    `;
    elements.historyTableBody.appendChild(tr);
  });

  renderHistoryPagination(totalPages, start + 1, end, filtered.length);
}

function renderHistoryPagination(totalPages, rangeStart, rangeEnd, filteredTotal) {
  const container = elements.historyPagination;
  if (!container) return;
  container.innerHTML = "";
  if (totalPages <= 1) return;

  // Info label
  const info = document.createElement("span");
  info.className = "pagination-info";
  info.textContent = `Jobs ${rangeStart}–${rangeEnd} of ${filteredTotal}`;
  container.appendChild(info);

  const nav = document.createElement("div");
  nav.className = "pagination-nav";

  // Prev button
  const prevBtn = document.createElement("button");
  prevBtn.className = "pagination-btn" + (historyCurrentPage === 1 ? " disabled" : "");
  prevBtn.disabled = historyCurrentPage === 1;
  prevBtn.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><polyline points="15 18 9 12 15 6"/></svg>`;
  prevBtn.addEventListener("click", () => { historyCurrentPage--; renderHistoryPage(); });
  nav.appendChild(prevBtn);

  // Page number buttons (show max 5 around current)
  const windowSize = 5;
  let pageStart = Math.max(1, historyCurrentPage - Math.floor(windowSize / 2));
  let pageEnd   = Math.min(totalPages, pageStart + windowSize - 1);
  if (pageEnd - pageStart < windowSize - 1) pageStart = Math.max(1, pageEnd - windowSize + 1);

  if (pageStart > 1) {
    const firstBtn = document.createElement("button");
    firstBtn.className = "pagination-btn";
    firstBtn.textContent = "1";
    firstBtn.addEventListener("click", () => { historyCurrentPage = 1; renderHistoryPage(); });
    nav.appendChild(firstBtn);
    if (pageStart > 2) {
      const dots = document.createElement("span");
      dots.className = "pagination-dots";
      dots.textContent = "…";
      nav.appendChild(dots);
    }
  }

  for (let p = pageStart; p <= pageEnd; p++) {
    const btn = document.createElement("button");
    btn.className = "pagination-btn" + (p === historyCurrentPage ? " active" : "");
    btn.textContent = p;
    btn.addEventListener("click", ((pg) => () => { historyCurrentPage = pg; renderHistoryPage(); })(p));
    nav.appendChild(btn);
  }

  if (pageEnd < totalPages) {
    if (pageEnd < totalPages - 1) {
      const dots = document.createElement("span");
      dots.className = "pagination-dots";
      dots.textContent = "…";
      nav.appendChild(dots);
    }
    const lastBtn = document.createElement("button");
    lastBtn.className = "pagination-btn";
    lastBtn.textContent = totalPages;
    lastBtn.addEventListener("click", () => { historyCurrentPage = totalPages; renderHistoryPage(); });
    nav.appendChild(lastBtn);
  }

  // Next button
  const nextBtn = document.createElement("button");
  nextBtn.className = "pagination-btn" + (historyCurrentPage === totalPages ? " disabled" : "");
  nextBtn.disabled = historyCurrentPage === totalPages;
  nextBtn.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><polyline points="9 18 15 12 9 6"/></svg>`;
  nextBtn.addEventListener("click", () => { historyCurrentPage++; renderHistoryPage(); });
  nav.appendChild(nextBtn);

  container.appendChild(nav);
}

// ═══════════════════════════════════════════════════════════════
// H. OTA MANAGEMENT PAGE — per-node SCP/Rsync deployment system
// ═══════════════════════════════════════════════════════════════

let otaNodes = [];  // cached list from /ota/nodes

// Load node list and render OTA cards
async function loadOtaNodes() {
  if (!elements.otaNodesGrid) return;
  elements.otaNodesGrid.innerHTML = `<div class="color-muted text-sm p-md">Loading deployment status…</div>`;
  try {
    const res = await fetch(`${API_BASE}/ota/nodes`, {
      headers: { "Authorization": `Bearer ${token}` }
    });
    if (!res.ok) {
      if (res.status === 401) {
        handleLogout();
        return;
      }
      throw new Error("HTTP " + res.status);
    }
    otaNodes = await res.json();
    renderOtaCards();
  } catch (e) {
    elements.otaNodesGrid.innerHTML = `<div class="color-danger text-sm p-md">Failed to load OTA status: ${e.message}</div>`;
  }
}

function otaStatusBadge(status) {
  const icons = { never: "○", pending: "◷", success: "✓", failed: "✗" };
  return `<span class="ota-status-badge ota-status-${status}">${icons[status] || "○"} ${status}</span>`;
}

function renderOtaCards() {
  if (!elements.otaNodesGrid) return;
  elements.otaNodesGrid.innerHTML = "";

  if (otaNodes.length === 0) {
    elements.otaNodesGrid.innerHTML = `
      <div class="ota-node-card" style="text-align:center; color:var(--text-muted);">
        No nodes registered. Add nodes in the Cluster Nodes view first.
      </div>`;
    return;
  }

  otaNodes.forEach(node => {
    const isDeployed = node.deploy_status === "success";
    const lastSync = node.last_sync_time
      ? new Date(node.last_sync_time).toLocaleString()
      : "Never";
    const remotePath = node.remote_deploy_path || "";

    const card = document.createElement("div");
    card.className = "ota-node-card";
    card.id = `ota-card-${node.id}`;
    card.innerHTML = `
      <div class="node-header">
        <div class="flex-col">
          <span class="font-semibold color-primary" style="font-size:var(--text-md);">${node.ip}</span>
          <span class="text-xs color-muted">${node.ssh_user}@${node.ip}:${node.ssh_port}</span>
        </div>
        <div class="flex-row align-center gap-sm">
          ${otaStatusBadge(node.deploy_status || "never")}
          <span class="badge ${node.status === 'active' ? 'badge-active' : 'badge-offline'}" style="font-size:10px;">${node.status}</span>
        </div>
      </div>

      <div class="ota-meta-row">
        <span><strong>Last Sync:</strong> ${lastSync}</span>
        <span><strong>Deploy Status:</strong> ${node.deploy_status || "never"}</span>
      </div>


      <div class="ota-node-actions">
        ${!isDeployed ? `
        <button class="btn-info" id="btn-scp-${node.id}" onclick="otaSCPDeploy(${node.id})">
          <span class="icon-slot" data-icon="UploadCloud"></span> SCP Deploy
        </button>` : ""}
        <button class="btn-success" id="btn-rsync-${node.id}" onclick="otaRsyncSync(${node.id})">
          <span class="icon-slot" data-icon="RefreshCw"></span> Rsync
        </button>
        <button class="btn-icon" id="btn-logs-${node.id}" onclick="openOtaLogModal(${node.id}, '${node.ip}')" title="View Logs" style="width:36px; height:36px; color:var(--text-secondary);">
          <span class="icon-slot" data-icon="Logs"></span>
        </button>
      </div>

      <div id="ota-card-msg-${node.id}" style="display:none; font-size:var(--text-xs); padding:6px 0;"></div>
    `;
    elements.otaNodesGrid.appendChild(card);
  });
}

function otaCardMsg(nodeId, msg, isError) {
  const el = document.getElementById(`ota-card-msg-${nodeId}`);
  if (!el) return;
  el.textContent = msg;
  el.style.display = msg ? "block" : "none";
  el.style.color = isError ? "var(--danger)" : "var(--success)";
}

// Per-node SCP initial deploy
window.otaSCPDeploy = async function (nodeId) {
  const remotePath = "worker";
  const localDir = elements.otaLocalDir ? elements.otaLocalDir.value.trim() || "worker" : "worker";
  const btn = document.getElementById(`btn-scp-${nodeId}`);
  if (btn) { btn.disabled = true; btn.textContent = "Deploying…"; }
  otaCardMsg(nodeId, "SCP deployment in progress…", false);

  try {
    const res = await fetch(`${API_BASE}/ota/nodes/${nodeId}/scp-deploy`, {
      method: "POST",
      headers: { "Authorization": `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ remote_path: remotePath, local_dir: localDir })
    });
    const data = await res.json();
    if (res.ok) {
      otaCardMsg(nodeId, `✅ Deployed to ${data.remote_path}`, false);
      loadOtaNodes();
    } else {
      otaCardMsg(nodeId, `❌ ${data.detail}`, true);
      if (btn) { btn.disabled = false; btn.textContent = "🚀 SCP Initial Deploy"; }
    }
  } catch (e) {
    otaCardMsg(nodeId, `❌ Network error: ${e.message}`, true);
    if (btn) { btn.disabled = false; btn.textContent = "🚀 SCP Initial Deploy"; }
  }
};

// Per-node Rsync sync
window.otaRsyncSync = async function (nodeId) {
  const pathInput = document.getElementById(`ota-path-${nodeId}`);
  const remotePath = pathInput ? pathInput.value.trim() : "";
  // If user edited the path field, save it first
  const node = otaNodes.find(n => n.id === nodeId);
  const localDir = elements.otaLocalDir ? elements.otaLocalDir.value.trim() || "worker" : "worker";

  const btn = document.getElementById(`btn-rsync-${nodeId}`);
  if (btn) { btn.disabled = true; btn.textContent = "Syncing…"; }
  otaCardMsg(nodeId, "Rsync in progress…", false);

  // If path differs from saved, do an SCP first (first-time)
  if (!node || !node.remote_deploy_path) {
    if (!remotePath) {
      otaCardMsg(nodeId, "Set a remote path before syncing.", true);
      if (btn) { btn.disabled = false; btn.textContent = "🔄 Rsync Sync"; }
      return;
    }
    // Auto-save path via SCP deploy first
    await otaSCPDeploy(nodeId);
    if (btn) { btn.disabled = false; btn.textContent = "🔄 Rsync Sync"; }
    return;
  }

  try {
    const res = await fetch(`${API_BASE}/ota/nodes/${nodeId}/rsync-sync`, {
      method: "POST",
      headers: { "Authorization": `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ local_dir: localDir })
    });
    const data = await res.json();
    if (res.ok) {
      otaCardMsg(nodeId, `✅ Rsync complete — ${data.remote_path}`, false);
      loadOtaNodes();
    } else {
      otaCardMsg(nodeId, `❌ ${data.detail}`, true);
    }
  } catch (e) {
    otaCardMsg(nodeId, `❌ Network error: ${e.message}`, true);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = "🔄 Rsync Sync"; }
  }
};

// Bulk: deploy all new nodes
async function otaDeployAll() {
  const remotePath = elements.otaDefaultRemotePath ? elements.otaDefaultRemotePath.value.trim() : "";
  if (!remotePath) {
    showOtaGlobalFeedback("Please enter a default remote path before bulk deploying.", true);
    return;
  }
  const localDir = elements.otaLocalDir ? elements.otaLocalDir.value.trim() || "worker" : "worker";
  const btn = elements.btnOtaDeployAll;
  if (btn) { btn.disabled = true; btn.textContent = "Deploying…"; }
  showOtaGlobalFeedback("Deploying to all new nodes via SCP…", false);

  try {
    const res = await fetch(`${API_BASE}/ota/deploy-all`, {
      method: "POST",
      headers: { "Authorization": `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ remote_path: remotePath, local_dir: localDir })
    });
    const data = await res.json();
    showOtaGlobalFeedback(data.detail || "Bulk deploy complete.", data.status === "partial");
    loadOtaNodes();
  } catch (e) {
    showOtaGlobalFeedback(`Error: ${e.message}`, true);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = "🚀 Deploy All New Nodes (SCP)"; }
  }
}

// Bulk: sync all deployed nodes
async function otaSyncAll() {
  const localDir = elements.otaLocalDir ? elements.otaLocalDir.value.trim() || "worker" : "worker";
  const btn = elements.btnOtaSyncAll;
  if (btn) { btn.disabled = true; btn.textContent = "Syncing…"; }
  showOtaGlobalFeedback("Rsyncing all deployed nodes…", false);

  try {
    const res = await fetch(`${API_BASE}/ota/sync-all`, {
      method: "POST",
      headers: { "Authorization": `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ local_dir: localDir })
    });
    const data = await res.json();
    showOtaGlobalFeedback(data.detail || "Sync complete.", data.status === "partial");
    loadOtaNodes();
  } catch (e) {
    showOtaGlobalFeedback(`Error: ${e.message}`, true);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = "🔄 Sync All Nodes (Rsync)"; }
  }
}

// Validate paths on all deployed nodes
async function otaValidatePaths() {
  const btn = elements.btnOtaValidate;
  if (btn) { btn.disabled = true; btn.textContent = "Validating…"; }
  showOtaGlobalFeedback("Validating remote paths…", false);

  try {
    const res = await fetch(`${API_BASE}/ota/validate-paths`, {
      method: "POST",
      headers: { "Authorization": `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ node_ids: null })
    });
    const data = await res.json();
    const results = data.results || [];
    if (results.length === 0) {
      showOtaGlobalFeedback("No nodes with configured paths.", false);
    } else {
      const summary = results.map(r => `${r.ip}: ${r.status}`).join(" | ");
      const hasInvalid = results.some(r => r.status !== "valid");
      showOtaGlobalFeedback(`Path validation: ${summary}`, hasInvalid);
    }
  } catch (e) {
    showOtaGlobalFeedback(`Error: ${e.message}`, true);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = "✅ Validate Paths"; }
  }
}

function showOtaGlobalFeedback(msg, isError) {
  const el = elements.otaGlobalFeedback;
  if (!el) return;
  el.textContent = msg;
  el.className = `ota-global-feedback show ${isError ? "error" : "success"}`;
  setTimeout(() => { el.className = "ota-global-feedback"; }, 6000);
}

// Log Modal
window.openOtaLogModal = async function (nodeId, nodeIp) {
  if (!elements.otaLogModal) return;
  elements.otaLogModalTitle.textContent = `Deployment Logs — Node ${nodeIp}`;
  elements.otaLogModalSubtitle.textContent = `Node ID: ${nodeId}`;
  elements.otaLogBody.textContent = "Loading…";
  elements.otaLogModal.classList.add("open");

  try {
    const res = await fetch(`${API_BASE}/ota/nodes/${nodeId}/logs`, {
      headers: { "Authorization": `Bearer ${token}` }
    });
    const data = await res.json();
    const logs = data.logs || [];
    elements.otaLogBody.textContent = logs.length > 0 ? logs.join("\n") : "No deployment logs recorded yet.";
    elements.otaLogBody.scrollTop = elements.otaLogBody.scrollHeight;
  } catch (e) {
    elements.otaLogBody.textContent = `Error loading logs: ${e.message}`;
  }
};

function closeOtaLogModal() {
  if (elements.otaLogModal) elements.otaLogModal.classList.remove("open");
}

// I. Manual Worker Package Builder & Downloader
async function packageWorker() {
  if (!elements.pkgStatusError || !elements.pkgStatusSuccess) return;

  elements.pkgStatusError.classList.add("hidden");
  elements.pkgStatusSuccess.classList.add("hidden");
  elements.btnPackageWorker.disabled = true;
  elements.btnPackageWorkerLabel.textContent = "Building zip archive...";

  let zipFilename = null;

  try {
    // Step 1: Ask backend to zip worker/ and return the filename
    const packRes = await fetch(`${API_BASE}/train/package-worker`, {
      method: "POST",
      headers: { "Authorization": `Bearer ${token}` }
    });
    const packData = await packRes.json();

    if (!packRes.ok) {
      elements.pkgStatusError.textContent = packData.detail || "Failed to build package.";
      elements.pkgStatusError.classList.remove("hidden");
      return;
    }

    zipFilename = packData.filename;
    elements.btnPackageWorkerLabel.textContent = "Downloading...";

    // Step 2: Trigger browser download via a hidden anchor
    const downloadUrl = `${API_BASE}/train/download-package?filename=${encodeURIComponent(zipFilename)}`;
    const a = document.createElement("a");
    a.href = downloadUrl;
    // Pass auth token via URL since we can't set headers on anchor clicks
    // Backend uses query-param token fallback for file downloads
    a.setAttribute("download", zipFilename);
    a.style.display = "none";
    document.body.appendChild(a);

    // Fetch with auth header, convert to blob, then download
    const dlRes = await fetch(downloadUrl, {
      headers: { "Authorization": `Bearer ${token}` }
    });

    if (!dlRes.ok) {
      elements.pkgStatusError.textContent = "Package built but download failed. Check server.";
      elements.pkgStatusError.classList.remove("hidden");
      document.body.removeChild(a);
      return;
    }

    const blob = await dlRes.blob();
    const blobUrl = URL.createObjectURL(blob);
    a.href = blobUrl;
    a.click();

    setTimeout(() => {
      URL.revokeObjectURL(blobUrl);
      document.body.removeChild(a);
    }, 2000);

    elements.pkgStatusSuccess.textContent = `Package ready: ${zipFilename} — download started!`;
    elements.pkgStatusSuccess.classList.remove("hidden");

  } catch (err) {
    elements.pkgStatusError.textContent = `Error: ${err.message}`;
    elements.pkgStatusError.classList.remove("hidden");
  } finally {
    elements.btnPackageWorker.disabled = false;
    elements.btnPackageWorkerLabel.textContent = " Build & Download Worker Package";
  }
}
