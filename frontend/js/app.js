/**
 * Main controller for TLG SmartPrint student portal and protected Admin panel.
 */
(() => {
  const { SmartPrintApi, PageSelector, PdfRenderer } = window;

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

    selectionSummaryBadge: document.getElementById("selectionSummaryBadge"),
    btnSelectAll: document.getElementById("btnSelectAll"),
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
    duplexSimplexBtn: document.getElementById("duplexSimplexBtn"),
    duplexDuplexBtn: document.getElementById("duplexDuplexBtn"),
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
    printValidationHint: document.getElementById("printValidationHint"),

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

    newAdminUsername: document.getElementById("newAdminUsername"),
    currentAdminPassword: document.getElementById("currentAdminPassword"),
    newAdminPassword: document.getElementById("newAdminPassword"),
    saveCredentialsBtn: document.getElementById("saveCredentialsBtn"),

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

  function setActiveView(viewName) {
    const isAdmin = viewName === "admin";
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
        if (status.printer_mode === "LINUX_CUPS") {
          el.printerModeText.textContent = "Rejim: Raspberry Pi CUPS faol";
        } else if (status.printer_mode === "REMOTE_AGENT") {
          el.printerModeText.textContent = "Rejim: Raspberry Pi ko'prigi faol";
        } else {
          el.printerModeText.textContent = "Rejim: Jonli printer faol";
        }
      } else {
        el.printerModeBadge.className = "status-pill status-pill--dryrun";
        el.printerModeText.textContent = "Rejim: Printer ulanmagan (Test)";
      }

      const preferred =
        status.printers.find((p) => p.name === status.default_printer_name) ||
        status.printers.find((p) => p.name.toLowerCase().includes("canon")) ||
        status.printers.find((p) => p.is_default) ||
        status.printers[0];

      el.detectedPrinterName.textContent = preferred
        ? preferred.name
        : "Printer ulanmagan";

      const currentVal = el.printerSelect.value;
      el.printerSelect.innerHTML = `<option value="">Avtomatik (Keyin ulanadi)</option>`;
      status.printers.forEach((printer) => {
        const opt = document.createElement("option");
        opt.value = printer.name;
        opt.textContent = `${printer.name} — ${printer.status_text}`;
        el.printerSelect.appendChild(opt);
      });
      if (currentVal) {
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

  async function openDocumentInStudio(doc) {
    state.currentDoc = doc;
    state.rotations = {};
    state.colorPages = new Set();
    if (el.colorPagesInput) {
      el.colorPagesInput.value = "";
    }
    state.selectedPages = new Set(Array.from({ length: doc.page_count }, (_, i) => i + 1));

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

    await PdfRenderer.loadPdf(doc.pdf_url);
    await PdfRenderer.renderAllThumbnails(state.pageCanvases, state.rotations);
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
        <span class="page-select-pill">✓ Tanlangan</span>
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
      rotateBtn.textContent = "↻ 90°";
      rotateBtn.addEventListener("click", async (e) => {
        e.stopPropagation();
        await rotatePage(pageNum);
      });

      const colorBtn = document.createElement("button");
      colorBtn.type = "button";
      colorBtn.className = "card-action-btn card-color-btn";
      colorBtn.textContent = "◐ Oq-qora";
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
        pill.textContent = isSelected ? "✓ Tanlangan" : "O'tkaziladi";
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
        btn.textContent = isColor ? "🎨 Rangli" : "◐ Oq-qora";
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
    el.summaryCostText.textContent = formatMoney(estimatedCost);
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
    } catch (err) {
      showToast(err.message, "error");
    } finally {
      el.printSubmitBtn.innerHTML = originalHtml;
      el.printSubmitBtn.disabled = state.selectedPages.size === 0;
    }
  }

  function showJobResultModal(job) {
    stopCountdownTimer();
    el.jobResultPdfLink.href = job.pdf_url;
    const totalSec = Math.max(0, parseInt(job.estimated_seconds, 10) || 0);
    const countdownMarkup =
      totalSec > 0
        ? `
      <div class="countdown-banner" id="jobCountdownBox">
        <div class="countdown-head">
          <span>Printer chiqish taymeri</span>
          <strong id="jobCountdownText">${escapeHtml(formatDuration(totalSec))} qoldi</strong>
        </div>
        <div class="countdown-bar-track">
          <div class="countdown-bar-fill" id="jobCountdownFill" style="width: 0%"></div>
        </div>
      </div>`
        : "";

    const colorLabel =
      job.color_mode === "mixed"
        ? `Aralash (${job.bw_sheets} oq-qora, ${job.color_sheets} rangli)`
        : job.color_mode === "color"
          ? "Rangli"
          : "Oq-qora";
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
      <div class="result-notice">
        <strong>${escapeHtml(job.status_message)}</strong>
      </div>
      ${countdownMarkup}
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
          <span>Tanlangan betlar</span>
          <strong>${escapeHtml(job.page_range_text)} (${job.selected_page_count} bet)</strong>
        </div>
        <div class="spec-box">
          <span>Sozlamalar</span>
          <strong>${job.copies} nusxa • ${escapeHtml(colorLabel)} • ${job.duplex === "duplex" ? "2 tomonlama" : "1 tomonlama"}</strong>
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
    el.jobResultModal.classList.remove("hidden");

    if (totalSec > 0) {
      const startedAt = Date.now();
      const textEl = document.getElementById("jobCountdownText");
      const fillEl = document.getElementById("jobCountdownFill");
      state.countdownTimer = setInterval(() => {
        const elapsed = (Date.now() - startedAt) / 1000;
        const remaining = Math.max(0, Math.ceil(totalSec - elapsed));
        const pct = Math.min(100, Math.round((elapsed / totalSec) * 100));
        if (fillEl) fillEl.style.width = `${pct}%`;
        if (remaining <= 0) {
          if (textEl) textEl.textContent = "Hisoblangan chiqish vaqti yakunlandi!";
          stopCountdownTimer();
        } else if (textEl) {
          textEl.textContent = `${formatDuration(remaining)} qoldi`;
        }
      }, 1000);
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

    // Populate Admin Printers dropdown & status list
    el.adminDefaultPrinterSelect.innerHTML = `<option value="">Avtomatik (Standart printer)</option>`;
    data.printers.forEach((p) => {
      const opt = document.createElement("option");
      opt.value = p.name;
      opt.textContent = `${p.name} — ${p.status_text}`;
      el.adminDefaultPrinterSelect.appendChild(opt);
    });
    el.adminDefaultPrinterSelect.value = data.settings.default_printer_name || "";
    if (el.adminAgentKeyInput) {
      el.adminAgentKeyInput.value = data.settings.agent_api_key || "";
    }

    if (el.piAgentStatusBox) {
      if (data.settings.agent_last_seen) {
        el.piAgentStatusBox.innerHTML = `
          <span><strong>Raspberry Pi Agent:</strong> ${escapeHtml(data.settings.agent_hostname || "raspberrypi")}</span>
          <span class="status-tag status-tag--ok">Oxirgi aloqa: ${escapeHtml(formatDateTime(data.settings.agent_last_seen))}</span>
        `;
      } else {
        el.piAgentStatusBox.innerHTML = `
          <span><strong>Raspberry Pi Agent:</strong> Hali ulanmagan</span>
          <span class="status-tag">REMOTE_AGENT kutilmoqda</span>
        `;
      }
    }

    if (!data.printers.length) {
      el.adminPrintersList.innerHTML = `<div class="printer-mini-item">Mahalliy yoki Raspberry Pi printerlari aniqlanmadi.</div>`;
    } else {
      el.adminPrintersList.innerHTML = data.printers
        .map(
          (p) => `
        <div class="printer-mini-item">
          <span><strong>${escapeHtml(p.name)}</strong></span>
          <span class="status-tag ${p.is_offline ? "" : "status-tag--ok"}">${escapeHtml(p.status_text)}</span>
        </div>
      `
        )
        .join("");
    }

    renderAdminJobsList();
  }

  function getStatusBadgeInfo(status) {
    switch (status) {
      case "COMPLETED":
        return { label: "Chop etilgan", cls: "status-tag--ok" };
      case "SENT_TO_PRINTER":
        return { label: "Printerga yuborildi", cls: "status-tag--ok" };
      case "PRINTING_ON_PI":
        return { label: "Raspberry Pi chop etmoqda", cls: "status-tag--ok" };
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
        return `
        <div class="queue-item">
          <div class="queue-item-main">
            <h4>${escapeHtml(job.original_filename)} <span class="version-pill">${escapeHtml(job.id)}</span></h4>
            <div class="queue-meta">
              <span class="tag-pill">${escapeHtml(formatDateTime(job.created_at))}</span>
              <span class="tag-pill">O'quvchi: ${escapeHtml(job.student_name || "Ko'rsatilmagan")}</span>
              <span class="tag-pill">Betlar: ${escapeHtml(job.page_range_text)} (${job.selected_page_count} bet)</span>
              <span class="tag-pill">${job.copies} nusxa • ${escapeHtml(jobColorLabel)} • ${job.duplex === "duplex" ? "2 tomonlama" : "1 tomonlama"} • ${job.pages_per_sheet}x</span>
              <span class="tag-pill">${job.physical_sheets} varaq</span>
              <span class="tag-pill">Vaqt: ${escapeHtml(formatDuration(job.estimated_seconds))}</span>
              <span class="tag-pill">${formatMoney(job.estimated_cost)}</span>
            </div>
          </div>
          <div class="queue-item-actions">
            <span class="status-tag ${badge.cls}">${badge.label}</span>
            <a href="${job.pdf_url}" target="_blank" rel="noopener" class="btn btn-primary btn-sm">Tayyor PDF</a>
            <a href="${job.original_pdf_url}" target="_blank" rel="noopener" class="btn btn-secondary btn-sm">Asl PDF</a>
            ${
              job.status !== "COMPLETED"
                ? `<button type="button" class="btn btn-secondary btn-sm admin-complete-btn" data-job-id="${escapeHtml(job.id)}">Chop etildi</button>`
                : ""
            }
            <button type="button" class="btn btn-ghost btn-sm admin-delete-btn" data-job-id="${escapeHtml(job.id)}">O'chirish</button>
          </div>
        </div>
      `;
      })
      .join("");

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

  async function saveAdminSettingsFromUI(successMessage) {
    const bwSimplex = Math.max(0, parseInt(el.priceBwSimplexInput.value, 10) || 0);
    const bwDuplex = Math.max(0, parseInt(el.priceBwDuplexInput.value, 10) || 0);
    const colorSimplex = Math.max(0, parseInt(el.priceColorSimplexInput.value, 10) || 0);
    const colorDuplex = Math.max(0, parseInt(el.priceColorDuplexInput.value, 10) || 0);
    const secondsBw = Math.max(1, parseInt(el.secondsBwInput ? el.secondsBwInput.value : "7", 10) || 7);
    const secondsColor = Math.max(1, parseInt(el.secondsColorInput ? el.secondsColorInput.value : "14", 10) || 14);

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
    el.saveCredentialsBtn.addEventListener("click", handleUpdateCredentials);
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

    el.btnClearSelection.addEventListener("click", () => {
      state.selectedPages.clear();
      syncSelectionUI({ syncTextInput: true });
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

    // Copies stepper
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

    // Duplex
    el.duplexSimplexBtn.addEventListener("click", () => {
      state.duplex = "simplex";
      el.duplexSimplexBtn.classList.add("is-active");
      el.duplexDuplexBtn.classList.remove("is-active");
      updateMetricsSummary();
    });
    el.duplexDuplexBtn.addEventListener("click", () => {
      state.duplex = "duplex";
      el.duplexDuplexBtn.classList.add("is-active");
      el.duplexSimplexBtn.classList.remove("is-active");
      updateMetricsSummary();
    });

    // Orientation
    el.orientPortraitBtn.addEventListener("click", () => {
      state.orientation = "portrait";
      el.orientPortraitBtn.classList.add("is-active");
      el.orientLandscapeBtn.classList.remove("is-active");
    });
    el.orientLandscapeBtn.addEventListener("click", () => {
      state.orientation = "landscape";
      el.orientLandscapeBtn.classList.add("is-active");
      el.orientPortraitBtn.classList.remove("is-active");
    });

    el.pagesPerSheetSelect.addEventListener("change", () => {
      state.pagesPerSheet = parseInt(el.pagesPerSheetSelect.value, 10) || 1;
      updateMetricsSummary();
    });

    el.paperSizeSelect.addEventListener("change", () => {
      state.paperSize = el.paperSizeSelect.value;
    });

    // Submit Print
    el.printSubmitBtn.addEventListener("click", submitPrintJob);

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

    // Job Result Modal
    const closeJobModal = () => {
      stopCountdownTimer();
      el.jobResultModal.classList.add("hidden");
    };
    el.jobModalCloseBtn.addEventListener("click", closeJobModal);
    el.jobDoneBtn.addEventListener("click", closeJobModal);
  }

  async function init() {
    bindEvents();
    setActiveView("student");
    await loadSystemStatus();
  }

  init();
})();
