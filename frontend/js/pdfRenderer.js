/**
 * Backend pypdfium2 page-image renderer with PDF.js fallback for 1:1 print preview parity.
 */
window.PdfRenderer = (() => {
  if (window.pdfjsLib) {
    window.pdfjsLib.GlobalWorkerOptions.workerSrc = "/vendor/pdf.worker.min.js";
  }

  let activePdfDoc = null;
  let activeDocMeta = null;
  let renderGeneration = 0;
  const imagePromiseCache = new Map();

  function extractDocIdFromUrl(pdfUrl) {
    const match = String(pdfUrl || "").match(/\/api\/documents\/([a-zA-Z0-9_-]+)\/pdf/i);
    return match ? match[1] : null;
  }

  async function ensureFallbackPdfJsDoc(pdfUrl) {
    if (activePdfDoc) return activePdfDoc;
    if (!window.pdfjsLib) {
      throw new Error("PDF.js kutubxonasi yuklanmadi.");
    }
    const loadingTask = window.pdfjsLib.getDocument(pdfUrl);
    activePdfDoc = await loadingTask.promise;
    return activePdfDoc;
  }

  function loadPageImage(docId, pageNumber, scale, cacheBust) {
    const key = `${docId}:${pageNumber}:${scale}`;
    if (imagePromiseCache.has(key)) {
      return imagePromiseCache.get(key);
    }
    const promise = new Promise((resolve, reject) => {
      const img = new Image();
      img.decoding = "async";
      img.onload = () => resolve(img);
      img.onerror = () => {
        imagePromiseCache.delete(key);
        reject(new Error(`Sahifa tasviri yuklanmadi: ${pageNumber}`));
      };
      img.src = `/api/documents/${encodeURIComponent(docId)}/pages/${pageNumber}/image?scale=${scale}&v=${cacheBust}`;
    });
    imagePromiseCache.set(key, promise);
    return promise;
  }

  async function loadPdf(pdfUrl, pageCount = 0) {
    renderGeneration += 1;
    imagePromiseCache.clear();
    if (activePdfDoc) {
      try {
        await activePdfDoc.destroy();
      } catch (_) {
        // ignore cleanup error
      }
      activePdfDoc = null;
    }

    const docId = extractDocIdFromUrl(pdfUrl);
    let total = Number(pageCount) || 0;
    if (docId && !total) {
      try {
        const res = await fetch(`/api/documents/${encodeURIComponent(docId)}`);
        if (res.ok) {
          const info = await res.json();
          total = Number(info.page_count) || 0;
        }
      } catch (_) {
        // fall through to PDF.js metadata if metadata lookup fails
      }
    }

    activeDocMeta = {
      docId,
      pdfUrl,
      numPages: total,
      cacheBust: Date.now(),
      useImageApi: Boolean(docId),
    };

    if (!activeDocMeta.useImageApi || !activeDocMeta.numPages) {
      const pdfDoc = await ensureFallbackPdfJsDoc(pdfUrl);
      activeDocMeta.numPages = pdfDoc.numPages;
    }

    return activeDocMeta;
  }

  async function renderImageToCanvas(img, canvas, targetWidth, extraRotation, fitContainer) {
    const natW = Math.max(1, img.naturalWidth || img.width || 1);
    const natH = Math.max(1, img.naturalHeight || img.height || 1);
    const rot = (((Number(extraRotation) || 0) % 360) + 360) % 360;
    const swap = rot === 90 || rot === 270;
    const rotW = swap ? natH : natW;
    const rotH = swap ? natW : natH;

    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const cssW = Math.max(1, Math.round(targetWidth));
    const cssH = Math.max(1, Math.round(targetWidth * (rotH / rotW)));

    canvas.width = Math.max(1, Math.floor(cssW * dpr));
    canvas.height = Math.max(1, Math.floor(cssH * dpr));

    if (fitContainer && canvas.parentElement) {
      const isLandscape = rotW > rotH;
      canvas.parentElement.classList.toggle("is-landscape", isLandscape);
      const card = canvas.parentElement.closest(".page-card");
      if (card) card.classList.toggle("is-landscape-card", isLandscape);
    }
    if (fitContainer) {
      canvas.style.width = "";
      canvas.style.height = "";
    } else {
      canvas.style.width = `${cssW}px`;
      canvas.style.height = `${cssH}px`;
    }

    const ctx = canvas.getContext("2d", { alpha: false });
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    ctx.save();
    ctx.translate(canvas.width / 2, canvas.height / 2);
    if (rot !== 0) {
      ctx.rotate((rot * Math.PI) / 180);
    }
    const drawW = swap ? canvas.height : canvas.width;
    const drawH = swap ? canvas.width : canvas.height;
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = "high";
    ctx.drawImage(img, -drawW / 2, -drawH / 2, drawW, drawH);
    ctx.restore();
  }

  async function renderPdfJsPageToCanvas(pageNumber, canvas, targetWidth, extraRotation, fitContainer) {
    const pdfDoc = await ensureFallbackPdfJsDoc(activeDocMeta.pdfUrl);
    const page = await pdfDoc.getPage(pageNumber);
    const rotation = (page.rotate + extraRotation) % 360;
    const rotatedBase = page.getViewport({ scale: 1, rotation });

    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const scale = (targetWidth / rotatedBase.width) * dpr;
    const viewport = page.getViewport({ scale, rotation });

    canvas.width = Math.floor(viewport.width);
    canvas.height = Math.floor(viewport.height);
    if (fitContainer && canvas.parentElement) {
      const isLandscape = rotatedBase.width > rotatedBase.height;
      canvas.parentElement.classList.toggle("is-landscape", isLandscape);
      const card = canvas.parentElement.closest(".page-card");
      if (card) card.classList.toggle("is-landscape-card", isLandscape);
    }
    if (fitContainer) {
      canvas.style.width = "";
      canvas.style.height = "";
    } else {
      canvas.style.width = `${Math.round(viewport.width / dpr)}px`;
      canvas.style.height = `${Math.round(viewport.height / dpr)}px`;
    }

    const ctx = canvas.getContext("2d", { alpha: false });
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    await page.render({
      canvasContext: ctx,
      viewport,
    }).promise;
  }

  async function renderPageToCanvas(pageNumber, canvas, targetWidth = 340, extraRotation = 0, fitContainer = true) {
    if (!activeDocMeta || !canvas) return;
    if (activeDocMeta.useImageApi && activeDocMeta.docId) {
      const reqScale = targetWidth > 420 ? 2.2 : 1.5;
      try {
        const img = await loadPageImage(activeDocMeta.docId, pageNumber, reqScale, activeDocMeta.cacheBust);
        await renderImageToCanvas(img, canvas, targetWidth, extraRotation, fitContainer);
        return;
      } catch (_) {
        activeDocMeta.useImageApi = false;
      }
    }
    await renderPdfJsPageToCanvas(pageNumber, canvas, targetWidth, extraRotation, fitContainer);
  }

  async function renderAllThumbnails(canvasesMap, rotationsMap) {
    if (!activeDocMeta) return;
    const myGen = renderGeneration;
    const total = getNumPages();

    for (let pageNum = 1; pageNum <= total; pageNum += 1) {
      if (myGen !== renderGeneration) return;
      const canvas = canvasesMap.get(pageNum);
      if (!canvas) continue;
      const rot = rotationsMap[String(pageNum)] || 0;
      await renderPageToCanvas(pageNum, canvas, 340, rot, true);
    }
  }

  function getNumPages() {
    if (activeDocMeta && activeDocMeta.numPages) return activeDocMeta.numPages;
    return activePdfDoc ? activePdfDoc.numPages : 0;
  }

  return {
    loadPdf,
    renderPageToCanvas,
    renderAllThumbnails,
    getNumPages,
  };
})();
