/**
 * API client for TLG SmartPrint backend (Student & Admin endpoints).
 */
window.SmartPrintApi = (() => {
  const TOKEN_KEY = "tlg_smartprint_admin_token";
  const CLIENT_TOKEN_KEY = "tlg_smartprint_client_token";

  function getClientToken() {
    let token = localStorage.getItem(CLIENT_TOKEN_KEY);
    if (!token) {
      token =
        typeof crypto !== "undefined" && crypto.randomUUID
          ? `stu_${crypto.randomUUID().replace(/-/g, "").slice(0, 16)}`
          : `stu_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 10)}`;
      localStorage.setItem(CLIENT_TOKEN_KEY, token);
    }
    return token;
  }

  function getDeviceLabel() {
    const ua = (typeof navigator !== "undefined" && navigator.userAgent) || "";
    const l = ua.toLowerCase();
    let osPart = "Qurilma";
    if (l.includes("iphone")) osPart = "iPhone";
    else if (l.includes("ipad")) osPart = "iPad";
    else if (l.includes("android")) osPart = "Android Telefon";
    else if (l.includes("windows")) osPart = "Windows Kompyuter";
    else if (l.includes("macintosh") || l.includes("mac os")) osPart = "Mac Kompyuter";
    else if (l.includes("linux")) osPart = "Linux Kompyuter";

    let browser = "";
    if (l.includes("edg/")) browser = "Edge";
    else if (l.includes("chrome/") || l.includes("crios/")) browser = "Chrome";
    else if (l.includes("firefox/") || l.includes("fxios/")) browser = "Firefox";
    else if (l.includes("safari/")) browser = "Safari";

    return browser ? `${osPart} • ${browser}` : osPart;
  }

  function getAdminToken() {
    return sessionStorage.getItem(TOKEN_KEY) || "";
  }

  function setAdminToken(token) {
    if (token) {
      sessionStorage.setItem(TOKEN_KEY, token);
    } else {
      sessionStorage.removeItem(TOKEN_KEY);
    }
  }

  async function handleResponse(res) {
    if (!res.ok) {
      let detail = `Server xatoligi (${res.status})`;
      try {
        const body = await res.json();
        if (body && body.detail) detail = body.detail;
      } catch (_) {
        // fallback message
      }
      const err = new Error(detail);
      err.status = res.status;
      throw err;
    }
    return res.json();
  }

  function authHeaders(extra = {}) {
    const token = getAdminToken();
    return token ? { ...extra, Authorization: `Bearer ${token}` } : extra;
  }

  async function getSystemStatus() {
    const res = await fetch("/api/system-status");
    return handleResponse(res);
  }

  async function uploadDocument(file) {
    const formData = new FormData();
    formData.append("file", file);
    const res = await fetch("/api/documents/upload", {
      method: "POST",
      body: formData,
    });
    return handleResponse(res);
  }

  async function loadSampleDocument() {
    const res = await fetch("/api/documents/sample", {
      method: "POST",
    });
    return handleResponse(res);
  }

  async function createPrintJob(payload) {
    const tok = getClientToken();
    const res = await fetch("/api/print-jobs", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Client-Token": tok,
      },
      body: JSON.stringify({
        client_token: tok,
        device_label: getDeviceLabel(),
        ...payload,
      }),
    });
    const data = await handleResponse(res);
    if (data && data.client_token) {
      localStorage.setItem(CLIENT_TOKEN_KEY, data.client_token);
    }
    return data;
  }

  async function getLiveQueue() {
    const res = await fetch("/api/queue/live", {
      headers: { "X-Client-Token": getClientToken() },
    });
    return handleResponse(res);
  }

  async function confirmJobPrinted(jobId) {
    const tok = getClientToken();
    const res = await fetch(`/api/print-jobs/${encodeURIComponent(jobId)}/confirm`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Client-Token": tok,
      },
      body: JSON.stringify({ client_token: tok }),
    });
    return handleResponse(res);
  }

  async function extendJobTime(jobId, extraSeconds = 15) {
    const tok = getClientToken();
    const res = await fetch(`/api/print-jobs/${encodeURIComponent(jobId)}/extend`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Client-Token": tok,
      },
      body: JSON.stringify({
        client_token: tok,
        extra_seconds: extraSeconds,
      }),
    });
    return handleResponse(res);
  }

  async function cancelPrintJob(jobId) {
    const tok = getClientToken();
    const res = await fetch(`/api/print-jobs/${encodeURIComponent(jobId)}/cancel`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Client-Token": tok,
      },
      body: JSON.stringify({ client_token: tok }),
    });
    return handleResponse(res);
  }

  // Admin APIs
  async function adminLogin(username, password) {
    const res = await fetch("/api/admin/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    const data = await handleResponse(res);
    setAdminToken(data.token);
    return data;
  }

  async function getAdminDashboard() {
    const res = await fetch("/api/admin/dashboard", {
      headers: authHeaders(),
    });
    return handleResponse(res);
  }

  async function updateAdminSettings(payload) {
    const res = await fetch("/api/admin/settings", {
      method: "PUT",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(payload),
    });
    return handleResponse(res);
  }

  async function updateAdminCredentials(payload) {
    const res = await fetch("/api/admin/credentials", {
      method: "PUT",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(payload),
    });
    const data = await handleResponse(res);
    if (data.token) setAdminToken(data.token);
    return data;
  }

  async function updateAdminJobStatus(jobId, status, statusMessage = "") {
    const res = await fetch(`/api/admin/print-jobs/${encodeURIComponent(jobId)}`, {
      method: "PATCH",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ status, status_message: statusMessage }),
    });
    return handleResponse(res);
  }

  async function verifyJobPayment(jobId, receiptFile) {
    const fd = new FormData();
    fd.append("receipt", receiptFile);
    fd.append("client_token", getClientToken());
    const res = await fetch(`/api/print-jobs/${encodeURIComponent(jobId)}/verify-payment`, {
      method: "POST",
      headers: { "X-Client-Token": getClientToken() },
      body: fd,
    });
    return handleResponse(res);
  }

  async function renewJobPayment(jobId) {
    const res = await fetch(`/api/print-jobs/${encodeURIComponent(jobId)}/renew-payment`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Client-Token": getClientToken(),
      },
      body: JSON.stringify({ client_token: getClientToken() }),
    });
    return handleResponse(res);
  }

  function getReceiptUrl(jobId) {
    return `/api/admin/print-jobs/${encodeURIComponent(jobId)}/receipt?token=${encodeURIComponent(getAdminToken())}`;
  }

  async function sendTelegramCode(phone, botUsername) {
    const res = await fetch("/api/admin/telegram/send-code", {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ phone, bot_username: botUsername }),
    });
    return handleResponse(res);
  }

  async function verifyTelegramCode(authToken, code, password = "") {
    const res = await fetch("/api/admin/telegram/verify-code", {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ auth_token: authToken, code, password }),
    });
    return handleResponse(res);
  }

  async function disconnectTelegram() {
    const res = await fetch("/api/admin/telegram/disconnect", {
      method: "POST",
      headers: authHeaders(),
    });
    return handleResponse(res);
  }

  async function getRecentHumoPayments() {
    const res = await fetch("/api/admin/telegram/recent-payments", {
      headers: authHeaders(),
    });
    return handleResponse(res);
  }

  async function deleteAdminPrintJob(jobId) {
    const res = await fetch(`/api/admin/print-jobs/${encodeURIComponent(jobId)}`, {
      method: "DELETE",
      headers: authHeaders(),
    });
    return handleResponse(res);
  }

  async function clearAdminPrintJobs() {
    const res = await fetch("/api/admin/print-jobs", {
      method: "DELETE",
      headers: authHeaders(),
    });
    return handleResponse(res);
  }

  async function downloadDatabaseBackup() {
    const res = await fetch("/api/admin/backup", {
      headers: authHeaders(),
    });
    if (!res.ok) {
      return handleResponse(res);
    }
    const blob = await res.blob();
    const disp = res.headers.get("content-disposition") || "";
    const match = disp.match(/filename="([^"]+)"/i);
    const filename = match ? match[1] : `smartprint_backup_${Date.now()}.db`;
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    return { filename };
  }

  async function scanPrinters({ networkIp = "", includeNetworkScan = true, waitAgentSeconds = 3.5 } = {}) {
    const res = await fetch("/api/admin/printers/scan", {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        network_ip: networkIp,
        include_network_scan: includeNetworkScan,
        wait_agent_seconds: waitAgentSeconds,
      }),
    });
    return handleResponse(res);
  }

  async function autoConfigurePrinter({ deviceUri, queueName = "", hostScope = "local", setDefault = true }) {
    const res = await fetch("/api/admin/printers/auto-configure", {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        device_uri: deviceUri,
        queue_name: queueName,
        host_scope: hostScope,
        set_default: setDefault,
      }),
    });
    return handleResponse(res);
  }

  return {
    getClientToken,
    getAdminToken,
    setAdminToken,
    getSystemStatus,
    uploadDocument,
    loadSampleDocument,
    createPrintJob,
    getLiveQueue,
    confirmJobPrinted,
    extendJobTime,
    cancelPrintJob,
    adminLogin,
    getAdminDashboard,
    updateAdminSettings,
    updateAdminCredentials,
    updateAdminJobStatus,
    deleteAdminPrintJob,
    clearAdminPrintJobs,
    downloadDatabaseBackup,
    scanPrinters,
    autoConfigurePrinter,
    verifyJobPayment,
    renewJobPayment,
    getReceiptUrl,
    sendTelegramCode,
    verifyTelegramCode,
    disconnectTelegram,
    getRecentHumoPayments,
  };
})();
