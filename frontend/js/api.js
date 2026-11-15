/**
 * API client for TLG SmartPrint backend (Student & Admin endpoints).
 */
window.SmartPrintApi = (() => {
  const TOKEN_KEY = "tlg_smartprint_admin_token";

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
      body: JSON.stringify(payload),
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
    getAdminToken,
    setAdminToken,
    getSystemStatus,
    uploadDocument,
    loadSampleDocument,
    createPrintJob,
    adminLogin,
    getAdminDashboard,
    updateAdminSettings,
    updateAdminCredentials,
    updateAdminJobStatus,
    deleteAdminPrintJob,
    clearAdminPrintJobs,
  };
})();
