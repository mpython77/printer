/**
 * Bidirectional page selection & range formatter/parser.
 */
window.PageSelector = (() => {
  function parseRange(rangeStr, maxPages) {
    if (!maxPages || maxPages < 1) return [];
    const cleaned = (rangeStr || "").trim().toLowerCase();
    if (!cleaned) return [];
    if (cleaned === "all" || cleaned === "barchasi" || cleaned === "*") {
      return Array.from({ length: maxPages }, (_, idx) => idx + 1);
    }

    const selected = new Set();
    const tokens = cleaned
      .replace(/;/g, ",")
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);

    for (const token of tokens) {
      if (token.includes("-")) {
        const parts = token.split("-").map((p) => p.trim());
        if (parts.length !== 2 || !/^\d+$/.test(parts[0]) || !/^\d+$/.test(parts[1])) {
          throw new Error(`Noto'g'ri oraliq: "${token}"`);
        }
        let start = parseInt(parts[0], 10);
        let end = parseInt(parts[1], 10);
        if (start > end) [start, end] = [end, start];
        for (let p = Math.max(1, start); p <= Math.min(maxPages, end); p += 1) {
          selected.add(p);
        }
      } else {
        if (!/^\d+$/.test(token)) {
          throw new Error(`Noto'g'ri bet raqami: "${token}"`);
        }
        const page = parseInt(token, 10);
        if (page < 1 || page > maxPages) {
          throw new Error(`${page}-bet mavjud emas (1–${maxPages})`);
        }
        selected.add(page);
      }
    }

    return Array.from(selected).sort((a, b) => a - b);
  }

  function formatRange(pages) {
    const sorted = Array.from(new Set(pages))
      .filter((p) => Number.isInteger(p) && p >= 1)
      .sort((a, b) => a - b);
    if (!sorted.length) return "";

    const parts = [];
    let start = sorted[0];
    let prev = sorted[0];
    for (let i = 1; i < sorted.length; i += 1) {
      const current = sorted[i];
      if (current === prev + 1) {
        prev = current;
      } else {
        parts.push(start === prev ? `${start}` : `${start}-${prev}`);
        start = current;
        prev = current;
      }
    }
    parts.push(start === prev ? `${start}` : `${start}-${prev}`);
    return parts.join(", ");
  }

  return {
    parseRange,
    formatRange,
  };
})();
