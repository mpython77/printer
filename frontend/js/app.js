/**
 * Main controller for TLG SmartPrint student portal and protected Admin panel.
 */
(() => {
  const { SmartPrintApi, PageSelector, PdfRenderer } = window;

  const STUDIO_DRAFT_KEY = "tlg_smartprint_studio_draft_v1";
  const MODAL_STATE_KEY = "tlg_smartprint_modal_state_v1";
  const ADMIN_VIEW_KEY = "tlg_smartprint_admin_view_v1";
  const ADMIN_TAB_KEY = "tlg_smartprint_admin_tab_v1";

  const state = {
    systemStatus: null,
    currentDoc: null,
    selectedPages: new Set(),
    rotations: {},
    copies: 1,
    colorMode: "bw",
    colorPages: new Set(),
    duplex: "simplex",
    orientation: "portrait",
    pagesPerSheet: 1,
    paperSize: "A4",
    zoomPage: 1,
    pageCanvases: new Map(),
    pageCards: new Map(),
    adminDashboard: null,
    countdownTimer: null,
    liveQueue: null,
    myActiveJobs: [],
    activeModalJob: null,
    showQueueDetails: false,
    queuePollTimer: null,
    isPollingQueue: false,
    isRestoringSession: false,
    pendingRestoredPrinterName: "",
    pendingScanRefreshTimer: null,
    telegramPendingAuthToken: "",
  };

  // DOM References
  const el = {
    printerModeBadge: document.getElementById("printerModeBadge"),
    printerModeText: document.getElementById("printerModeText"),
    detectedPrinterName: document.getElementById("detectedPrinterName"),
    backToStudioBtn: document.getElementById("backToStudioBtn"),
    openAdminBtn: document.getElementById("openAdminBtn"),
    openAdminBtnLabel: document.getElementById("openAdminBtnLabel"),
    adminLogoutBtn: document.getElementById("adminLogoutBtn"),

    liveQueueCard: document.getElementById("liveQueueCard"),
    livePrinterStateBadge: document.getElementById("livePrinterStateBadge"),
    livePrinterStateText: document.getElementById("livePrinterStateText"),
    liveQueueMetaText: document.getElementById("liveQueueMetaText"),
    toggleQueueDetailsBtn: document.getElementById("toggleQueueDetailsBtn"),
    liveActiveJobBox: document.getElementById("liveActiveJobBox"),
    liveConfirmPrompt: document.getElementById("liveConfirmPrompt"),
    myPendingPaymentBanner: document.getElementById("myPendingPaymentBanner"),
    liveQueueColumns: document.getElementById("liveQueueColumns"),
    liveWaitingCountPill: document.getElementById("liveWaitingCountPill"),
    liveWaitingList: document.getElementById("liveWaitingList"),
    liveRecentList: document.getElementById("liveRecentList"),

    studentView: document.getElementById("studentView"),
    adminView: document.getElementById("adminView"),

    uploadView: document.getElementById("uploadView"),
    studioWorkspace: document.getElementById("studioWorkspace"),
    dropZone: document.getElementById("dropZone"),
    fileInput: document.getElementById("fileInput"),
    browseFileBtn: document.getElementById("browseFileBtn"),
    loadSampleBtn: document.getElementById("loadSampleBtn"),
    uploadLoader: document.getElementById("uploadLoader"),
    uploadLoaderText: document.getElementById("uploadLoaderText"),

    heroBwPrice: document.getElementById("heroBwPrice"),
    heroColorPrice: document.getElementById("heroColorPrice"),
    heroPrinterName: document.getElementById("heroPrinterName"),
    segBwPriceBadge: document.getElementById("segBwPriceBadge"),
    segColorPriceBadge: document.getElementById("segColorPriceBadge"),

    selectionSummaryBadge: document.getElementById("selectionSummaryBadge"),
    btnSelectAll: document.getElementById("btnSelectAll"),
    btnSelectOdd: document.getElementById("btnSelectOdd"),
    btnSelectEven: document.getElementById("btnSelectEven"),
    btnClearSelection: document.getElementById("btnClearSelection"),
    pageRangeInput: document.getElementById("pageRangeInput"),
    rangeErrorMsg: document.getElementById("rangeErrorMsg"),
    pagesGrid: document.getElementById("pagesGrid"),

    docFileTypeBadge: document.getElementById("docFileTypeBadge"),
    docTitleText: document.getElementById("docTitleText"),
    docMetaSubtext: document.getElementById("docMetaSubtext"),
    changeDocumentBtn: document.getElementById("changeDocumentBtn"),

    studentNameInput: document.getElementById("studentNameInput"),
    copiesMinusBtn: document.getElementById("copiesMinusBtn"),
    copiesPlusBtn: document.getElementById("copiesPlusBtn"),
    copiesValue: document.getElementById("copiesValue"),
    colorBwBtn: document.getElementById("colorBwBtn"),
    colorColorBtn: document.getElementById("colorColorBtn"),
    colorMixedBtn: document.getElementById("colorMixedBtn"),
    mixedColorBox: document.getElementById("mixedColorBox"),
    colorPagesInput: document.getElementById("colorPagesInput"),
    orientPortraitBtn: document.getElementById("orientPortraitBtn"),
    orientLandscapeBtn: document.getElementById("orientLandscapeBtn"),
    pagesPerSheetSelect: document.getElementById("pagesPerSheetSelect"),
    paperSizeSelect: document.getElementById("paperSizeSelect"),
    printerSelect: document.getElementById("printerSelect"),

    summaryPagesText: document.getElementById("summaryPagesText"),
    summaryCopiesText: document.getElementById("summaryCopiesText"),
    summarySheetsText: document.getElementById("summarySheetsText"),
    summaryUnitPriceText: document.getElementById("summaryUnitPriceText"),
    summaryTimeText: document.getElementById("summaryTimeText"),
    summaryCostText: document.getElementById("summaryCostText"),
    printSubmitBtn: document.getElementById("printSubmitBtn"),
    printSubmitPriceBadge: document.getElementById("printSubmitPriceBadge"),
    printValidationHint: document.getElementById("printValidationHint"),
    mobileStickyBar: document.getElementById("mobileStickyBar"),
    mobileStickyPages: document.getElementById("mobileStickyPages"),
    mobileStickyTotal: document.getElementById("mobileStickyTotal"),
    mobilePrintSubmitBtn: document.getElementById("mobilePrintSubmitBtn"),

    // Admin Login Modal
    adminLoginModal: document.getElementById("adminLoginModal"),
    adminLoginCloseBtn: document.getElementById("adminLoginCloseBtn"),
    adminLoginForm: document.getElementById("adminLoginForm"),
    adminUsernameInput: document.getElementById("adminUsernameInput"),
    adminPasswordInput: document.getElementById("adminPasswordInput"),
    toggleLoginPwdBtn: document.getElementById("toggleLoginPwdBtn"),
    adminLoginError: document.getElementById("adminLoginError"),
    adminLoginSubmitBtn: document.getElementById("adminLoginSubmitBtn"),

    // Admin Dashboard
    adminCurrentUsernameLabel: document.getElementById("adminCurrentUsernameLabel"),
    adminRefreshBtn: document.getElementById("adminRefreshBtn"),
    statTotalJobs: document.getElementById("statTotalJobs"),
    statJobsToday: document.getElementById("statJobsToday"),
    statTotalPages: document.getElementById("statTotalPages"),
    statTotalSheets: document.getElementById("statTotalSheets"),
    statTotalRevenue: document.getElementById("statTotalRevenue"),

    priceBwSimplexInput: document.getElementById("priceBwSimplexInput"),
    priceBwDuplexInput: document.getElementById("priceBwDuplexInput"),
    priceColorSimplexInput: document.getElementById("priceColorSimplexInput"),
    priceColorDuplexInput: document.getElementById("priceColorDuplexInput"),
    secondsBwInput: document.getElementById("secondsBwInput"),
    secondsColorInput: document.getElementById("secondsColorInput"),
    savePricingBtn: document.getElementById("savePricingBtn"),

    adminPrinterModeSelect: document.getElementById("adminPrinterModeSelect"),
    adminDefaultPrinterSelect: document.getElementById("adminDefaultPrinterSelect"),
    adminAgentKeyInput: document.getElementById("adminAgentKeyInput"),
    piAgentStatusBox: document.getElementById("piAgentStatusBox"),
    adminPrintersList: document.getElementById("adminPrintersList"),
    savePrinterSettingsBtn: document.getElementById("savePrinterSettingsBtn"),
    scanPrintersBtn: document.getElementById("scanPrintersBtn"),
    scanNetworkIpInput: document.getElementById("scanNetworkIpInput"),
    scanIpBtn: document.getElementById("scanIpBtn"),
    printerScanSummaryBox: document.getElementById("printerScanSummaryBox"),

    newAdminUsername: document.getElementById("newAdminUsername"),
    currentAdminPassword: document.getElementById("currentAdminPassword"),
    newAdminPassword: document.getElementById("newAdminPassword"),
    saveCredentialsBtn: document.getElementById("saveCredentialsBtn"),
    downloadDbBackupBtn: document.getElementById("downloadDbBackupBtn"),

    // Payment & Telegram Controls
    paymentEnabledInput: document.getElementById("paymentEnabledInput"),
    paymentCardNumberInput: document.getElementById("paymentCardNumberInput"),
    paymentCardHolderInput: document.getElementById("paymentCardHolderInput"),
    telegramBotUsernameInput: document.getElementById("telegramBotUsernameInput"),
    paymentWindowSecondsInput: document.getElementById("paymentWindowSecondsInput"),
    savePaymentSettingsBtn: document.getElementById("savePaymentSettingsBtn"),
    adminTelegramStatusBadge: document.getElementById("adminTelegramStatusBadge"),
    adminTelegramAccountDetails: document.getElementById("adminTelegramAccountDetails"),
    telegramPhoneInput: document.getElementById("telegramPhoneInput"),
    telegramSendCodeBtn: document.getElementById("telegramSendCodeBtn"),
    telegramCodeGroup: document.getElementById("telegramCodeGroup"),
    telegramCodeInput: document.getElementById("telegramCodeInput"),
    telegramPasswordInput: document.getElementById("telegramPasswordInput"),
    telegramVerifyCodeBtn: document.getElementById("telegramVerifyCodeBtn"),
    telegramDisconnectBtn: document.getElementById("telegramDisconnectBtn"),
    telegramAuthMessage: document.getElementById("telegramAuthMessage"),
    refreshHumoPaymentsBtn: document.getElementById("refreshHumoPaymentsBtn"),
    adminHumoPaymentsList: document.getElementById("adminHumoPaymentsList"),

    adminJobSearchInput: document.getElementById("adminJobSearchInput"),
    adminJobStatusFilter: document.getElementById("adminJobStatusFilter"),
    adminClearJobsBtn: document.getElementById("adminClearJobsBtn"),
    adminJobsList: document.getElementById("adminJobsList"),

    // Zoom & Job Result Modals
    zoomModal: document.getElementById("zoomModal"),
    zoomModalTitle: document.getElementById("zoomModalTitle"),
    zoomSelectionStatus: document.getElementById("zoomSelectionStatus"),
    zoomToggleSelectBtn: document.getElementById("zoomToggleSelectBtn"),
    zoomRotateBtn: document.getElementById("zoomRotateBtn"),
    zoomCloseBtn: document.getElementById("zoomCloseBtn"),
    zoomPrevBtn: document.getElementById("zoomPrevBtn"),
    zoomNextBtn: document.getElementById("zoomNextBtn"),
    zoomCanvas: document.getElementById("zoomCanvas"),

    jobResultModal: document.getElementById("jobResultModal"),
    jobResultBody: document.getElementById("jobResultBody"),
    jobResultPdfLink: document.getElementById("jobResultPdfLink"),
    jobModalCloseBtn: document.getElementById("jobModalCloseBtn"),
    jobDoneBtn: document.getElementById("jobDoneBtn"),

    toastContainer: document.getElementById("toastContainer"),
  };

  function showToast(message, type = "info") {
    const toast = document.createElement("div");
    toast.className = `toast ${type === "error" ? "is-error" : type === "success" ? "is-success" : ""}`;
    toast.textContent = message;
    el.toastContainer.appendChild(toast);
    setTimeout(() => toast.remove(), 4200);
  }

  function escapeHtml(str) {
    return String(str || "")
      .replace(/(?:[\u{1F300}-\u{1FAFF}\u2600-\u27BF]\uFE0F?)\s?/gu, "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function formatBytes(bytes) {
    if (!bytes) return "0 B";
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
  }

  function formatMoney(amount) {
    return `${Number(amount || 0).toLocaleString("ru-RU")} so'm`;
  }

  function formatDuration(totalSeconds) {
    const sec = Math.max(0, Math.round(Number(totalSeconds || 0)));
    if (sec === 0) return "~0 soniya";
    if (sec < 60) return `~${sec} soniya`;
    const mins = Math.floor(sec / 60);
    const rem = sec % 60;
    return rem > 0 ? `~${mins} daq ${rem} soniya` : `~${mins} daqiqa`;
  }

  function stopCountdownTimer() {
    if (state.countdownTimer) {
      clearInterval(state.countdownTimer);
      state.countdownTimer = null;
    }
  }

  function formatDateTime(iso) {
    if (!iso) return "";
    try {
      const dt = new Date(iso);
      return dt.toLocaleString("uz-UZ", {
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch (_) {
      return iso;
    }
  }

  function readJsonStorage(storageObj, key, fallback = null) {
    try {
      const raw = storageObj.getItem(key);
      return raw ? JSON.parse(raw) : fallback;
    } catch (_) {
      return fallback;
    }
  }

  function saveStudioDraft() {
    if (state.isRestoringSession || !state.currentDoc) return;
    try {
      const payload = {
        docId: state.currentDoc.id,
        selectedPages: Array.from(state.selectedPages).sort((a, b) => a - b),
        rotations: state.rotations,
        copies: state.copies,
        colorMode: state.colorMode,
        colorPages: Array.from(state.colorPages).sort((a, b) => a - b),
        colorPagesText: el.colorPagesInput ? el.colorPagesInput.value : "",
        orientation: state.orientation,
        pagesPerSheet: state.pagesPerSheet,
        paperSize: state.paperSize,
        studentName: el.studentNameInput ? el.studentNameInput.value : "",
        printerName: el.printerSelect ? el.printerSelect.value : "",
        savedAt: Date.now(),
      };
      localStorage.setItem(STUDIO_DRAFT_KEY, JSON.stringify(payload));
    } catch (_) {
      // Ignore storage quota errors
    }
  }

  function clearStudioDraft() {
    try {
      localStorage.removeItem(STUDIO_DRAFT_KEY);
    } catch (_) {
      // Ignore
    }
  }

  function saveModalState(openJobId, dismissedJobId = "") {
    try {
      localStorage.setItem(
        MODAL_STATE_KEY,
        JSON.stringify({
          openJobId: openJobId || "",
          dismissedJobId: dismissedJobId || "",
          savedAt: Date.now(),
        })
      );
    } catch (_) {
      // Ignore
    }
  }

  function setActiveAdminTab(tabName) {
    const target = tabName || "orders";
    try {
      sessionStorage.setItem(ADMIN_TAB_KEY, target);
    } catch (_) {
      // Ignore
    }
    document.querySelectorAll(".admin-nav-btn[data-admin-tab]").forEach((b) => {
      b.classList.toggle("is-active", b.getAttribute("data-admin-tab") === target);
    });
    document.querySelectorAll("#adminView [data-admin-panel]").forEach((panel) => {
      panel.classList.toggle("hidden", panel.getAttribute("data-admin-panel") !== target);
    });
  }

  function setActiveView(viewName) {
    const isAdmin = viewName === "admin";
    try {
      sessionStorage.setItem(ADMIN_VIEW_KEY, isAdmin ? "admin" : "student");
    } catch (_) {
      // Ignore
    }
    el.studentView.classList.toggle("is-active", !isAdmin);
    el.adminView.classList.toggle("is-active", isAdmin);

    const hasToken = Boolean(SmartPrintApi.getAdminToken());
    el.backToStudioBtn.classList.toggle("hidden", !isAdmin);
    el.adminLogoutBtn.classList.toggle("hidden", !hasToken);
    el.openAdminBtn.classList.toggle("is-active", isAdmin);
    el.openAdminBtnLabel.textContent = hasToken ? "Admin panel" : "Admin kirish";
  }

  async function loadSystemStatus() {
    try {
      const status = await SmartPrintApi.getSystemStatus();
      state.systemStatus = status;

      if (status.hardware_connected) {
        el.printerModeBadge.className = "status-pill status-pill--live";
        el.printerModeText.textContent = "Chop etish: Faol";
      } else {
        el.printerModeBadge.className = "status-pill status-pill--dryrun";
        el.printerModeText.textContent = "Printer: Test rejimi";
      }

      const physicalPrinters = (status.printers || []).filter((p) => !p.is_virtual);
      const readyPrinters = physicalPrinters.filter((p) => p.ready_to_print || !p.is_offline);
      const candidatePool = readyPrinters.length ? readyPrinters : physicalPrinters;
      const preferred =
        candidatePool.find((p) => p.name === status.default_printer_name) ||
        candidatePool.find((p) => p.name.toLowerCase().includes("canon")) ||
        candidatePool.find((p) => p.is_default) ||
        candidatePool[0];

      el.detectedPrinterName.textContent = preferred
        ? preferred.name
        : "Printer ulanmagan";
      if (el.heroPrinterName) {
        el.heroPrinterName.textContent = preferred ? preferred.name : "Test rejimi";
      }
      if (status.pricing) {
        const bwPriceStr = formatMoney(status.pricing.bw_simplex || 400);
        const colorPriceStr = formatMoney(status.pricing.color_simplex || 1000);
        if (el.heroBwPrice) el.heroBwPrice.textContent = bwPriceStr;
        if (el.heroColorPrice) el.heroColorPrice.textContent = colorPriceStr;
        if (el.segBwPriceBadge) el.segBwPriceBadge.textContent = bwPriceStr;
        if (el.segColorPriceBadge) el.segColorPriceBadge.textContent = colorPriceStr;
      }

      const currentVal = state.pendingRestoredPrinterName || el.printerSelect.value;
      state.pendingRestoredPrinterName = "";
      el.printerSelect.innerHTML = `<option value="">Avtomatik (Keyin ulanadi)</option>`;
      physicalPrinters.forEach((printer) => {
        const opt = document.createElement("option");
        opt.value = printer.name;
        opt.textContent = `${printer.name} — ${printer.status_text}`;
        el.printerSelect.appendChild(opt);
      });
      if (currentVal && Array.from(el.printerSelect.options).some((o) => o.value === currentVal)) {
        el.printerSelect.value = currentVal;
      } else if (preferred) {
        el.printerSelect.value = preferred.name;
      }

      updateMetricsSummary();
    } catch (_) {
      el.detectedPrinterName.textContent = "Tizim holati olinmadi";
    }
  }

  // ---------------------------------------------------------------------------
  // Student Document Upload & Page Studio
  // ---------------------------------------------------------------------------

  function setLoader(active, text = "Hujjat yuklanmoqda va betlarga ajratilmoqda...") {
    el.uploadLoader.classList.toggle("hidden", !active);
    el.uploadLoaderText.textContent = text;
    el.browseFileBtn.disabled = active;
    el.loadSampleBtn.disabled = active;
  }

  async function handleFileUpload(file) {
    if (!file) return;
    setLoader(true, `"${file.name}" yuklanmoqda va sahifalarga tayyorlanmoqda...`);
    try {
      const doc = await SmartPrintApi.uploadDocument(file);
      await openDocumentInStudio(doc);
      showToast(`"${doc.original_filename}" muvaffaqiyatli yuklandi (${doc.page_count} bet).`, "success");
    } catch (err) {
      showToast(err.message, "error");
    } finally {
      setLoader(false);
    }
  }

  async function handleLoadSample() {
    setLoader(true, "8 betlik namuna o'quv qo'llanma tayyorlanmoqda...");
    try {
      const doc = await SmartPrintApi.loadSampleDocument();
      await openDocumentInStudio(doc);
      showToast("8 betlik namuna hujjat ochildi!", "success");
    } catch (err) {
      showToast(err.message, "error");
    } finally {
      setLoader(false);
    }
  }

  function applyStudioDraft(doc, savedDraft) {
    const pageCount = Math.max(1, parseInt(doc.page_count, 10) || 1);
    const allPages = Array.from({ length: pageCount }, (_, i) => i + 1);
    if (!savedDraft || typeof savedDraft !== "object") {
      state.rotations = {};
      state.colorPages = new Set();
      state.selectedPages = new Set(allPages);
      state.copies = 1;
      state.colorMode = "bw";
      state.orientation = "portrait";
      state.pagesPerSheet = 1;
      state.paperSize = "A4";
      if (el.colorPagesInput) el.colorPagesInput.value = "";
      if (el.copiesValue) el.copiesValue.textContent = "1";
      if (el.pagesPerSheetSelect) el.pagesPerSheetSelect.value = "1";
      if (el.paperSizeSelect) el.paperSizeSelect.value = "A4";
      el.orientPortraitBtn.classList.add("is-active");
      el.orientLandscapeBtn.classList.remove("is-active");
      setColorMode("bw");
      return;
    }

    const validRotations = {};
    if (savedDraft.rotations && typeof savedDraft.rotations === "object") {
      Object.entries(savedDraft.rotations).forEach(([k, v]) => {
        const pg = parseInt(k, 10);
        const deg = parseInt(v, 10);
        if (pg >= 1 && pg <= pageCount && [90, 180, 270].includes(((deg % 360) + 360) % 360)) {
          validRotations[String(pg)] = ((deg % 360) + 360) % 360;
        }
      });
    }
    state.rotations = validRotations;

    const restoredSelected = Array.isArray(savedDraft.selectedPages)
      ? savedDraft.selectedPages
          .map((n) => parseInt(n, 10))
          .filter((n) => Number.isInteger(n) && n >= 1 && n <= pageCount)
      : allPages;
    state.selectedPages = new Set(restoredSelected);

    const restoredColorPages = Array.isArray(savedDraft.colorPages)
      ? savedDraft.colorPages
          .map((n) => parseInt(n, 10))
          .filter((n) => Number.isInteger(n) && n >= 1 && n <= pageCount)
      : [];
    state.colorPages = new Set(restoredColorPages);
    if (el.colorPagesInput) {
      el.colorPagesInput.value =
        typeof savedDraft.colorPagesText === "string"
          ? savedDraft.colorPagesText
          : PageSelector.formatRange(restoredColorPages);
    }

    state.copies = Math.max(1, Math.min(99, parseInt(savedDraft.copies, 10) || 1));
    if (el.copiesValue) el.copiesValue.textContent = String(state.copies);

    const orient = savedDraft.orientation === "landscape" ? "landscape" : "portrait";
    state.orientation = orient;
    el.orientPortraitBtn.classList.toggle("is-active", orient === "portrait");
    el.orientLandscapeBtn.classList.toggle("is-active", orient === "landscape");

    const pps = [1, 2, 4].includes(parseInt(savedDraft.pagesPerSheet, 10))
      ? parseInt(savedDraft.pagesPerSheet, 10)
      : 1;
    state.pagesPerSheet = pps;
    if (el.pagesPerSheetSelect) el.pagesPerSheetSelect.value = String(pps);

    const paper = ["A4", "A5", "Letter"].includes(savedDraft.paperSize) ? savedDraft.paperSize : "A4";
    state.paperSize = paper;
    if (el.paperSizeSelect) el.paperSizeSelect.value = paper;

    if (el.studentNameInput && typeof savedDraft.studentName === "string") {
      el.studentNameInput.value = savedDraft.studentName;
    }
    if (typeof savedDraft.printerName === "string" && savedDraft.printerName) {
      if (el.printerSelect && Array.from(el.printerSelect.options).some((o) => o.value === savedDraft.printerName)) {
        el.printerSelect.value = savedDraft.printerName;
      } else {
        state.pendingRestoredPrinterName = savedDraft.printerName;
      }
    }

    const mode = ["bw", "color", "mixed"].includes(savedDraft.colorMode) ? savedDraft.colorMode : "bw";
    setColorMode(mode);
  }

  async function openDocumentInStudio(doc, savedDraft = null) {
    state.isRestoringSession = true;
    try {
      state.currentDoc = doc;
      applyStudioDraft(doc, savedDraft);

      el.docFileTypeBadge.textContent = (doc.file_type || "PDF").toUpperCase();
      el.docTitleText.textContent = doc.original_filename;
      el.docTitleText.title = doc.original_filename;
      el.docMetaSubtext.textContent = `${doc.page_count} bet • ${formatBytes(doc.file_size)}`;

      el.uploadView.classList.add("hidden");
      el.studioWorkspace.classList.remove("hidden");

      buildPageCards(doc.page_count);
      syncSelectionUI({ syncTextInput: true });
      updateColorFilterClass();
      updateMetricsSummary();

      await PdfRenderer.loadPdf(doc.pdf_url, doc.page_count);
      await PdfRenderer.renderAllThumbnails(state.pageCanvases, state.rotations);
    } finally {
      state.isRestoringSession = false;
    }
    saveStudioDraft();
  }

  function buildPageCards(pageCount) {
    el.pagesGrid.innerHTML = "";
    state.pageCanvases.clear();
    state.pageCards.clear();

    for (let pageNum = 1; pageNum <= pageCount; pageNum += 1) {
      const card = document.createElement("div");
      card.className = "page-card is-selected";
      card.dataset.page = String(pageNum);
      card.setAttribute("role", "button");
      card.setAttribute("tabindex", "0");
      card.setAttribute("aria-label", `${pageNum}-betni tanlash yoki bekor qilish`);

      const head = document.createElement("div");
      head.className = "page-card-head";
      head.innerHTML = `
        <span class="page-num-badge">${pageNum}-bet</span>
        <span class="page-select-pill">Tanlangan</span>
      `;

      const frame = document.createElement("div");
      frame.className = "page-canvas-frame";
      const canvas = document.createElement("canvas");
      frame.appendChild(canvas);

      const actions = document.createElement("div");
      actions.className = "page-card-actions";

      const zoomBtn = document.createElement("button");
      zoomBtn.type = "button";
      zoomBtn.className = "card-action-btn";
      zoomBtn.textContent = "Ko'rish";
      zoomBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        openZoomModal(pageNum);
      });

      const rotateBtn = document.createElement("button");
      rotateBtn.type = "button";
      rotateBtn.className = "card-action-btn";
      rotateBtn.textContent = "90° burish";
      rotateBtn.addEventListener("click", async (e) => {
        e.stopPropagation();
        await rotatePage(pageNum);
      });

      const colorBtn = document.createElement("button");
      colorBtn.type = "button";
      colorBtn.className = "card-action-btn card-color-btn";
      colorBtn.textContent = "Oq-qora";
      colorBtn.title = "Shu betni rangli yoki oq-qora qilish";
      colorBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        togglePageColor(pageNum);
      });

      actions.appendChild(zoomBtn);
      actions.appendChild(rotateBtn);
      actions.appendChild(colorBtn);

      card.appendChild(head);
      card.appendChild(frame);
      card.appendChild(actions);

      card.addEventListener("click", () => togglePageSelection(pageNum));
      card.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          togglePageSelection(pageNum);
        }
      });

      el.pagesGrid.appendChild(card);
      state.pageCanvases.set(pageNum, canvas);
      state.pageCards.set(pageNum, card);
    }
  }

  function togglePageSelection(pageNum) {
    if (state.selectedPages.has(pageNum)) {
      state.selectedPages.delete(pageNum);
    } else {
      state.selectedPages.add(pageNum);
    }
    syncSelectionUI({ syncTextInput: true });
  }

  async function rotatePage(pageNum) {
    const key = String(pageNum);
    state.rotations[key] = ((state.rotations[key] || 0) + 90) % 360;
    saveStudioDraft();
    const canvas = state.pageCanvases.get(pageNum);
    if (canvas) {
      await PdfRenderer.renderPageToCanvas(pageNum, canvas, 340, state.rotations[key], true);
    }
    if (!el.zoomModal.classList.contains("hidden") && state.zoomPage === pageNum) {
      await renderZoomCanvas();
    }
  }

  function syncSelectionUI({ syncTextInput = true } = {}) {
    if (!state.currentDoc) return;
    const total = state.currentDoc.page_count;
    const sorted = Array.from(state.selectedPages).sort((a, b) => a - b);
    const count = sorted.length;

    el.selectionSummaryBadge.textContent = `${total} ta betdan ${count} tasi tanlandi`;

    state.pageCards.forEach((card, pageNum) => {
      const isSelected = state.selectedPages.has(pageNum);
      card.classList.toggle("is-selected", isSelected);
      const pill = card.querySelector(".page-select-pill");
      if (pill) {
        pill.textContent = isSelected ? "Tanlangan" : "O'tkaziladi";
      }
    });

    if (syncTextInput) {
      el.pageRangeInput.value = PageSelector.formatRange(sorted);
      el.pageRangeInput.classList.remove("is-invalid");
      el.rangeErrorMsg.classList.add("hidden");
    }

    el.printSubmitBtn.disabled = count === 0;
    el.printValidationHint.classList.toggle("hidden", count > 0);

    if (!el.zoomModal.classList.contains("hidden")) {
      const zoomSelected = state.selectedPages.has(state.zoomPage);
      el.zoomSelectionStatus.textContent = zoomSelected ? "Tanlangan" : "Tanlanmagan";
      el.zoomSelectionStatus.className = `status-tag ${zoomSelected ? "status-tag--ok" : ""}`;
    }

    updateMetricsSummary();
  }

  function setColorMode(mode) {
    state.colorMode = mode;
    el.colorBwBtn.classList.toggle("is-active", mode === "bw");
    el.colorColorBtn.classList.toggle("is-active", mode === "color");
    if (el.colorMixedBtn) {
      el.colorMixedBtn.classList.toggle("is-active", mode === "mixed");
    }
    if (el.mixedColorBox) {
      el.mixedColorBox.classList.toggle("hidden", mode !== "mixed");
    }
    updateColorFilterClass();
    updateMetricsSummary();
  }

  function togglePageColor(pageNum) {
    if (!state.currentDoc) return;
    if (state.colorMode === "bw") {
      state.colorPages = new Set([pageNum]);
    } else if (state.colorMode === "color") {
      state.colorPages = new Set(
        Array.from({ length: state.currentDoc.page_count }, (_, i) => i + 1).filter(
          (p) => p !== pageNum
        )
      );
    } else if (state.colorPages.has(pageNum)) {
      state.colorPages.delete(pageNum);
    } else {
      state.colorPages.add(pageNum);
    }

    if (el.colorPagesInput) {
      const sorted = Array.from(state.colorPages).sort((a, b) => a - b);
      el.colorPagesInput.value = PageSelector.formatRange(sorted);
      el.colorPagesInput.classList.remove("is-invalid");
    }
    setColorMode("mixed");
  }

  function isPageRenderedInColor(pageNum) {
    if (state.colorMode === "color") return true;
    if (state.colorMode === "mixed") return state.colorPages.has(pageNum);
    return false;
  }

  function updateColorFilterClass() {
    el.pagesGrid.classList.remove("is-bw");
    state.pageCards.forEach((card, pageNum) => {
      const isColor = isPageRenderedInColor(pageNum);
      card.classList.toggle("is-bw-page", !isColor);
      card.classList.toggle("is-color-page", isColor);
      const btn = card.querySelector(".card-color-btn");
      if (btn) {
        btn.classList.toggle("is-color", isColor);
        btn.textContent = isColor ? "Rangli" : "Oq-qora";
      }
    });
    const zoomWrap = el.zoomCanvas.parentElement;
    if (zoomWrap) {
      zoomWrap.classList.toggle("is-bw", !isPageRenderedInColor(state.zoomPage));
    }
  }

  function computeClientSheetBreakdown(selectedArr) {
    if (!selectedArr.length) {
      return { physicalSheets: 0, bwSheets: 0, colorSheets: 0 };
    }
    const faces = [];
    for (let i = 0; i < selectedArr.length; i += state.pagesPerSheet) {
      faces.push(selectedArr.slice(i, i + state.pagesPerSheet));
    }
    const facesPerSheet = state.duplex === "duplex" ? 2 : 1;
    let bwPerCopy = 0;
    let colorPerCopy = 0;
    for (let i = 0; i < faces.length; i += facesPerSheet) {
      const sheetPages = faces.slice(i, i + facesPerSheet).flat();
      const hasColor =
        state.colorMode === "color" ||
        (state.colorMode === "mixed" && sheetPages.some((p) => state.colorPages.has(p)));
      if (hasColor) {
        colorPerCopy += 1;
      } else {
        bwPerCopy += 1;
      }
    }
    const bwSheets = bwPerCopy * state.copies;
    const colorSheets = colorPerCopy * state.copies;
    return {
      physicalSheets: bwSheets + colorSheets,
      bwSheets,
      colorSheets,
    };
  }

  function updateMetricsSummary() {
    const selectedArr = Array.from(state.selectedPages).sort((a, b) => a - b);
    const count = selectedArr.length;
    const rangeStr = PageSelector.formatRange(selectedArr);

    el.summaryPagesText.textContent = count > 0 ? `${rangeStr} (${count} bet)` : "Tanlanmagan";
    el.summaryCopiesText.textContent = `${state.copies} nusxa`;

    const { physicalSheets, bwSheets, colorSheets } = computeClientSheetBreakdown(selectedArr);

    const pricing = (state.systemStatus && state.systemStatus.pricing) || {
      bw_simplex: 400,
      bw_duplex: 700,
      color_simplex: 1000,
      color_duplex: 1800,
      seconds_bw_per_sheet: 7,
      seconds_color_per_sheet: 14,
      warmup_seconds: 5,
    };

    const bwUnit = state.duplex === "duplex" ? pricing.bw_duplex : pricing.bw_simplex;
    const colorUnit = state.duplex === "duplex" ? pricing.color_duplex : pricing.color_simplex;

    const secBw = pricing.seconds_bw_per_sheet || 7;
    const secColor = pricing.seconds_color_per_sheet || 14;
    const warmup = pricing.warmup_seconds ?? 5;
    const duplexFactor = state.duplex === "duplex" ? 1.5 : 1.0;
    const estimatedSeconds =
      physicalSheets > 0
        ? Math.ceil(warmup + (bwSheets * secBw + colorSheets * secColor) * duplexFactor)
        : 0;

    const estimatedCost = bwSheets * bwUnit + colorSheets * colorUnit;

    if (state.colorMode === "mixed" && physicalSheets > 0) {
      el.summarySheetsText.textContent = `${physicalSheets} varaq (${bwSheets} oq-qora, ${colorSheets} rangli)`;
      el.summaryUnitPriceText.textContent = `${formatMoney(bwUnit)} / ${formatMoney(colorUnit)}`;
    } else {
      el.summarySheetsText.textContent = `${physicalSheets} varaq`;
      el.summaryUnitPriceText.textContent = formatMoney(
        state.colorMode === "color" ? colorUnit : bwUnit
      );
    }

    if (el.summaryTimeText) {
      el.summaryTimeText.textContent = formatDuration(estimatedSeconds);
    }
    const costFormatted = formatMoney(estimatedCost);
    el.summaryCostText.textContent = costFormatted;
    if (el.printSubmitPriceBadge) {
      el.printSubmitPriceBadge.textContent = costFormatted;
    }
    if (el.mobileStickyPages) {
      el.mobileStickyPages.textContent = `${count} bet • ${physicalSheets} varaq`;
    }
    if (el.mobileStickyTotal) {
      el.mobileStickyTotal.textContent = costFormatted;
    }
    if (el.mobilePrintSubmitBtn) {
      el.mobilePrintSubmitBtn.disabled = count === 0;
    }
    document.querySelectorAll(".copy-preset-btn[data-copy-preset]").forEach((btn) => {
      const presetVal = parseInt(btn.getAttribute("data-copy-preset"), 10);
      btn.classList.toggle("is-active", presetVal === state.copies);
    });
    saveStudioDraft();
  }

  async function openZoomModal(pageNum) {
    if (!state.currentDoc) return;
    state.zoomPage = pageNum;
    el.zoomModal.classList.remove("hidden");
    await renderZoomCanvas();
  }

  async function renderZoomCanvas() {
    if (!state.currentDoc) return;
    const total = state.currentDoc.page_count;
    const pageNum = state.zoomPage;
    el.zoomModalTitle.textContent = `${pageNum}-bet / ${total}`;
    const isSelected = state.selectedPages.has(pageNum);
    el.zoomSelectionStatus.textContent = isSelected ? "Tanlangan" : "Tanlanmagan";
    el.zoomSelectionStatus.className = `status-tag ${isSelected ? "status-tag--ok" : ""}`;
    el.zoomPrevBtn.disabled = pageNum <= 1;
    el.zoomNextBtn.disabled = pageNum >= total;

    const zoomWrap = el.zoomCanvas.parentElement;
    if (zoomWrap) {
      zoomWrap.classList.toggle("is-bw", !isPageRenderedInColor(pageNum));
    }

    const rot = state.rotations[String(pageNum)] || 0;
    await PdfRenderer.renderPageToCanvas(pageNum, el.zoomCanvas, 720, rot, false);
  }

  function closeZoomModal() {
    el.zoomModal.classList.add("hidden");
  }

  async function submitPrintJob() {
    if (!state.currentDoc) return;
    const selectedPages = Array.from(state.selectedPages).sort((a, b) => a - b);
    if (!selectedPages.length) {
      showToast("Kamida bitta bet tanlang.", "error");
      return;
    }

    el.printSubmitBtn.disabled = true;
    const originalHtml = el.printSubmitBtn.innerHTML;
    el.printSubmitBtn.textContent = "Tayyorlanmoqda...";

    try {
      const payload = {
        document_id: state.currentDoc.id,
        selected_pages: selectedPages,
        page_range_text: PageSelector.formatRange(selectedPages),
        rotations: state.rotations,
        copies: state.copies,
        color_mode: state.colorMode,
        color_pages: Array.from(state.colorPages).sort((a, b) => a - b),
        color_pages_text: el.colorPagesInput ? el.colorPagesInput.value.trim() : "",
        duplex: state.duplex,
        orientation: state.orientation,
        pages_per_sheet: state.pagesPerSheet,
        paper_size: state.paperSize,
        student_name: el.studentNameInput.value.trim(),
        printer_name: el.printerSelect.value,
      };

      const job = await SmartPrintApi.createPrintJob(payload);
      showJobResultModal(job);
      await Promise.all([loadLiveQueue(), refreshMyActiveJobs()]);
    } catch (err) {
      showToast(err.message, "error");
    } finally {
      el.printSubmitBtn.innerHTML = originalHtml;
      el.printSubmitBtn.disabled = state.selectedPages.size === 0;
    }
  }

  function formatColorLabel(job) {
    if (job.color_mode === "mixed") {
      return `Aralash (${job.bw_sheets} oq-qora, ${job.color_sheets} rangli)`;
    }
    return job.color_mode === "color" ? "Rangli" : "Oq-qora";
  }

  function buildJobLiveBannerMarkup(job) {
    const qState = job.queue_state || "ACTIVE_PRINTING";
    const totalSec = Math.max(1, parseInt(job.estimated_seconds, 10) || 5);
    const remSec = Math.max(0, parseInt(job.remaining_print_seconds, 10) || 0);
    const pct =
      qState === "AWAITING_CONFIRMATION" || qState === "COMPLETED"
        ? 100
        : Math.max(4, Math.min(100, Math.round(((totalSec - remSec) / totalSec) * 100)));

    if (qState === "COMPLETED") {
      return `
        <div class="modal-live-banner is-done">
          <div class="modal-live-head">
            <strong>Tasdiqlandi — Chop etish yakunlandi</strong>
            <span>Navbat keyingi foydalanuvchiga o'tdi</span>
          </div>
        </div>
      `;
    }
    if (qState === "CANCELLED") {
      return `
        <div class="modal-live-banner is-cancelled">
          <div class="modal-live-head">
            <strong>Buyurtma bekor qilindi</strong>
          </div>
        </div>
      `;
    }
    if (qState === "WAITING_IN_QUEUE") {
      return `
        <div class="modal-live-banner is-waiting">
          <div class="modal-live-head">
            <strong>Navbatda ${job.queue_position}-o'rindasiz</strong>
            <span>Taxminiy kutish: ${escapeHtml(formatDuration(job.estimated_wait_seconds))}</span>
          </div>
          <p class="modal-live-sub">
            Oldingi foydalanuvchi qog'ozlarni chiqarib tasdiqlagach, sizning hujjatingiz avtomatik chop etiladi.
          </p>
          <div class="live-confirm-actions">
            <button type="button" class="btn btn-danger-outline btn-sm" data-cancel-job-id="${escapeHtml(job.id)}">
              Navbatdan chiqish (Bekor qilish)
            </button>
          </div>
        </div>
      `;
    }
    if (qState === "AWAITING_CONFIRMATION") {
      const autoSec = Math.max(0, parseInt(job.confirm_remaining_seconds, 10) || 0);
      return `
        <div class="modal-live-banner is-confirm">
          <div class="modal-live-title">
            Qog'ozlaringiz printerdan chiqib bo'ldimi? Rostdan ham chiqarib oldingizmi?
          </div>
          <p class="modal-live-sub">
            Qog'ozlarni qo'lingizga olgach tasdiqlang — shundan so'ng navbat keyingi foydalanuvchiga beriladi (${autoSec} soniyadan keyin avtomatik bo'shaydi).
          </p>
          <div class="live-confirm-actions">
            <button type="button" class="btn btn-print btn-sm" data-confirm-job-id="${escapeHtml(job.id)}">
              Ha, chiqarib bo'ldim (Navbatni bo'shatish)
            </button>
            <button type="button" class="btn btn-secondary btn-sm" data-extend-job-id="${escapeHtml(job.id)}">
              Hali chiqyapti (+15s)
            </button>
          </div>
        </div>
      `;
    }

    if (qState === "AWAITING_PAYMENT") {
      const payCfg = (state.systemStatus && state.systemStatus.payment) || {};
      const windowSec = Math.max(30, parseInt(payCfg.window_seconds, 10) || 120);
      const remSec = job.payment_deadline_ts
        ? Math.max(0, Math.ceil(job.payment_deadline_ts - Date.now() / 1000))
        : Math.max(0, parseInt(job.payment_remaining_seconds, 10) || 0);
      const pct = Math.max(0, Math.min(100, Math.round((remSec / windowSec) * 100)));
      const cardNum = payCfg.card_number || "Karta raqami kiritilmagan — operatorga murojaat qiling";
      const cardHolder = payCfg.card_holder || "";
      const exactAmount = String(Number(job.estimated_cost || 0));
      const mins = String(Math.floor(remSec / 60)).padStart(2, "0");
      const secs = String(remSec % 60).padStart(2, "0");
      const hasErr = job.payment_status === "UNVERIFIED" || job.payment_status === "EXPIRED";

      return `
        <div class="modal-live-banner is-payment">
          <div class="countdown-head">
            <span>To'lov uchun ajratilgan vaqt</span>
            <strong id="jobPaymentCountdownText">${remSec > 0 ? `${mins}:${secs} qoldi` : "Vaqt tugadi!"}</strong>
          </div>
          <div class="countdown-bar-track">
            <div class="countdown-bar-fill is-payment-fill" id="jobPaymentCountdownFill" style="width: ${pct}%"></div>
          </div>

          <div class="payment-card-visual">
            <div class="payment-card-row">
              <div>
                <span class="pay-label">HUMO karta raqami</span>
                <strong class="pay-value pay-card-num">${escapeHtml(cardNum)}</strong>
                ${cardHolder ? `<span class="pay-holder">${escapeHtml(cardHolder)}</span>` : ""}
              </div>
              <button type="button" class="btn btn-secondary btn-xs" data-copy-text="${escapeHtml(cardNum.replace(/\s+/g, ""))}">
                Kartani nusxalash
              </button>
            </div>
            <div class="payment-card-row payment-amount-row">
              <div>
                <span class="pay-label">Aniq o'tkaziladigan summa</span>
                <strong class="pay-value pay-amount">${formatMoney(job.estimated_cost)}</strong>
              </div>
              <button type="button" class="btn btn-secondary btn-xs" data-copy-text="${escapeHtml(exactAmount)}">
                Summani nusxalash
              </button>
            </div>
          </div>

          <div class="receipt-upload-zone">
            <label class="form-label" for="jobReceiptFileInput">
              To'lov cheki (Click / Payme / Uzum skrinshot yoki PDF — rasmiy isbot sifatida saqlanadi)
            </label>
            <input id="jobReceiptFileInput" type="file" accept=".jpg,.jpeg,.png,.webp,.pdf,image/*,application/pdf" class="receipt-file-input" />
            ${
              job.has_receipt
                ? `<div class="receipt-saved-badge">Yuklangan chek: <strong>${escapeHtml(job.receipt_filename || "chek")}</strong></div>`
                : ""
            }
          </div>

          <div id="jobPaymentErrorBox" class="pay-error-box ${hasErr && job.payment_note ? "" : "hidden"}">
            ${hasErr && job.payment_note ? escapeHtml(job.payment_note) : ""}
          </div>

          <div class="live-confirm-actions">
            <button type="button" id="verifyPaymentSubmitBtn" class="btn btn-print btn-sm" data-verify-payment-job-id="${escapeHtml(job.id)}">
              To'lov qildim va chekni tasdiqlash
            </button>
            <button type="button" id="renewPaymentTimerBtn" class="btn btn-secondary btn-sm" data-renew-payment-job-id="${escapeHtml(job.id)}">
              120s vaqtni yangilash
            </button>
            <button type="button" class="btn btn-danger-outline btn-sm" data-cancel-job-id="${escapeHtml(job.id)}">
              Bekor qilish
            </button>
          </div>
        </div>
      `;
    }

    return `
      <div class="modal-live-banner is-printing">
        <div class="countdown-head">
          <span>Printer chiqish taymeri</span>
          <strong id="jobCountdownText">${remSec > 0 ? `${escapeHtml(formatDuration(remSec))} qoldi` : "Yakunlanmoqda..."}</strong>
        </div>
        <div class="countdown-bar-track">
          <div class="countdown-bar-fill" id="jobCountdownFill" style="width: ${pct}%"></div>
        </div>
        <div class="live-confirm-actions live-confirm-actions--compact">
          <button type="button" class="btn btn-primary btn-sm" data-confirm-job-id="${escapeHtml(job.id)}">
            Qog'oz chiqib bo'ldi — Tasdiqlash
          </button>
          <button type="button" class="btn btn-ghost btn-sm" data-extend-job-id="${escapeHtml(job.id)}">
            +15s qo'shish
          </button>
        </div>
      </div>
    `;
  }

  function closeJobModal() {
    stopCountdownTimer();
    const closingId = state.activeModalJob && state.activeModalJob.id ? state.activeModalJob.id : "";
    saveModalState("", closingId);
    state.activeModalJob = null;
    el.jobResultModal.classList.add("hidden");
  }

  function showJobResultModal(job) {
    stopCountdownTimer();
    state.activeModalJob = job;
    saveModalState(job && job.id ? job.id : "", "");
    el.jobResultPdfLink.href = job.pdf_url;
    el.jobResultPdfLink.classList.toggle("hidden", job.queue_state === "AWAITING_PAYMENT");

    const totalSec = Math.max(0, parseInt(job.estimated_seconds, 10) || 0);
    const colorLabel = formatColorLabel(job);
    const segmentsHtml =
      job.print_segments && job.print_segments.length > 1
        ? `
      <div class="segment-order-box">
        <span class="segment-order-title">Printerga yuborish tartibi (qog'ozlar ketma-ket chiqishi uchun):</span>
        <div class="segment-pills">
          ${job.print_segments
            .map(
              (s) =>
                `<span class="segment-pill ${s.color_mode === "color" ? "is-color" : ""}">${s.segment_index}. ${escapeHtml(s.page_range_text)}-bet (${s.color_mode === "color" ? "Rangli" : "Oq-qora"})</span>`
            )
            .join("")}
        </div>
      </div>`
        : "";

    el.jobResultBody.innerHTML = `
      <div class="result-notice" id="jobModalStatusNotice">
        <strong>${escapeHtml(job.status_message)}</strong>
      </div>
      <div id="jobModalLiveBanner">${buildJobLiveBannerMarkup(job)}</div>
      ${segmentsHtml}
      <div class="result-specs">
        <div class="spec-box">
          <span>Buyurtma ID</span>
          <strong>${escapeHtml(job.id)}</strong>
        </div>
        <div class="spec-box">
          <span>O'quvchi</span>
          <strong>${escapeHtml(job.student_name || "Ko'rsatilmagan")}</strong>
        </div>
        <div class="spec-box">
          <span>Qurilma</span>
          <strong>${escapeHtml(job.device_label || job.device_id || "Joriy brauzer")}</strong>
        </div>
        <div class="spec-box">
          <span>Printer</span>
          <strong>${escapeHtml(job.printer_name || job.printer_mode || "Standart")}</strong>
        </div>
        <div class="spec-box">
          <span>Tanlangan betlar</span>
          <strong>${escapeHtml(job.page_range_text)} (${job.selected_page_count} bet)</strong>
        </div>
        <div class="spec-box">
          <span>Sozlamalar</span>
          <strong>${job.copies} nusxa • ${escapeHtml(colorLabel)}${job.duplex === "duplex" ? " • 2 tomonlama" : ""}</strong>
        </div>
        <div class="spec-box">
          <span>Sarflanadigan qog'oz</span>
          <strong>${job.physical_sheets} varaq (${job.paper_size})</strong>
        </div>
        <div class="spec-box">
          <span>Taxminiy chiqish vaqti</span>
          <strong>${escapeHtml(formatDuration(totalSec))}</strong>
        </div>
        <div class="spec-box">
          <span>Hisoblangan narx</span>
          <strong>${formatMoney(job.estimated_cost)}</strong>
        </div>
      </div>
    `;
    attachQueueActionHandlers(el.jobResultBody);
    el.jobResultModal.classList.remove("hidden");
    if (job.queue_state === "AWAITING_PAYMENT") {
      startPaymentCountdown(job);
    }
  }

  function startPaymentCountdown(job) {
    stopCountdownTimer();
    const payCfg = (state.systemStatus && state.systemStatus.payment) || {};
    const windowSec = Math.max(30, parseInt(payCfg.window_seconds, 10) || 120);

    const tick = () => {
      if (!state.activeModalJob || state.activeModalJob.id !== job.id || state.activeModalJob.queue_state !== "AWAITING_PAYMENT") {
        stopCountdownTimer();
        return;
      }
      const remSec = job.payment_deadline_ts
        ? Math.max(0, Math.ceil(job.payment_deadline_ts - Date.now() / 1000))
        : 0;
      const textEl = document.getElementById("jobPaymentCountdownText");
      const fillEl = document.getElementById("jobPaymentCountdownFill");
      if (textEl) {
        const mins = String(Math.floor(remSec / 60)).padStart(2, "0");
        const secs = String(remSec % 60).padStart(2, "0");
        textEl.textContent = remSec > 0 ? `${mins}:${secs} qoldi` : "Vaqt tugadi!";
      }
      if (fillEl) {
        const pct = Math.max(0, Math.min(100, Math.round((remSec / windowSec) * 100)));
        fillEl.style.width = `${pct}%`;
      }
    };
    tick();
    state.countdownTimer = setInterval(tick, 1000);
  }

  function syncOpenJobModalWithLiveQueue() {
    if (!state.activeModalJob || el.jobResultModal.classList.contains("hidden") || !state.liveQueue) {
      return;
    }
    if (state.activeModalJob.queue_state === "AWAITING_PAYMENT") {
      return;
    }
    const targetId = state.activeModalJob.id;
    const candidates = [
      state.liveQueue.active_job,
      ...(state.liveQueue.waiting_jobs || []),
      ...(state.liveQueue.recent_jobs || []),
    ].filter(Boolean);
    const liveMatch = candidates.find((item) => item.id === targetId);
    if (!liveMatch) return;

    state.activeModalJob = { ...state.activeModalJob, ...liveMatch };
    const noticeEl = document.getElementById("jobModalStatusNotice");
    if (noticeEl) {
      noticeEl.innerHTML = `<strong>${escapeHtml(liveMatch.status_message)}</strong>`;
    }
    const liveBannerEl = document.getElementById("jobModalLiveBanner");
    if (liveBannerEl) {
      liveBannerEl.innerHTML = buildJobLiveBannerMarkup(state.activeModalJob);
      attachQueueActionHandlers(liveBannerEl);
    }
  }

  async function confirmJobPrintedAction(jobId) {
    try {
      const updated = await SmartPrintApi.confirmJobPrinted(jobId);
      if (state.activeModalJob && state.activeModalJob.id === jobId) {
        state.activeModalJob = updated;
      }
      showToast("Rahmat! Chop etish tasdiqlandi va navbat keyingi foydalanuvchiga o'tdi.", "success");
      await loadLiveQueue();
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function extendJobTimeAction(jobId) {
    try {
      const updated = await SmartPrintApi.extendJobTime(jobId, 15);
      if (state.activeModalJob && state.activeModalJob.id === jobId) {
        state.activeModalJob = updated;
      }
      showToast("Printer uchun qo'shimcha +15 soniya vaqt qo'shildi.", "info");
      await loadLiveQueue();
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function cancelJobAction(jobId) {
    try {
      const updated = await SmartPrintApi.cancelPrintJob(jobId);
      saveModalState("", jobId);
      if (state.activeModalJob && state.activeModalJob.id === jobId) {
        state.activeModalJob = updated;
        if (el.jobResultModal && !el.jobResultModal.classList.contains("hidden")) {
          showJobResultModal(updated);
          saveModalState("", jobId);
        }
      }
      showToast("Buyurtma navbatdan bekor qilindi.", "info");
      await Promise.all([loadLiveQueue(), refreshMyActiveJobs()]);
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  function attachQueueActionHandlers(root) {
    if (!root) return;
    root.querySelectorAll("[data-open-job-modal-id]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const jobId = btn.dataset.openJobModalId;
        if (!jobId) return;
        btn.disabled = true;
        try {
          const fresh = await SmartPrintApi.getPrintJob(jobId);
          showJobResultModal(fresh);
        } catch (err) {
          showToast(err.message, "error");
        } finally {
          btn.disabled = false;
        }
      });
    });
    root.querySelectorAll("[data-confirm-job-id]").forEach((btn) => {
      btn.addEventListener("click", () => confirmJobPrintedAction(btn.dataset.confirmJobId));
    });
    root.querySelectorAll("[data-extend-job-id]").forEach((btn) => {
      btn.addEventListener("click", () => extendJobTimeAction(btn.dataset.extendJobId));
    });
    root.querySelectorAll("[data-cancel-job-id]").forEach((btn) => {
      btn.addEventListener("click", () => cancelJobAction(btn.dataset.cancelJobId));
    });
    root.querySelectorAll("[data-copy-text]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const val = btn.dataset.copyText || "";
        try {
          await navigator.clipboard.writeText(val);
        } catch (_) {
          const inp = document.createElement("textarea");
          inp.value = val;
          document.body.appendChild(inp);
          inp.select();
          document.execCommand("copy");
          inp.remove();
        }
        showToast(`Nusxalandi: ${val}`, "success");
      });
    });
    root.querySelectorAll("[data-verify-payment-job-id]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const jobId = btn.dataset.verifyPaymentJobId;
        const fileInput = document.getElementById("jobReceiptFileInput");
        const errBox = document.getElementById("jobPaymentErrorBox");
        const file = fileInput && fileInput.files && fileInput.files[0];
        if (!file) {
          if (errBox) {
            errBox.textContent = "Iltimos, avval to'lov chekini (rasm yoki PDF) yuklang!";
            errBox.classList.remove("hidden");
          }
          showToast("Avval to'lov chekini yuklang!", "error");
          if (fileInput) fileInput.focus();
          return;
        }
        btn.disabled = true;
        const origLabel = btn.textContent;
        btn.textContent = "To'lov tekshirilmoqda...";
        if (errBox) errBox.classList.add("hidden");
        try {
          const updatedJob = await SmartPrintApi.verifyJobPayment(jobId, file);
          state.activeModalJob = updatedJob;
          showJobResultModal(updatedJob);
          await Promise.all([loadLiveQueue(), refreshMyActiveJobs()]);
          showToast(updatedJob.payment_note || "To'lov tasdiqlandi! Chop etish boshlandi.", "success");
        } catch (err) {
          if (errBox) {
            errBox.textContent = err.message;
            errBox.classList.remove("hidden");
          }
          showToast(err.message, "error");
        } finally {
          btn.disabled = false;
          btn.textContent = origLabel;
        }
      });
    });
    root.querySelectorAll("[data-renew-payment-job-id]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const jobId = btn.dataset.renewPaymentJobId;
        btn.disabled = true;
        try {
          const updatedJob = await SmartPrintApi.renewJobPayment(jobId);
          state.activeModalJob = updatedJob;
          showJobResultModal(updatedJob);
          await refreshMyActiveJobs();
          showToast("120 soniyalik to'lov taymeri yangilandi!", "info");
        } catch (err) {
          showToast(err.message, "error");
        } finally {
          btn.disabled = false;
        }
      });
    });
  }

  function renderLiveQueue() {
    const q = state.liveQueue;
    if (!q || !el.liveQueueCard) return;
    const myToken = SmartPrintApi.getClientToken();

    el.liveQueueCard.classList.remove("is-idle", "is-busy", "is-confirm");
    el.livePrinterStateBadge.classList.remove("is-idle", "is-busy", "is-confirm");

    if (q.printer_state === "IDLE") {
      el.liveQueueCard.classList.add("is-idle");
      el.livePrinterStateBadge.classList.add("is-idle");
      el.livePrinterStateText.textContent = "Printer BO'SH — Chop etishga tayyor";
      el.liveQueueMetaText.textContent =
        q.recent_jobs && q.recent_jobs.length
          ? `Oxirgi chiqarish yakunlangan • Navbat bo'sh`
          : "Navbatda hech kim yo'q";
    } else if (q.printer_state === "AWAITING_CONFIRMATION") {
      el.liveQueueCard.classList.add("is-confirm");
      el.livePrinterStateBadge.classList.add("is-confirm");
      el.livePrinterStateText.textContent = "Tasdiqlash kutilmoqda";
      el.liveQueueMetaText.textContent = `${q.active_job ? q.active_job.student_name : "Foydalanuvchi"} tasdiqlashi kutilmoqda • Navbat: ${q.waiting_count} ta`;
    } else {
      el.liveQueueCard.classList.add("is-busy");
      el.livePrinterStateBadge.classList.add("is-busy");
      el.livePrinterStateText.textContent = "Printer BAND — Chop etilmoqda";
      el.liveQueueMetaText.textContent = `${q.active_job ? q.active_job.physical_sheets : 0} varaq chiqmoqda • Navbat: ${q.waiting_count} ta`;
    }

    const hasDetails = q.printer_busy || q.waiting_count > 0 || (q.recent_jobs && q.recent_jobs.length > 0);
    el.toggleQueueDetailsBtn.classList.toggle("hidden", !hasDetails);

    if (q.active_job) {
      const act = q.active_job;
      const isMine = Boolean(act.is_mine);
      const totalSec = Math.max(1, parseInt(act.estimated_seconds, 10) || 5);
      const remSec = Math.max(0, parseInt(act.remaining_print_seconds, 10) || 0);
      const pct =
        act.queue_state === "AWAITING_CONFIRMATION"
          ? 100
          : Math.max(5, Math.min(100, Math.round(((totalSec - remSec) / totalSec) * 100)));
      const printerLabel = act.printer_name || q.default_printer_name || "Printer";

      el.liveActiveJobBox.innerHTML = `
        <div class="live-active-main">
          <div class="live-active-info">
            <div class="live-active-who">
              <strong>${escapeHtml(act.student_name)}</strong>
              <span class="mine-badge ${isMine ? "" : "is-other"}">${isMine ? "Sizning qurilmangiz" : "Boshqa foydalanuvchi"}</span>
              <span class="tag-pill">${escapeHtml(act.device_label || act.device_id || "Qurilma")}</span>
              <span class="tag-pill">${escapeHtml(printerLabel)}</span>
              <span class="tag-pill">${act.physical_sheets} varaq</span>
              <span class="tag-pill">${escapeHtml(formatColorLabel(act))}</span>
            </div>
            <div class="live-active-file">
              ${escapeHtml(act.original_filename)} • Betlar: ${escapeHtml(act.page_range_text)} (${act.copies} nusxa)
            </div>
          </div>
          <div class="live-active-timer">
            ${
              act.queue_state === "AWAITING_CONFIRMATION"
                ? `<strong>Chiqib bo'ldi — tasdiqlash kutilmoqda</strong><span>${act.confirm_remaining_seconds} soniyada avtomatik bo'shaydi</span>`
                : `<strong>${remSec > 0 ? `${escapeHtml(formatDuration(remSec))} qoldi` : "Yakunlanmoqda..."}</strong><span>Jami vaqt: ${escapeHtml(formatDuration(totalSec))}</span>`
            }
          </div>
        </div>
        <div class="live-progress-track">
          <div class="live-progress-fill" style="width: ${pct}%"></div>
        </div>
      `;
      el.liveActiveJobBox.classList.remove("hidden");

      el.liveConfirmPrompt.classList.remove("is-locked");
      if (isMine && act.queue_state === "AWAITING_CONFIRMATION") {
        el.liveConfirmPrompt.innerHTML = `
          <div class="live-confirm-text">
            <strong>Qog'ozlaringiz printerdan chiqib bo'ldimi? Rostdan ham chiqarib oldingizmi?</strong>
            <span>Tasdiqlashingiz bilan navbatdagi foydalanuvchi hujjati chop etila boshlaydi.</span>
          </div>
          <div class="live-confirm-actions">
            <button type="button" class="btn btn-print btn-sm" data-confirm-job-id="${escapeHtml(act.id)}">
              Ha, chiqarib bo'ldim (Navbatni bo'shatish)
            </button>
            <button type="button" class="btn btn-secondary btn-sm" data-extend-job-id="${escapeHtml(act.id)}">
              Hali chiqyapti (+15s)
            </button>
          </div>
        `;
        el.liveConfirmPrompt.classList.remove("hidden");
        attachQueueActionHandlers(el.liveConfirmPrompt);
      } else if (isMine && act.queue_state === "ACTIVE_PRINTING") {
        el.liveConfirmPrompt.innerHTML = `
          <div class="live-confirm-text">
            <strong>Sizning hujjatingiz hozir printerdan chiqmoqda (${act.physical_sheets} varaq).</strong>
            <span>Agar qog'ozlar taymerdan oldinroq chiqib bo'lsa, quyidagi tugmani bosing:</span>
          </div>
          <div class="live-confirm-actions">
            <button type="button" class="btn btn-primary btn-sm" data-confirm-job-id="${escapeHtml(act.id)}">
              Ha, chiqarib bo'ldim
            </button>
            <button type="button" class="btn btn-ghost btn-sm" data-extend-job-id="${escapeHtml(act.id)}">
              +15s qo'shish
            </button>
          </div>
        `;
        el.liveConfirmPrompt.classList.remove("hidden");
        attachQueueActionHandlers(el.liveConfirmPrompt);
      } else {
        el.liveConfirmPrompt.innerHTML = `
          <div class="live-confirm-text">
            <strong>Tasdiqlash faqat ushbu buyurtma egasiga (${escapeHtml(act.student_name)} • ${escapeHtml(act.device_label || act.device_id)}) ko'rinadi.</strong>
            <span>Boshqa qurilmalar uni tasdiqlay olmaydi — chop etish yakunlangach navbat sizga avtomatik o'tadi.</span>
          </div>
        `;
        el.liveConfirmPrompt.classList.add("is-locked");
        el.liveConfirmPrompt.classList.remove("hidden");
      }
    } else {
      el.liveActiveJobBox.classList.add("hidden");
      el.liveActiveJobBox.innerHTML = "";
      el.liveConfirmPrompt.classList.add("hidden");
      el.liveConfirmPrompt.classList.remove("is-locked");
      el.liveConfirmPrompt.innerHTML = "";
    }

    el.liveWaitingCountPill.textContent = String(q.waiting_count);
    if (q.waiting_jobs && q.waiting_jobs.length) {
      el.liveWaitingList.innerHTML = q.waiting_jobs
        .map((w) => {
          const isMine = Boolean(w.is_mine);
          const wPrinter = w.printer_name || q.default_printer_name || "Printer";
          return `
            <div class="live-queue-row ${isMine ? "is-mine" : ""}">
              <div class="live-row-left">
                <span class="queue-pos-badge">#${w.queue_position}</span>
                <div class="live-row-info">
                  <strong>${escapeHtml(w.student_name)} ${isMine ? `<span class="mine-badge">Siz</span>` : ""}</strong>
                  <span>${escapeHtml(w.original_filename)} • ${w.physical_sheets} varaq • ${escapeHtml(formatColorLabel(w))}</span>
                  <span>${escapeHtml(w.device_label || w.device_id)} • ${escapeHtml(wPrinter)}</span>
                </div>
              </div>
              <div class="live-row-right">
                <span class="wait-eta">~${escapeHtml(formatDuration(w.estimated_wait_seconds))}</span>
                ${
                  isMine
                    ? `<button type="button" class="btn btn-ghost btn-sm" data-cancel-job-id="${escapeHtml(w.id)}">Bekor qilish</button>`
                    : ""
                }
              </div>
            </div>
          `;
        })
        .join("");
      attachQueueActionHandlers(el.liveWaitingList);
    } else {
      el.liveWaitingList.innerHTML = `<div class="live-empty">Navbatda kutayotganlar yo'q</div>`;
    }

    if (q.recent_jobs && q.recent_jobs.length) {
      el.liveRecentList.innerHTML = q.recent_jobs
        .map(
          (r) => `
          <div class="live-queue-row">
            <div class="live-row-left">
              <div class="live-row-info">
                <strong>${escapeHtml(r.student_name)}</strong>
                <span>${escapeHtml(r.original_filename)} • ${r.physical_sheets} varaq</span>
                <span>${escapeHtml(r.device_label || r.device_id)} • ${escapeHtml(r.printer_name || q.default_printer_name || "Printer")}</span>
              </div>
            </div>
            <div class="live-row-right">
              <span class="status-tag status-tag--ok">Chiqarildi</span>
            </div>
          </div>
        `
        )
        .join("");
    } else {
      el.liveRecentList.innerHTML = `<div class="live-empty">Hali chiqarilgan hujjatlar yo'q</div>`;
    }

    const showColumns = q.waiting_count > 0 || state.showQueueDetails;
    el.liveQueueColumns.classList.toggle("hidden", !showColumns);
    renderMyPendingPaymentBanner();
    syncOpenJobModalWithLiveQueue();
  }

  function renderMyPendingPaymentBanner() {
    if (!el.myPendingPaymentBanner) return;
    const pendingList = (state.myActiveJobs || []).filter(
      (j) => j && j.queue_state === "AWAITING_PAYMENT"
    );
    if (!pendingList.length) {
      el.myPendingPaymentBanner.classList.add("hidden");
      el.myPendingPaymentBanner.innerHTML = "";
      return;
    }
    const job = pendingList[0];
    const remSec = job.payment_deadline_ts
      ? Math.max(0, Math.ceil(job.payment_deadline_ts - Date.now() / 1000))
      : Math.max(0, parseInt(job.payment_remaining_seconds, 10) || 0);
    const mins = String(Math.floor(remSec / 60)).padStart(2, "0");
    const secs = String(remSec % 60).padStart(2, "0");
    const timeLabel = remSec > 0 ? `${mins}:${secs} qoldi` : "Vaqt tugadi (yangilash mumkin)";

    el.myPendingPaymentBanner.innerHTML = `
      <div class="live-pending-payment-text">
        <strong>Tugallanmagan to'lov: ${escapeHtml(job.original_filename)} (${formatMoney(job.estimated_cost)})</strong>
        <span>Holati: ${escapeHtml(timeLabel)} — chek yuklab tasdiqlashingiz mumkin</span>
      </div>
      <div class="live-confirm-actions">
        <button type="button" class="btn btn-primary btn-sm" data-open-job-modal-id="${escapeHtml(job.id)}">
          To'lov oynasini ochish
        </button>
        <button type="button" class="btn btn-ghost btn-sm" data-cancel-job-id="${escapeHtml(job.id)}">
          Bekor qilish
        </button>
      </div>
    `;
    el.myPendingPaymentBanner.classList.remove("hidden");
    attachQueueActionHandlers(el.myPendingPaymentBanner);
  }

  async function refreshMyActiveJobs() {
    try {
      const jobs = await SmartPrintApi.getMyActiveJobs();
      state.myActiveJobs = Array.isArray(jobs) ? jobs : [];
      renderMyPendingPaymentBanner();
      return state.myActiveJobs;
    } catch (_) {
      return state.myActiveJobs || [];
    }
  }

  async function loadLiveQueue() {
    if (state.isPollingQueue) return;
    state.isPollingQueue = true;
    try {
      const hasPendingPayment = (state.myActiveJobs || []).some(
        (j) => j && j.queue_state === "AWAITING_PAYMENT"
      );
      if (hasPendingPayment) {
        await refreshMyActiveJobs();
      }
      state.liveQueue = await SmartPrintApi.getLiveQueue();
      renderLiveQueue();
    } catch (_) {
      // ignore transient network errors while polling
    } finally {
      state.isPollingQueue = false;
    }
  }

  // ---------------------------------------------------------------------------
  // Admin Login & Dashboard Logic
  // ---------------------------------------------------------------------------

  function openAdminLoginModal() {
    el.adminLoginError.classList.add("hidden");
    el.adminLoginError.textContent = "";
    el.adminLoginModal.classList.remove("hidden");
    el.adminUsernameInput.focus();
  }

  function closeAdminLoginModal() {
    el.adminLoginModal.classList.add("hidden");
  }

  async function openAdminSection() {
    if (!SmartPrintApi.getAdminToken()) {
      openAdminLoginModal();
      return;
    }
    try {
      await loadAdminDashboard();
      setActiveView("admin");
    } catch (err) {
      if (err.status === 401) {
        SmartPrintApi.setAdminToken("");
        setActiveView("student");
        openAdminLoginModal();
      } else {
        showToast(err.message, "error");
      }
    }
  }

  async function handleAdminLoginSubmit(e) {
    e.preventDefault();
    const username = el.adminUsernameInput.value.trim();
    const password = el.adminPasswordInput.value;

    el.adminLoginError.classList.add("hidden");
    el.adminLoginSubmitBtn.disabled = true;
    el.adminLoginSubmitBtn.textContent = "Tekshirilmoqda...";

    try {
      await SmartPrintApi.adminLogin(username, password);
      closeAdminLoginModal();
      el.adminPasswordInput.value = "";
      await loadAdminDashboard();
      setActiveView("admin");
      showToast("Admin paneliga xush kelibsiz!", "success");
    } catch (err) {
      el.adminLoginError.textContent = err.message;
      el.adminLoginError.classList.remove("hidden");
    } finally {
      el.adminLoginSubmitBtn.disabled = false;
      el.adminLoginSubmitBtn.textContent = "Tizimga kirish";
    }
  }

  async function loadAdminDashboard() {
    const data = await SmartPrintApi.getAdminDashboard();
    state.adminDashboard = data;

    // KPI Cards
    el.statTotalJobs.textContent = String(data.stats.total_jobs);
    el.statJobsToday.textContent = `Bugun: ${data.stats.jobs_today} ta`;
    el.statTotalPages.textContent = String(data.stats.total_selected_pages);
    el.statTotalSheets.textContent = String(data.stats.total_physical_sheets);
    el.statTotalRevenue.textContent = formatMoney(data.stats.total_revenue);

    // Settings inputs
    el.adminCurrentUsernameLabel.textContent = data.settings.admin_username;
    el.newAdminUsername.value = data.settings.admin_username;
    el.priceBwSimplexInput.value = data.settings.bw_simplex;
    el.priceBwDuplexInput.value = data.settings.bw_duplex;
    el.priceColorSimplexInput.value = data.settings.color_simplex;
    el.priceColorDuplexInput.value = data.settings.color_duplex;
    if (el.secondsBwInput) {
      el.secondsBwInput.value = data.settings.seconds_bw_per_sheet ?? 7;
    }
    if (el.secondsColorInput) {
      el.secondsColorInput.value = data.settings.seconds_color_per_sheet ?? 14;
    }
    el.adminPrinterModeSelect.value = data.settings.printer_mode;
    if (el.adminAgentKeyInput) {
      el.adminAgentKeyInput.value = data.settings.agent_api_key || "";
    }

    if (el.paymentEnabledInput) {
      el.paymentEnabledInput.checked = Boolean(data.settings.payment_enabled);
    }
    if (el.paymentCardNumberInput) {
      el.paymentCardNumberInput.value = data.settings.payment_card_number || "";
    }
    if (el.paymentCardHolderInput) {
      el.paymentCardHolderInput.value = data.settings.payment_card_holder || "";
    }
    if (el.telegramBotUsernameInput) {
      el.telegramBotUsernameInput.value = data.settings.telegram_bot_username || "@HUMOcardbot";
    }
    if (el.paymentWindowSecondsInput) {
      el.paymentWindowSecondsInput.value = data.settings.payment_window_seconds ?? 120;
    }

    renderAdminTelegramStatus(data.telegram || {});
    if (data.telegram && data.telegram.connected) {
      loadRecentHumoPayments({ silent: true });
    } else if (el.adminHumoPaymentsList) {
      el.adminHumoPaymentsList.innerHTML = `<div class="humo-feed-empty">Telegram hisob ulanganidan keyin oxirgi tushumlar ko'rinadi.</div>`;
    }

    renderPrinterInventory(
      data.printers || [],
      data.discovered_devices || [],
      data.scan_summary || null,
      data.settings || {}
    );

    renderAdminJobsList();
  }

  function _formatScanLayerLabel(layer) {
    const map = {
      windows_usb_pnp: "Windows USB PnP",
      windows_spooler: "Windows Spooler",
      cups_backends: "CUPS Backends",
      linux_cups: "Linux CUPS",
      linux_usb: "Linux USB Port",
      mdns_network: "Wi-Fi / mDNS",
      network_ip_probe: "IP Port Skaneri",
      pi_agent: "Raspberry Pi Agent",
      "pi:pi_cups": "Pi CUPS",
      "pi:cups_backends": "Pi Backends",
      "pi:linux_usb": "Pi USB",
      "pi:mdns_network": "Pi Wi-Fi / mDNS",
      "pi:network_ip_probe": "Pi IP Probe",
    };
    return map[layer] || layer;
  }

  function _renderPrinterBadgesHtml(p) {
    const pills = [];
    const connMap = {
      USB: "USB",
      NETWORK: "Tarmoq",
      LOCAL: "Lokal",
      VIRTUAL: "Virtual",
      UNCONFIGURED_USB: "Yangi USB",
      UNCONFIGURED_NETWORK: "Yangi Tarmoq",
    };
    const connLabel = connMap[p.connection_type] || p.connection_type || "Lokal";
    pills.push(`<span class="tag-pill">${escapeHtml(connLabel)}</span>`);
    if (p.supports_color === true) {
      pills.push(`<span class="tag-pill">Rangli</span>`);
    } else if (p.supports_color === false) {
      pills.push(`<span class="tag-pill">Oq-qora</span>`);
    }
    if (p.supports_duplex === true) {
      pills.push(`<span class="tag-pill">2-tomonlama</span>`);
    }
    if (p.hardware_present === true) {
      pills.push(`<span class="status-tag status-tag--ok">Kabel/aloqa faol</span>`);
    } else if (p.hardware_present === false) {
      pills.push(`<span class="status-tag status-tag--warn">Aloqa yo'q</span>`);
    }
    return pills.join("");
  }

  function renderPrinterInventory(printers, discoveredDevices, summary, settingsSnapshot = null) {
    const settings = settingsSnapshot || (state.adminDashboard && state.adminDashboard.settings) || {};
    const currentDefault = settingsSnapshot
      ? (settingsSnapshot.default_printer_name || "")
      : (el.adminDefaultPrinterSelect ? el.adminDefaultPrinterSelect.value : settings.default_printer_name || "");

    if (el.adminDefaultPrinterSelect) {
      el.adminDefaultPrinterSelect.innerHTML = `<option value="">Avtomatik (Standart printer)</option>`;
      printers.forEach((p) => {
        const opt = document.createElement("option");
        opt.value = p.name;
        const kindHint = p.is_virtual ? " [Virtual]" : p.ready_to_print ? " [Tayyor]" : " [Oflayn]";
        opt.textContent = `${p.name}${kindHint} — ${p.status_text}`;
        el.adminDefaultPrinterSelect.appendChild(opt);
      });
      el.adminDefaultPrinterSelect.value = currentDefault;
    }

    if (el.piAgentStatusBox) {
      const agentOnline = summary ? Boolean(summary.agent_online) : false;
      const lastSeen = (summary && summary.agent_last_seen) || settings.agent_last_seen || "";
      const hostName = (summary && summary.agent_hostname) || settings.agent_hostname || "raspberrypi";
      if (lastSeen && agentOnline) {
        el.piAgentStatusBox.innerHTML = `
          <span><strong>Raspberry Pi Agent:</strong> ${escapeHtml(hostName)}</span>
          <span class="status-tag status-tag--ok">Onlayn • ${escapeHtml(formatDateTime(lastSeen))}</span>
        `;
      } else if (lastSeen) {
        el.piAgentStatusBox.innerHTML = `
          <span><strong>Raspberry Pi Agent:</strong> ${escapeHtml(hostName)}</span>
          <span class="status-tag status-tag--warn">Uzilgan • Oxirgi aloqa: ${escapeHtml(formatDateTime(lastSeen))}</span>
        `;
      } else {
        el.piAgentStatusBox.innerHTML = `
          <span><strong>Raspberry Pi Agent:</strong> Hali ulanmagan</span>
          <span class="status-tag">REMOTE_AGENT kutilmoqda</span>
        `;
      }
    }

    if (el.printerScanSummaryBox) {
      if (summary) {
        const hasReady = (summary.ready_physical_count || 0) > 0;
        const hasNew = (summary.unconfigured_hardware_count || 0) > 0;
        const stateCls = hasReady ? "is-ok" : hasNew ? "is-warn" : "is-empty";
        const layersHtml = (summary.layers_checked || [])
          .map((l) => `<span class="tag-pill">${escapeHtml(_formatScanLayerLabel(l))}</span>`)
          .join("");
        el.printerScanSummaryBox.className = `scan-summary-box ${stateCls}`;
        el.printerScanSummaryBox.innerHTML = `
          <div class="scan-summary-head">
            <strong>${escapeHtml(summary.recommendation || "Skanerlash natijasi")}</strong>
            <span class="scan-counts-inline">Tayyor: ${summary.ready_physical_count || 0} • Yangi: ${summary.unconfigured_hardware_count || 0} • Oflayn: ${summary.offline_physical_count || 0}</span>
          </div>
          ${summary.target_ip_message ? `<div class="scan-ip-note">${escapeHtml(summary.target_ip_message)}</div>` : ""}
          ${layersHtml ? `<div class="scan-layers-strip">${layersHtml}</div>` : ""}
        `;
        el.printerScanSummaryBox.classList.remove("hidden");
      } else {
        el.printerScanSummaryBox.classList.add("hidden");
      }
    }

    if (!el.adminPrintersList) return;

    const readyPhys = printers.filter((p) => !p.is_virtual && p.ready_to_print);
    const offlinePhys = printers.filter((p) => !p.is_virtual && !p.ready_to_print);
    const virtList = printers.filter((p) => p.is_virtual);
    const activeDefault = settings.default_printer_name || "";

    const renderCard = (p, kind) => {
      const isDef = activeDefault ? p.name === activeDefault : p.is_default;
      const metaParts = [];
      if (p.port_or_uri) metaParts.push(p.port_or_uri);
      if (p.host_label) metaParts.push(p.host_label);
      if (p.jobs_in_queue > 0) metaParts.push(`Navbatda: ${p.jobs_in_queue}`);

      let actionHtml = "";
      if (kind === "unconfigured") {
        const scope = p.source === "pi_agent" ? "agent" : "local";
        actionHtml = p.can_auto_configure
          ? `<button type="button" class="btn btn-primary btn-xs auto-config-printer-btn" data-uri="${escapeHtml(p.port_or_uri || "")}" data-queue="${escapeHtml(p.suggested_queue_name || p.name)}" data-scope="${scope}">CUPS ga avto-ulash</button>`
          : `<span class="status-tag status-tag--warn">Qo'lda sozlash kerak</span>`;
      } else if (kind !== "virtual") {
        actionHtml = isDef
          ? `<span class="status-tag status-tag--ok">Asosiy printer</span>`
          : `<button type="button" class="btn btn-outline btn-xs set-default-printer-btn" data-printer-name="${escapeHtml(p.name)}">Asosiy qilish</button>`;
      }

      const statusBadgeCls =
        kind === "ready" ? "status-tag--ok" : kind === "unconfigured" || kind === "offline" ? "status-tag--warn" : "";

      return `
        <div class="printer-hw-card printer-hw-card--${kind}">
          <div class="printer-hw-main">
            <div class="printer-hw-title">
              <strong>${escapeHtml(p.name)}</strong>
              <span class="status-tag ${statusBadgeCls}">${escapeHtml(p.status_text || "")}</span>
            </div>
            <div class="printer-hw-badges">${_renderPrinterBadgesHtml(p)}</div>
            ${metaParts.length ? `<div class="printer-hw-meta">${escapeHtml(metaParts.join(" • "))}</div>` : ""}
          </div>
          ${actionHtml ? `<div class="printer-hw-actions">${actionHtml}</div>` : ""}
        </div>
      `;
    };

    const blocks = [];
    if (readyPhys.length) {
      blocks.push(`<div class="printer-scan-group-title">Tayyor jismoniy printerlar (${readyPhys.length})</div>`);
      blocks.push(readyPhys.map((p) => renderCard(p, "ready")).join(""));
    }
    if (discoveredDevices.length) {
      blocks.push(`<div class="printer-scan-group-title">Yangi aniqlangan USB / Tarmoq printerlar (${discoveredDevices.length})</div>`);
      blocks.push(discoveredDevices.map((p) => renderCard(p, "unconfigured")).join(""));
    }
    if (offlinePhys.length) {
      blocks.push(`<div class="printer-scan-group-title">Oflayn yoki kabeli uzilgan printerlar (${offlinePhys.length})</div>`);
      blocks.push(offlinePhys.map((p) => renderCard(p, "offline")).join(""));
    }
    if (!readyPhys.length && !discoveredDevices.length && !offlinePhys.length) {
      blocks.push(`<div class="printer-mini-item">Jismoniy printer topilmadi. Printer kabelini ulab «Printerlarni skanerlash» tugmasini bosing.</div>`);
    }
    if (virtList.length) {
      blocks.push(`
        <details class="virtual-printers-details">
          <summary>Virtual dasturiy printerlar (${virtList.length})</summary>
          <div class="virtual-printers-list">
            ${virtList.map((p) => renderCard(p, "virtual")).join("")}
          </div>
        </details>
      `);
    }

    el.adminPrintersList.innerHTML = blocks.join("");

    el.adminPrintersList.querySelectorAll(".set-default-printer-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const chosen = btn.getAttribute("data-printer-name") || "";
        if (!chosen) return;
        if (el.adminDefaultPrinterSelect) {
          el.adminDefaultPrinterSelect.value = chosen;
        }
        await saveAdminSettingsFromUI(`Asosiy printer tanlandi: ${chosen}`);
      });
    });

    el.adminPrintersList.querySelectorAll(".auto-config-printer-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const deviceUri = btn.getAttribute("data-uri") || "";
        const queueName = btn.getAttribute("data-queue") || "";
        const hostScope = btn.getAttribute("data-scope") || "local";
        if (!deviceUri) return;
        btn.disabled = true;
        btn.textContent = "Ulanmoqda...";
        try {
          const res = await SmartPrintApi.autoConfigurePrinter({
            deviceUri,
            queueName,
            hostScope,
            setDefault: true,
          });
          showToast(res.message || "Printer ulandi!", res.ok ? "success" : "error");
          if (res.scan) {
            renderPrinterInventory(
              res.scan.printers || [],
              res.scan.discovered_devices || [],
              res.scan.summary || null
            );
          }
          if (res.ok && res.pending) {
            btn.textContent = "Pi ulamoqda...";
            if (state.pendingScanRefreshTimer) {
              clearTimeout(state.pendingScanRefreshTimer);
            }
            state.pendingScanRefreshTimer = setTimeout(() => {
              state.pendingScanRefreshTimer = null;
              handleScanPrinters();
            }, 3000);
          } else {
            await Promise.all([loadSystemStatus(), loadAdminDashboard()]);
          }
        } catch (err) {
          showToast(err.message, "error");
          btn.disabled = false;
          btn.textContent = "CUPS ga avto-ulash";
        }
      });
    });
  }

  async function handleScanPrinters() {
    const netIp = el.scanNetworkIpInput ? el.scanNetworkIpInput.value.trim() : "";
    if (el.scanPrintersBtn) {
      el.scanPrintersBtn.disabled = true;
      el.scanPrintersBtn.textContent = "Skanerlanmoqda...";
    }
    if (el.scanIpBtn) el.scanIpBtn.disabled = true;
    try {
      const scanRes = await SmartPrintApi.scanPrinters({
        networkIp: netIp,
        includeNetworkScan: true,
        waitAgentSeconds: 3.5,
      });
      renderPrinterInventory(
        scanRes.printers || [],
        scanRes.discovered_devices || [],
        scanRes.summary || null
      );
      const sum = scanRes.summary || {};
      const toastKind = (sum.ready_physical_count || 0) > 0 || (sum.unconfigured_hardware_count || 0) > 0 ? "success" : "info";
      showToast(sum.recommendation || "Printerlarni skanerlash yakunlandi.", toastKind);
      await loadSystemStatus();
    } catch (err) {
      showToast(err.message, "error");
    } finally {
      if (el.scanPrintersBtn) {
        el.scanPrintersBtn.disabled = false;
        el.scanPrintersBtn.textContent = "Printerlarni skanerlash";
      }
      if (el.scanIpBtn) el.scanIpBtn.disabled = false;
    }
  }

  function getStatusBadgeInfo(status) {
    switch (status) {
      case "AWAITING_PAYMENT":
        return { label: "To'lov kutilmoqda", cls: "status-tag--warn" };
      case "COMPLETED":
        return { label: "Chop etilgan", cls: "status-tag--ok" };
      case "SENT_TO_PRINTER":
        return { label: "Printerga yuborildi", cls: "status-tag--ok" };
      case "PRINTING_ON_PI":
        return { label: "Raspberry Pi chop etmoqda", cls: "status-tag--ok" };
      case "AWAITING_CONFIRMATION":
        return { label: "Tasdiqlash kutilmoqda", cls: "" };
      case "WAITING_IN_QUEUE":
        return { label: "Kutish navbatida", cls: "" };
      case "QUEUED_FOR_AGENT":
        return { label: "Pi navbatida", cls: "" };
      case "ERROR":
        return { label: "Xatolik", cls: "status-tag--err" };
      case "CANCELLED":
        return { label: "Bekor qilingan", cls: "" };
      default:
        return { label: "Navbatda / Test", cls: "" };
    }
  }

  function renderAdminJobsList() {
    if (!state.adminDashboard) return;
    const query = el.adminJobSearchInput.value.trim().toLowerCase();
    const filterStatus = el.adminJobStatusFilter.value;

    const filtered = state.adminDashboard.jobs.filter((job) => {
      const matchStatus = filterStatus === "ALL" || job.status === filterStatus;
      if (!matchStatus) return false;
      if (!query) return true;
      const haystack = `${job.id} ${job.original_filename} ${job.student_name} ${job.page_range_text}`.toLowerCase();
      return haystack.includes(query);
    });

    if (!filtered.length) {
      el.adminJobsList.innerHTML = `<div class="queue-empty">Mos keladigan buyurtmalar topilmadi.</div>`;
      return;
    }

    el.adminJobsList.innerHTML = filtered
      .map((job) => {
        const badge = getStatusBadgeInfo(job.status);
        const jobColorLabel =
          job.color_mode === "mixed"
            ? `Aralash (${job.bw_sheets} oq-qora / ${job.color_sheets} rangli)`
            : job.color_mode === "color"
              ? "Rangli"
              : "Oq-qora";
        const payTag =
          job.payment_status === "PAID"
            ? `<span class="tag-pill pay-pill is-paid">To'langan (${escapeHtml(job.payment_tx_id || "tasdiq")})</span>`
            : job.payment_status === "UNVERIFIED"
              ? `<span class="tag-pill pay-pill is-unverified">To'lov topilmadi</span>`
              : job.payment_status === "AWAITING_PAYMENT"
                ? `<span class="tag-pill pay-pill is-pending">To'lov kutilmoqda</span>`
                : job.payment_status === "EXPIRED"
                  ? `<span class="tag-pill pay-pill is-unverified">Vaqt tugagan</span>`
                  : "";
        const duplexTxt = job.duplex === "duplex" ? " • 2 tomonlama" : "";
        const deviceTxt = job.device_label || job.device_id || "Noma'lum";
        return `
        <div class="queue-item">
          <div class="queue-item-main">
            <div class="queue-item-title">
              <span class="queue-item-file" title="${escapeHtml(job.original_filename)}">${escapeHtml(job.original_filename)}</span>
              <span class="version-pill">#${escapeHtml(job.id)}</span>
            </div>
            <div class="queue-item-line">
              <span>O'quvchi: ${escapeHtml(job.student_name || "Ko'rsatilmagan")}</span>
              <span>${escapeHtml(deviceTxt)} (${escapeHtml(job.client_ip || "local")})</span>
              <span>${escapeHtml(formatDateTime(job.created_at))}</span>
            </div>
            <div class="queue-item-line queue-item-line--strong">
              <span>Betlar: ${escapeHtml(job.page_range_text)} (${job.selected_page_count} bet)</span>
              <span>${job.copies} nusxa • ${escapeHtml(jobColorLabel)}${duplexTxt}</span>
              <span>${job.physical_sheets} varaq</span>
              <span>${escapeHtml(formatDuration(job.estimated_seconds))}</span>
              <span class="queue-item-cost">${formatMoney(job.estimated_cost)}</span>
            </div>
            <div class="queue-item-line">
              <span>Printer: ${escapeHtml(job.printer_name || job.printer_mode)}</span>
            </div>
            ${job.payment_note ? `<div class="payment-note-line">${escapeHtml(job.payment_note)}</div>` : ""}
          </div>
          <div class="queue-item-side">
            <div class="queue-item-badges">
              <span class="status-tag ${badge.cls}">${badge.label}</span>
              ${job.status === "AWAITING_PAYMENT" && job.payment_status === "AWAITING_PAYMENT" ? "" : payTag}
            </div>
            <div class="queue-item-actions">
              ${
                job.queue_state === "AWAITING_PAYMENT"
                  ? `<button type="button" class="btn btn-success btn-sm admin-approve-payment-btn" data-job-id="${escapeHtml(job.id)}">To'lovni tasdiqlash</button>`
                  : ""
              }
              ${
                job.status !== "COMPLETED"
                  ? `<button type="button" class="btn btn-secondary btn-sm admin-complete-btn" data-job-id="${escapeHtml(job.id)}">Chop etildi</button>`
                  : ""
              }
              <a href="${job.pdf_url}" target="_blank" rel="noopener" class="btn btn-outline btn-sm">Tayyor PDF</a>
              <a href="${job.original_pdf_url}" target="_blank" rel="noopener" class="btn btn-outline btn-sm">Asl PDF</a>
              ${
                job.has_receipt
                  ? `<a href="${escapeHtml(SmartPrintApi.getReceiptUrl(job.id))}" target="_blank" rel="noopener" class="btn btn-outline btn-sm">Chek</a>`
                  : ""
              }
              <button type="button" class="btn btn-ghost btn-sm admin-delete-btn" data-job-id="${escapeHtml(job.id)}">O'chirish</button>
            </div>
          </div>
        </div>
      `;
      })
      .join("");

    el.adminJobsList.querySelectorAll(".admin-approve-payment-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        btn.disabled = true;
        try {
          await SmartPrintApi.updateAdminJobStatus(btn.dataset.jobId, "APPROVE_PAYMENT");
          showToast("To'lov admin tomonidan tasdiqlandi va chop etishga uzatildi!", "success");
          await Promise.all([loadAdminDashboard(), loadLiveQueue()]);
        } catch (err) {
          showToast(err.message, "error");
        } finally {
          btn.disabled = false;
        }
      });
    });

    el.adminJobsList.querySelectorAll(".admin-complete-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          await SmartPrintApi.updateAdminJobStatus(btn.dataset.jobId, "COMPLETED");
          showToast("Buyurtma 'Chop etilgan' deb belgilandi.", "success");
          await loadAdminDashboard();
        } catch (err) {
          showToast(err.message, "error");
        }
      });
    });

    el.adminJobsList.querySelectorAll(".admin-delete-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          await SmartPrintApi.deleteAdminPrintJob(btn.dataset.jobId);
          showToast("Buyurtma tarixdan o'chirildi.", "info");
          await loadAdminDashboard();
        } catch (err) {
          showToast(err.message, "error");
        }
      });
    });
  }

  function renderAdminTelegramStatus(tg) {
    if (!el.adminTelegramStatusBadge) return;
    const connected = Boolean(tg && tg.connected);
    el.adminTelegramStatusBadge.className = `status-pill ${connected ? "status-pill--live" : "status-pill--dryrun"}`;
    el.adminTelegramStatusBadge.textContent = connected
      ? `Telegram ulangan: ${tg.account_name || tg.account_phone || "Faol"}`
      : "Telegram ulanmagan";
    if (el.adminTelegramAccountDetails) {
      if (connected) {
        const handle = tg.account_username ? `@${tg.account_username}` : "";
        el.adminTelegramAccountDetails.innerHTML = `<strong>${escapeHtml(tg.account_name || "Telegram")}</strong> ${escapeHtml(handle)} (${escapeHtml(tg.account_phone || "")}) • Bot: <code>${escapeHtml(tg.bot_username || "@HUMOcardbot")}</code>`;
      } else {
        el.adminTelegramAccountDetails.textContent =
          "Telegram akkaunt ulansa, sayt botdagi tushumlarni real vaqtda avtomatik o'qiydi.";
      }
    }
    if (el.telegramDisconnectBtn) {
      el.telegramDisconnectBtn.classList.toggle("hidden", !connected);
    }
  }

  function showTelegramAuthMsg(msg, isError = false) {
    if (!el.telegramAuthMessage) return;
    if (!msg) {
      el.telegramAuthMessage.classList.add("hidden");
      el.telegramAuthMessage.textContent = "";
      return;
    }
    el.telegramAuthMessage.textContent = msg;
    el.telegramAuthMessage.className = `tg-auth-msg ${isError ? "is-error" : "is-success"}`;
  }

  async function handleTelegramSendCode() {
    const phone = el.telegramPhoneInput ? el.telegramPhoneInput.value.trim() : "";
    const bot = el.telegramBotUsernameInput ? el.telegramBotUsernameInput.value.trim() : "@HUMOcardbot";
    if (!phone) {
      showTelegramAuthMsg("Telefon raqamini kiriting (+998...).", true);
      return;
    }
    el.telegramSendCodeBtn.disabled = true;
    el.telegramSendCodeBtn.textContent = "Yuborilmoqda...";
    showTelegramAuthMsg("");
    try {
      const res = await SmartPrintApi.sendTelegramCode(phone, bot || "@HUMOcardbot");
      state.telegramPendingAuthToken = res.auth_token;
      if (el.telegramCodeGroup) el.telegramCodeGroup.classList.remove("hidden");
      showTelegramAuthMsg(res.message || "Tasdiqlash kodi yuborildi!", false);
      showToast(res.message || "Telegram kod yuborildi!", "success");
    } catch (err) {
      showTelegramAuthMsg(err.message, true);
      showToast(err.message, "error");
    } finally {
      el.telegramSendCodeBtn.disabled = false;
      el.telegramSendCodeBtn.textContent = "Kod yuborish";
    }
  }

  async function handleTelegramVerifyCode() {
    if (!state.telegramPendingAuthToken) {
      showTelegramAuthMsg("Avval 'Kod yuborish' tugmasini bosing.", true);
      return;
    }
    const code = el.telegramCodeInput ? el.telegramCodeInput.value.trim() : "";
    const password = el.telegramPasswordInput ? el.telegramPasswordInput.value : "";
    el.telegramVerifyCodeBtn.disabled = true;
    el.telegramVerifyCodeBtn.textContent = "Tekshirilmoqda...";
    try {
      const res = await SmartPrintApi.verifyTelegramCode(state.telegramPendingAuthToken, code, password);
      if (res.needs_password) {
        showTelegramAuthMsg(res.message, false);
        showToast(res.message, "info");
        if (el.telegramPasswordInput) el.telegramPasswordInput.focus();
        return;
      }
      state.telegramPendingAuthToken = "";
      if (el.telegramCodeGroup) el.telegramCodeGroup.classList.add("hidden");
      if (el.telegramCodeInput) el.telegramCodeInput.value = "";
      if (el.telegramPasswordInput) el.telegramPasswordInput.value = "";
      showTelegramAuthMsg(res.message || "Telegram sessiyasi saqlandi!", false);
      showToast(res.message || "Telegram ulandi!", "success");
      await Promise.all([loadSystemStatus(), loadAdminDashboard()]);
    } catch (err) {
      showTelegramAuthMsg(err.message, true);
      showToast(err.message, "error");
    } finally {
      el.telegramVerifyCodeBtn.disabled = false;
      el.telegramVerifyCodeBtn.textContent = "Tasdiqlash va sessiyani saqlash";
    }
  }

  async function handleTelegramDisconnect() {
    try {
      await SmartPrintApi.disconnectTelegram();
      showTelegramAuthMsg("Telegram hisob uzildi.", false);
      showToast("Telegram hisobi uzildi.", "info");
      await Promise.all([loadSystemStatus(), loadAdminDashboard()]);
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function loadRecentHumoPayments({ silent = false } = {}) {
    if (!el.adminHumoPaymentsList) return;
    if (!silent) {
      el.adminHumoPaymentsList.innerHTML = `<div class="humo-feed-empty">Botdan oxirgi tushumlar yuklanmoqda...</div>`;
    }
    try {
      const data = await SmartPrintApi.getRecentHumoPayments();
      if (!data.connected) {
        el.adminHumoPaymentsList.innerHTML = `<div class="humo-feed-empty">${escapeHtml(data.error || "Telegram ulanmagan.")}</div>`;
        return;
      }
      const items = data.transactions || [];
      if (!items.length) {
        el.adminHumoPaymentsList.innerHTML = `<div class="humo-feed-empty">${escapeHtml(data.bot_username || "@HUMOcardbot")} da tushum xabarlari topilmadi.</div>`;
        return;
      }
      el.adminHumoPaymentsList.innerHTML = items
        .slice(0, 12)
        .map(
          (tx) => `
          <div class="humo-feed-item">
            <div>
              <strong>+ ${formatMoney(tx.amount_uzs)}</strong>
              <span class="humo-feed-meta">${escapeHtml(tx.card_mask || "HUMO")} • ${escapeHtml(tx.humo_time || formatDateTime(tx.msg_date_iso))} • ${escapeHtml(tx.source || "")}</span>
            </div>
            <span class="status-tag ${tx.used ? "" : "status-tag--ok"}">${tx.used ? "Ishlatilgan" : "Yangi"}</span>
          </div>
        `
        )
        .join("");
    } catch (err) {
      if (!silent) {
        el.adminHumoPaymentsList.innerHTML = `<div class="humo-feed-empty">${escapeHtml(err.message)}</div>`;
      }
    }
  }

  async function saveAdminSettingsFromUI(successMessage) {
    const bwSimplex = Math.max(0, parseInt(el.priceBwSimplexInput.value, 10) || 0);
    const bwDuplex = Math.max(0, parseInt(el.priceBwDuplexInput.value, 10) || 0);
    const colorSimplex = Math.max(0, parseInt(el.priceColorSimplexInput.value, 10) || 0);
    const colorDuplex = Math.max(0, parseInt(el.priceColorDuplexInput.value, 10) || 0);
    const secondsBw = Math.max(1, parseInt(el.secondsBwInput ? el.secondsBwInput.value : "7", 10) || 7);
    const secondsColor = Math.max(1, parseInt(el.secondsColorInput ? el.secondsColorInput.value : "14", 10) || 14);
    const payWindow = Math.max(30, parseInt(el.paymentWindowSecondsInput ? el.paymentWindowSecondsInput.value : "120", 10) || 120);

    try {
      await SmartPrintApi.updateAdminSettings({
        bw_simplex: bwSimplex,
        bw_duplex: bwDuplex,
        color_simplex: colorSimplex,
        color_duplex: colorDuplex,
        seconds_bw_per_sheet: secondsBw,
        seconds_color_per_sheet: secondsColor,
        printer_mode: el.adminPrinterModeSelect.value,
        default_printer_name: el.adminDefaultPrinterSelect.value,
        agent_api_key: el.adminAgentKeyInput ? el.adminAgentKeyInput.value.trim() : "",
        payment_enabled: el.paymentEnabledInput ? Boolean(el.paymentEnabledInput.checked) : true,
        payment_card_number: el.paymentCardNumberInput ? el.paymentCardNumberInput.value.trim() : "",
        payment_card_holder: el.paymentCardHolderInput ? el.paymentCardHolderInput.value.trim() : "",
        payment_window_seconds: payWindow,
        telegram_bot_username: el.telegramBotUsernameInput ? el.telegramBotUsernameInput.value.trim() : "@HUMOcardbot",
      });
      await Promise.all([loadSystemStatus(), loadAdminDashboard()]);
      showToast(successMessage, "success");
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function handleUpdateCredentials() {
    const newUsername = el.newAdminUsername.value.trim();
    const currentPassword = el.currentAdminPassword.value;
    const newPassword = el.newAdminPassword.value;

    if (!newUsername || !currentPassword || newPassword.length < 4) {
      showToast("Login, joriy parol va kamida 4 belgili yangi parol kiriting.", "error");
      return;
    }

    try {
      await SmartPrintApi.updateAdminCredentials({
        new_username: newUsername,
        current_password: currentPassword,
        new_password: newPassword,
      });
      el.currentAdminPassword.value = "";
      el.newAdminPassword.value = "";
      await loadAdminDashboard();
      showToast("Admin logini va paroli muvaffaqiyatli yangilandi!", "success");
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  function handleAdminLogout() {
    SmartPrintApi.setAdminToken("");
    state.adminDashboard = null;
    setActiveView("student");
    showToast("Admin panelidan chiqdingiz.", "info");
  }

  function bindEvents() {
    // Header Navigation
    el.openAdminBtn.addEventListener("click", openAdminSection);
    el.backToStudioBtn.addEventListener("click", () => setActiveView("student"));
    el.adminLogoutBtn.addEventListener("click", handleAdminLogout);

    // Admin Login Modal
    el.adminLoginCloseBtn.addEventListener("click", closeAdminLoginModal);
    el.adminLoginModal.addEventListener("click", (e) => {
      if (e.target === el.adminLoginModal) closeAdminLoginModal();
    });
    el.toggleLoginPwdBtn.addEventListener("click", () => {
      const isPwd = el.adminPasswordInput.type === "password";
      el.adminPasswordInput.type = isPwd ? "text" : "password";
      el.toggleLoginPwdBtn.textContent = isPwd ? "Yashirish" : "Ko'rish";
    });
    el.adminLoginForm.addEventListener("submit", handleAdminLoginSubmit);

    // Admin Dashboard Actions
    el.adminRefreshBtn.addEventListener("click", loadAdminDashboard);
    el.savePricingBtn.addEventListener("click", () =>
      saveAdminSettingsFromUI("Bitta list narxlari saqlandi va saytda yangilandi!")
    );
    el.savePrinterSettingsBtn.addEventListener("click", () =>
      saveAdminSettingsFromUI("Printer va tizim rejimi saqlandi!")
    );
    if (el.scanPrintersBtn) {
      el.scanPrintersBtn.addEventListener("click", handleScanPrinters);
    }
    if (el.scanIpBtn) {
      el.scanIpBtn.addEventListener("click", handleScanPrinters);
    }
    if (el.scanNetworkIpInput) {
      el.scanNetworkIpInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          handleScanPrinters();
        }
      });
    }
    if (el.savePaymentSettingsBtn) {
      el.savePaymentSettingsBtn.addEventListener("click", () =>
        saveAdminSettingsFromUI("To'lov kartasi va Telegram bot sozlamalari saqlandi!")
      );
    }
    if (el.telegramSendCodeBtn) {
      el.telegramSendCodeBtn.addEventListener("click", handleTelegramSendCode);
    }
    if (el.telegramVerifyCodeBtn) {
      el.telegramVerifyCodeBtn.addEventListener("click", handleTelegramVerifyCode);
    }
    if (el.telegramDisconnectBtn) {
      el.telegramDisconnectBtn.addEventListener("click", handleTelegramDisconnect);
    }
    if (el.refreshHumoPaymentsBtn) {
      el.refreshHumoPaymentsBtn.addEventListener("click", () => loadRecentHumoPayments({ silent: false }));
    }
    el.saveCredentialsBtn.addEventListener("click", handleUpdateCredentials);
    if (el.downloadDbBackupBtn) {
      el.downloadDbBackupBtn.addEventListener("click", async () => {
        el.downloadDbBackupBtn.disabled = true;
        try {
          const result = await SmartPrintApi.downloadDatabaseBackup();
          showToast(`Zaxira nusxa yuklandi: ${result.filename}`, "success");
        } catch (err) {
          showToast(err.message, "error");
        } finally {
          el.downloadDbBackupBtn.disabled = false;
        }
      });
    }
    el.adminJobSearchInput.addEventListener("input", renderAdminJobsList);
    el.adminJobStatusFilter.addEventListener("change", renderAdminJobsList);
    el.adminClearJobsBtn.addEventListener("click", async () => {
      try {
        await SmartPrintApi.clearAdminPrintJobs();
        showToast("Barcha buyurtmalar tarixi tozalandi.", "info");
        await loadAdminDashboard();
      } catch (err) {
        showToast(err.message, "error");
      }
    });

    // Upload & Drag/Drop
    el.browseFileBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      el.fileInput.click();
    });
    el.dropZone.addEventListener("click", (e) => {
      if (e.target.closest("button")) return;
      el.fileInput.click();
    });
    el.dropZone.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        el.fileInput.click();
      }
    });
    el.fileInput.addEventListener("change", () => {
      if (el.fileInput.files && el.fileInput.files[0]) {
        handleFileUpload(el.fileInput.files[0]);
        el.fileInput.value = "";
      }
    });

    ["dragenter", "dragover"].forEach((evtName) => {
      el.dropZone.addEventListener(evtName, (e) => {
        e.preventDefault();
        el.dropZone.classList.add("is-dragover");
      });
    });
    ["dragleave", "drop"].forEach((evtName) => {
      el.dropZone.addEventListener(evtName, (e) => {
        e.preventDefault();
        el.dropZone.classList.remove("is-dragover");
      });
    });
    el.dropZone.addEventListener("drop", (e) => {
      const files = e.dataTransfer && e.dataTransfer.files;
      if (files && files[0]) handleFileUpload(files[0]);
    });

    el.loadSampleBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      handleLoadSample();
    });

    el.changeDocumentBtn.addEventListener("click", () => {
      state.currentDoc = null;
      clearStudioDraft();
      el.studioWorkspace.classList.add("hidden");
      el.uploadView.classList.remove("hidden");
    });

    // Quick selection buttons
    el.btnSelectAll.addEventListener("click", () => {
      if (!state.currentDoc) return;
      state.selectedPages = new Set(
        Array.from({ length: state.currentDoc.page_count }, (_, i) => i + 1)
      );
      syncSelectionUI({ syncTextInput: true });
    });

    if (el.btnSelectOdd) {
      el.btnSelectOdd.addEventListener("click", () => {
        if (!state.currentDoc) return;
        state.selectedPages = new Set(
          Array.from({ length: state.currentDoc.page_count }, (_, i) => i + 1).filter(
            (p) => p % 2 === 1
          )
        );
        syncSelectionUI({ syncTextInput: true });
      });
    }

    if (el.btnSelectEven) {
      el.btnSelectEven.addEventListener("click", () => {
        if (!state.currentDoc) return;
        state.selectedPages = new Set(
          Array.from({ length: state.currentDoc.page_count }, (_, i) => i + 1).filter(
            (p) => p % 2 === 0
          )
        );
        syncSelectionUI({ syncTextInput: true });
      });
    }

    el.btnClearSelection.addEventListener("click", () => {
      state.selectedPages.clear();
      syncSelectionUI({ syncTextInput: true });
    });

    // Grid thumbnail size switcher (Kichik / O'rta / Katta)
    document.querySelectorAll(".grid-size-btn[data-grid-size]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const size = btn.getAttribute("data-grid-size") || "md";
        el.pagesGrid.classList.remove("size-sm", "size-md", "size-lg");
        el.pagesGrid.classList.add(`size-${size}`);
        document.querySelectorAll(".grid-size-btn[data-grid-size]").forEach((b) => {
          b.classList.toggle("is-active", b === btn);
        });
      });
    });

    // Range text input live sync
    el.pageRangeInput.addEventListener("input", () => {
      if (!state.currentDoc) return;
      try {
        const parsed = PageSelector.parseRange(
          el.pageRangeInput.value,
          state.currentDoc.page_count
        );
        state.selectedPages = new Set(parsed);
        el.pageRangeInput.classList.remove("is-invalid");
        el.rangeErrorMsg.classList.add("hidden");
        syncSelectionUI({ syncTextInput: false });
      } catch (err) {
        el.pageRangeInput.classList.add("is-invalid");
        el.rangeErrorMsg.textContent = err.message;
        el.rangeErrorMsg.classList.remove("hidden");
      }
    });

    // Copies stepper & quick presets
    el.copiesMinusBtn.addEventListener("click", () => {
      state.copies = Math.max(1, state.copies - 1);
      el.copiesValue.textContent = String(state.copies);
      updateMetricsSummary();
    });
    el.copiesPlusBtn.addEventListener("click", () => {
      state.copies = Math.min(99, state.copies + 1);
      el.copiesValue.textContent = String(state.copies);
      updateMetricsSummary();
    });
    document.querySelectorAll(".copy-preset-btn[data-copy-preset]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const val = parseInt(btn.getAttribute("data-copy-preset"), 10) || 1;
        state.copies = Math.max(1, Math.min(99, val));
        el.copiesValue.textContent = String(state.copies);
        updateMetricsSummary();
      });
    });

    // Color mode
    el.colorBwBtn.addEventListener("click", () => setColorMode("bw"));
    el.colorColorBtn.addEventListener("click", () => setColorMode("color"));
    if (el.colorMixedBtn) {
      el.colorMixedBtn.addEventListener("click", () => {
        setColorMode("mixed");
        if (el.colorPagesInput) el.colorPagesInput.focus();
      });
    }
    if (el.colorPagesInput) {
      el.colorPagesInput.addEventListener("input", () => {
        if (!state.currentDoc) return;
        try {
          const parsed = PageSelector.parseRange(
            el.colorPagesInput.value,
            state.currentDoc.page_count
          );
          state.colorPages = new Set(parsed);
          el.colorPagesInput.classList.remove("is-invalid");
          updateColorFilterClass();
          updateMetricsSummary();
        } catch (_) {
          el.colorPagesInput.classList.add("is-invalid");
        }
      });
    }

    // Default print side is always single-sided ("simplex")
    state.duplex = "simplex";

    // Orientation
    el.orientPortraitBtn.addEventListener("click", () => {
      state.orientation = "portrait";
      el.orientPortraitBtn.classList.add("is-active");
      el.orientLandscapeBtn.classList.remove("is-active");
      saveStudioDraft();
    });
    el.orientLandscapeBtn.addEventListener("click", () => {
      state.orientation = "landscape";
      el.orientLandscapeBtn.classList.add("is-active");
      el.orientPortraitBtn.classList.remove("is-active");
      saveStudioDraft();
    });

    el.pagesPerSheetSelect.addEventListener("change", () => {
      state.pagesPerSheet = parseInt(el.pagesPerSheetSelect.value, 10) || 1;
      updateMetricsSummary();
    });

    el.paperSizeSelect.addEventListener("change", () => {
      state.paperSize = el.paperSizeSelect.value;
      saveStudioDraft();
    });

    if (el.studentNameInput) {
      el.studentNameInput.addEventListener("input", saveStudioDraft);
    }
    if (el.printerSelect) {
      el.printerSelect.addEventListener("change", saveStudioDraft);
    }

    // Submit Print
    el.printSubmitBtn.addEventListener("click", submitPrintJob);
    if (el.mobilePrintSubmitBtn) {
      el.mobilePrintSubmitBtn.addEventListener("click", submitPrintJob);
    }

    // Admin side navigation (one section visible at a time)
    document.querySelectorAll(".admin-nav-btn[data-admin-tab]").forEach((tabBtn) => {
      tabBtn.addEventListener("click", () => {
        setActiveAdminTab(tabBtn.getAttribute("data-admin-tab"));
      });
    });

    // Zoom modal controls
    el.zoomCloseBtn.addEventListener("click", closeZoomModal);
    el.zoomModal.addEventListener("click", (e) => {
      if (e.target === el.zoomModal) closeZoomModal();
    });
    el.zoomPrevBtn.addEventListener("click", async () => {
      if (state.zoomPage > 1) {
        state.zoomPage -= 1;
        await renderZoomCanvas();
      }
    });
    el.zoomNextBtn.addEventListener("click", async () => {
      if (state.currentDoc && state.zoomPage < state.currentDoc.page_count) {
        state.zoomPage += 1;
        await renderZoomCanvas();
      }
    });
    el.zoomToggleSelectBtn.addEventListener("click", () => {
      togglePageSelection(state.zoomPage);
    });
    el.zoomRotateBtn.addEventListener("click", async () => {
      await rotatePage(state.zoomPage);
    });

    document.addEventListener("keydown", async (e) => {
      if (e.key === "Escape") {
        if (!el.zoomModal.classList.contains("hidden")) closeZoomModal();
        if (!el.adminLoginModal.classList.contains("hidden")) closeAdminLoginModal();
        if (!el.jobResultModal.classList.contains("hidden")) closeJobModal();
      } else if (!el.zoomModal.classList.contains("hidden")) {
        if (e.key === "ArrowLeft" && state.zoomPage > 1) {
          state.zoomPage -= 1;
          await renderZoomCanvas();
        } else if (
          e.key === "ArrowRight" &&
          state.currentDoc &&
          state.zoomPage < state.currentDoc.page_count
        ) {
          state.zoomPage += 1;
          await renderZoomCanvas();
        }
      }
    });

    if (el.toggleQueueDetailsBtn) {
      el.toggleQueueDetailsBtn.addEventListener("click", () => {
        state.showQueueDetails = !state.showQueueDetails;
        el.toggleQueueDetailsBtn.textContent = state.showQueueDetails ? "Yashirish" : "Tafsilotlar";
        renderLiveQueue();
      });
    }

    // Job Result Modal
    el.jobModalCloseBtn.addEventListener("click", closeJobModal);
    el.jobDoneBtn.addEventListener("click", closeJobModal);
  }

  async function restoreSessionOnLoad() {
    const savedAdminTab = sessionStorage.getItem(ADMIN_TAB_KEY);
    if (savedAdminTab) {
      setActiveAdminTab(savedAdminTab);
    }

    const wasAdminView = sessionStorage.getItem(ADMIN_VIEW_KEY) === "admin";
    if (wasAdminView && SmartPrintApi.getAdminToken()) {
      await openAdminSection();
    }

    const savedDraft = readJsonStorage(localStorage, STUDIO_DRAFT_KEY, null);
    if (savedDraft && savedDraft.docId) {
      try {
        const doc = await SmartPrintApi.getDocument(savedDraft.docId);
        await openDocumentInStudio(doc, savedDraft);
      } catch (_) {
        clearStudioDraft();
      }
    }

    const modalState = readJsonStorage(localStorage, MODAL_STATE_KEY, {});
    const myJobs = await refreshMyActiveJobs();
    const openJobId = (modalState && modalState.openJobId) || "";
    const dismissedJobId = (modalState && modalState.dismissedJobId) || "";

    let jobToReopen = null;
    const awaiting = myJobs.find((j) => j.queue_state === "AWAITING_PAYMENT");
    if (awaiting && awaiting.id !== dismissedJobId) {
      jobToReopen = awaiting;
    } else if (openJobId && openJobId !== dismissedJobId) {
      jobToReopen = myJobs.find((j) => j.id === openJobId) || null;
      if (!jobToReopen) {
        try {
          const fetched = await SmartPrintApi.getPrintJob(openJobId);
          if (fetched && fetched.queue_state !== "CANCELLED") {
            jobToReopen = fetched;
          }
        } catch (_) {
          saveModalState("", "");
        }
      }
    }
    if (jobToReopen) {
      showJobResultModal(jobToReopen);
    }
  }

  async function init() {
    bindEvents();
    const initialView =
      sessionStorage.getItem(ADMIN_VIEW_KEY) === "admin" && SmartPrintApi.getAdminToken()
        ? "admin"
        : "student";
    setActiveView(initialView);
    await Promise.all([loadSystemStatus(), loadLiveQueue()]);
    await restoreSessionOnLoad();
    if (state.queuePollTimer) {
      clearInterval(state.queuePollTimer);
    }
    state.queuePollTimer = setInterval(loadLiveQueue, 2000);
  }

  init();
})();
