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
    const res = await fetch("/api/print-jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        client_token: getClientToken(),
        ...payload,
      }),
    });
    return handleResponse(res);
  }

  async function getLiveQueue() {
    const res = await fetch("/api/queue/live");
    return handleResponse(res);
  }

  async function confirmJobPrinted(jobId) {
    const res = await fetch(`/api/print-jobs/${encodeURIComponent(jobId)}/confirm`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ client_token: getClientToken() }),
    });
    return handleResponse(res);
  }

  async function extendJobTime(jobId, extraSeconds = 15) {
    const res = await fetch(`/api/print-jobs/${encodeURIComponent(jobId)}/extend`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        client_token: getClientToken(),
        extra_seconds: extraSeconds,
      }),
    });
    return handleResponse(res);
  }

  async function cancelPrintJob(jobId) {
    const res = await fetch(`/api/print-jobs/${encodeURIComponent(jobId)}/cancel`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ client_token: getClientToken() }),
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
  };
})();
