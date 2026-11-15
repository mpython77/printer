/**
 * PDF.js renderer for page thumbnails and high-DPI zoom preview.
 */
window.PdfRenderer = (() => {
  if (window.pdfjsLib) {
    window.pdfjsLib.GlobalWorkerOptions.workerSrc = "/vendor/pdf.worker.min.js";
  }

  let activePdfDoc = null;
  let renderGeneration = 0;

  async function loadPdf(pdfUrl) {
    if (!window.pdfjsLib) {
      throw new Error("PDF.js kutubxonasi yuklanmadi.");
    }
    renderGeneration += 1;
    if (activePdfDoc) {
      try {
        await activePdfDoc.destroy();
      } catch (_) {
        // ignore cleanup error
      }
      activePdfDoc = null;
    }
    const loadingTask = window.pdfjsLib.getDocument(pdfUrl);
    activePdfDoc = await loadingTask.promise;
    return activePdfDoc;
  }

  async function renderPageToCanvas(pageNumber, canvas, targetWidth = 340, extraRotation = 0, fitContainer = true) {
    if (!activePdfDoc || !canvas) return;
    const page = await activePdfDoc.getPage(pageNumber);
    const rotation = (page.rotate + extraRotation) % 360;
    const rotatedBase = page.getViewport({ scale: 1, rotation });

    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const scale = (targetWidth / rotatedBase.width) * dpr;
    const viewport = page.getViewport({ scale, rotation });

    canvas.width = Math.floor(viewport.width);
    canvas.height = Math.floor(viewport.height);
    if (fitContainer && canvas.parentElement) {
      canvas.parentElement.classList.toggle("is-landscape", rotatedBase.width > rotatedBase.height);
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

  async function renderAllThumbnails(canvasesMap, rotationsMap) {
    if (!activePdfDoc) return;
    const myGen = renderGeneration;
    const total = activePdfDoc.numPages;

    for (let pageNum = 1; pageNum <= total; pageNum += 1) {
      if (myGen !== renderGeneration) return;
      const canvas = canvasesMap.get(pageNum);
      if (!canvas) continue;
      const rot = rotationsMap[String(pageNum)] || 0;
      await renderPageToCanvas(pageNum, canvas, 340, rot, true);
    }
  }

  function getNumPages() {
    return activePdfDoc ? activePdfDoc.numPages : 0;
  }

  return {
    loadPdf,
    renderPageToCanvas,
    renderAllThumbnails,
    getNumPages,
  };
})();
