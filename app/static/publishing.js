(() => {
  "use strict";

  const previewFrame = document.querySelector(".preview-frame");
  const copyButton = document.querySelector("#copy-rich-text");
  const downloadButton = document.querySelector("#download-html");
  const status = document.querySelector("#publish-status");
  const contextLabel = document.querySelector("#preview-context-label");
  const wechatPushForm = document.querySelector("#wechat-push-form");
  const wechatPreflightButton = document.querySelector("#wechat-preflight-button");
  const tabButtons = Array.from(document.querySelectorAll("[data-preview-target]"));
  const widthButtons = Array.from(document.querySelectorAll("[data-preview-width]"));

  if (!previewFrame || !copyButton || !downloadButton || !status) {
    return;
  }

  const activePane = () =>
    previewFrame.querySelector(".preview-pane:not([hidden])");
  const activePreview = () => activePane()?.querySelector(".publish-preview");
  const activePlainText = () =>
    activePane()?.querySelector(".publish-plain-text")?.value || "";

  const setStatus = (message, tone = "") => {
    status.textContent = message;
    status.classList.remove("success", "error");
    if (tone) {
      status.classList.add(tone);
    }
  };

  const waitForMathJax = async () => {
    if (window.MathJax?.startup?.promise) {
      await window.MathJax.startup.promise;
    }
  };

  const svgToPng = (svg, width, height) =>
    new Promise((resolve, reject) => {
      const copy = svg.cloneNode(true);
      copy.setAttribute("xmlns", "http://www.w3.org/2000/svg");
      const source = new XMLSerializer().serializeToString(copy);
      const blob = new Blob([source], { type: "image/svg+xml;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const image = new Image();

      image.onload = () => {
        try {
          const scale = 2;
          const canvas = document.createElement("canvas");
          canvas.width = Math.max(1, Math.ceil(width * scale));
          canvas.height = Math.max(1, Math.ceil(height * scale));
          const context = canvas.getContext("2d");
          context.scale(scale, scale);
          context.drawImage(image, 0, 0, width, height);
          resolve(canvas.toDataURL("image/png"));
        } catch (error) {
          reject(error);
        } finally {
          URL.revokeObjectURL(url);
        }
      };
      image.onerror = () => {
        URL.revokeObjectURL(url);
        reject(new Error("公式图片转换失败"));
      };
      image.src = url;
    });

  const blobToDataUrl = (blob) =>
    new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = () => reject(new Error("图片读取失败"));
      reader.readAsDataURL(blob);
    });

  const embedImages = async (root) => {
    let embeddedImageCount = 0;
    let imageFallbackCount = 0;
    const images = Array.from(root.querySelectorAll("img"));

    for (const image of images) {
      const source = image.getAttribute("src") || "";
      if (!source || source.startsWith("data:image/")) {
        continue;
      }

      try {
        const imageUrl = new URL(source, window.location.href);
        if (!["http:", "https:"].includes(imageUrl.protocol)) {
          throw new Error("图片地址不受支持");
        }
        if (
          imageUrl.protocol === "https:" &&
          imageUrl.hostname.toLowerCase() === "mmbiz.qpic.cn"
        ) {
          image.removeAttribute("srcset");
          continue;
        }
        const sameOrigin = imageUrl.origin === window.location.origin;
        const response = await fetch(imageUrl.href, {
          cache: "force-cache",
          credentials: sameOrigin ? "same-origin" : "omit",
          mode: "cors",
        });
        if (!response.ok) {
          throw new Error(`图片请求失败：${response.status}`);
        }
        const blob = await response.blob();
        if (!blob.type.startsWith("image/")) {
          throw new Error("返回内容不是图片");
        }
        image.setAttribute("src", await blobToDataUrl(blob));
        image.removeAttribute("srcset");
        embeddedImageCount += 1;
      } catch (_error) {
        try {
          image.setAttribute("src", new URL(source, window.location.href).href);
        } catch (_urlError) {
          // Keep the sanitized renderer value when it cannot be normalized.
        }
        imageFallbackCount += 1;
      }
    }

    return { embeddedImageCount, imageFallbackCount };
  };

  const cleanInlineStyle = (value) =>
    value
      .split(";")
      .map((part) => part.trim())
      .filter((part) => {
        if (!part || !part.includes(":")) {
          return false;
        }
        const cssValue = part.slice(part.indexOf(":") + 1).trim();
        return (
          cssValue &&
          !/\b(?:undefined|null|expression)\b/i.test(cssValue) &&
          !/var\s*\(/i.test(cssValue) &&
          !/javascript\s*:/i.test(cssValue)
        );
      })
      .join(";");

  const normalizeExportNode = (root) => {
    const nodes = [root, ...root.querySelectorAll("*")];
    nodes.forEach((node) => {
      Array.from(node.attributes || []).forEach((attribute) => {
        const name = attribute.name.toLowerCase();
        if (
          name === "class" ||
          name === "id" ||
          name === "contenteditable" ||
          name.startsWith("on") ||
          (name.startsWith("data-") && name !== "data-platform")
        ) {
          node.removeAttribute(attribute.name);
        }
      });
      const style = cleanInlineStyle(node.getAttribute("style") || "");
      if (style) {
        node.setAttribute("style", style);
      } else {
        node.removeAttribute("style");
      }
    });

    root.querySelectorAll("a[href]").forEach((link) => {
      const href = link.getAttribute("href") || "";
      if (!/^(?:https?:|mailto:)/i.test(href)) {
        link.removeAttribute("href");
      }
    });
    root.querySelectorAll("table").forEach((table) => {
      table.style.width = "100%";
      table.style.maxWidth = "100%";
      table.style.tableLayout = "fixed";
    });
    root.querySelectorAll("th, td").forEach((cell) => {
      cell.style.whiteSpace = "normal";
      cell.style.wordBreak = "break-word";
      cell.style.overflowWrap = "anywhere";
    });
    root.querySelectorAll("pre, pre code").forEach((code) => {
      code.style.maxWidth = "100%";
      code.style.overflow = "visible";
      code.style.whiteSpace = "pre-wrap";
      code.style.wordBreak = "break-all";
    });
  };

  const emptyBoundary = () => {
    const node = document.createElement("p");
    node.style.fontSize = "0";
    node.style.lineHeight = "0";
    node.style.margin = "0";
    node.innerHTML = "&nbsp;";
    return node;
  };

  const prepareExport = async () => {
    await waitForMathJax();
    const preview = activePreview();
    if (!preview) {
      throw new Error("没有可复制的正文预览");
    }
    const article = preview.firstElementChild;
    if (!article) {
      throw new Error("正文结构不完整");
    }
    const clone = article.cloneNode(true);
    const originalFormulas = Array.from(
      article.querySelectorAll("[data-formula-source]"),
    );
    const clonedFormulas = Array.from(
      clone.querySelectorAll("[data-formula-source]"),
    );
    let fallbackCount = 0;

    for (let index = 0; index < clonedFormulas.length; index += 1) {
      const original = originalFormulas[index];
      const formula = clonedFormulas[index];
      const container = original?.querySelector("mjx-container");
      const svg = container?.querySelector("svg");
      const source = formula.dataset.formulaSource || "";
      const display = formula.dataset.formulaDisplay || "inline";

      try {
        if (!svg) {
          throw new Error("公式尚未渲染");
        }
        const bounds = container.getBoundingClientRect();
        const width = Math.max(bounds.width, 12);
        const height = Math.max(bounds.height, 12);
        const dataUrl = await svgToPng(svg, width, height);
        const image = document.createElement("img");
        image.src = dataUrl;
        image.alt = source;
        image.style.maxWidth = "100%";
        image.style.height = "auto";
        image.style.verticalAlign = "middle";
        if (display === "block") {
          image.style.display = "block";
          image.style.margin = "20px auto";
        } else {
          image.style.display = "inline-block";
          image.style.margin = "0 3px";
        }
        formula.replaceWith(image);
      } catch (_error) {
        fallbackCount += 1;
        formula.textContent = source;
        formula.style.fontFamily = "Menlo,Consolas,monospace";
        formula.style.color = "#6a6255";
      }
    }
    const imageResult = await embedImages(clone);
    normalizeExportNode(clone);
    clone.insertBefore(emptyBoundary(), clone.firstChild);
    clone.appendChild(emptyBoundary());
    return {
      node: clone,
      formulaCount: clonedFormulas.length,
      formulaFallbackCount: fallbackCount,
      ...imageResult,
    };
  };

  if (wechatPushForm) {
    wechatPushForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (wechatPreflightButton) {
        wechatPreflightButton.disabled = true;
      }
      setStatus("正在固化公式、图片和最终公众号正文……");
      try {
        const prepared = await prepareExport();
        wechatPushForm.querySelector('[name="final_html"]').value =
          prepared.node.outerHTML;
        wechatPushForm.querySelector('[name="formula_count"]').value =
          String(prepared.formulaCount);
        wechatPushForm.querySelector('[name="image_fallback_count"]').value =
          String(prepared.imageFallbackCount);
        wechatPushForm.querySelector('[name="formula_fallback_count"]').value =
          String(prepared.formulaFallbackCount);
        if (prepared.imageFallbackCount || prepared.formulaFallbackCount) {
          throw new Error(
            "仍有外部图片或公式转换失败，请处理后再直推；富文本复制仍可使用。",
          );
        }
        setStatus("本地正文已准备，正在进入最终确认……", "success");
        wechatPushForm.submit();
      } catch (error) {
        setStatus(`草稿预检失败：${error.message}`, "error");
        if (wechatPreflightButton) {
          wechatPreflightButton.disabled = false;
        }
      }
    });
  }

  const resultSummary = (prepared) => {
    const details = [];
    if (prepared.embeddedImageCount) {
      details.push(`${prepared.embeddedImageCount} 张图片已内嵌`);
    }
    if (prepared.imageFallbackCount) {
      details.push(`${prepared.imageFallbackCount} 张图片需手动上传`);
    }
    if (prepared.formulaFallbackCount) {
      details.push(`${prepared.formulaFallbackCount} 个公式保留为 LaTeX`);
    }
    return details.length ? `；${details.join("，")}` : "";
  };

  const escapeHtml = (value) =>
    value.replace(
      /[&<>"']/g,
      (character) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[character],
    );

  const fallbackCopy = (html) => {
    const holder = document.createElement("div");
    holder.contentEditable = "true";
    holder.style.position = "fixed";
    holder.style.left = "-9999px";
    holder.innerHTML = html;
    document.body.appendChild(holder);
    const selection = window.getSelection();
    const range = document.createRange();
    range.selectNodeContents(holder);
    selection.removeAllRanges();
    selection.addRange(range);
    const copied = document.execCommand("copy");
    selection.removeAllRanges();
    holder.remove();
    if (!copied) {
      throw new Error("浏览器未允许复制");
    }
  };

  const copyArticle = async () => {
    copyButton.disabled = true;
    setStatus("正在处理公式、图片与公众号正文样式……");
    try {
      const prepared = await prepareExport();
      const html = prepared.node.outerHTML;
      if (navigator.clipboard?.write && window.ClipboardItem) {
        const item = new ClipboardItem({
          "text/html": new Blob([html], { type: "text/html" }),
          "text/plain": new Blob([activePlainText()], { type: "text/plain" }),
        });
        await navigator.clipboard.write([item]);
      } else {
        fallbackCopy(html);
      }
      const suffix = resultSummary(prepared);
      setStatus(`已复制，请粘贴到公众号编辑器并完成最终检查${suffix}。`, "success");
    } catch (error) {
      setStatus(`复制失败：${error.message || "请改用下载 HTML"}`, "error");
    } finally {
      copyButton.disabled = false;
    }
  };

  const downloadArticle = async () => {
    downloadButton.disabled = true;
    setStatus("正在生成包含公式与内嵌图片的正文 HTML……");
    try {
      const prepared = await prepareExport();
      const preview = activePreview();
      const documentHtml = [
        "<!doctype html>",
        '<html lang="zh-CN"><head><meta charset="utf-8">',
        `<title>${escapeHtml(preview?.dataset.exportTitle || "公众号文章")}</title>`,
        "</head><body>",
        prepared.node.outerHTML,
        "</body></html>",
      ].join("");
      const blob = new Blob([documentHtml], { type: "text/html;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      const safeTitle = (preview?.dataset.exportTitle || "wechat-article")
        .replace(/[\\/:*?"<>|]/g, "-")
        .slice(0, 80);
      anchor.href = url;
      anchor.download = `${safeTitle}.html`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
      const suffix = resultSummary(prepared);
      setStatus(`HTML 已生成，请打开检查正文${suffix}。`, "success");
    } catch (error) {
      setStatus(`下载失败：${error.message || "请稍后重试"}`, "error");
    } finally {
      downloadButton.disabled = false;
    }
  };

  copyButton.addEventListener("click", copyArticle);
  downloadButton.addEventListener("click", downloadArticle);

  widthButtons.forEach((button) => {
    button.addEventListener("click", () => {
      const isEditor = button.dataset.previewWidth === "editor";
      previewFrame.classList.toggle("is-editor", isEditor);
      previewFrame.classList.toggle("is-mobile", !isEditor);
      widthButtons.forEach((candidate) => {
        const active = candidate === button;
        candidate.classList.toggle("active", active);
        candidate.setAttribute("aria-pressed", String(active));
      });
    });
  });

  tabButtons.forEach((button) => {
    button.addEventListener("click", () => {
      const target = button.dataset.previewTarget;
      previewFrame.querySelectorAll("[data-preview-pane]").forEach((pane) => {
        pane.hidden = pane.dataset.previewPane !== target;
      });
      tabButtons.forEach((candidate) => {
        const active = candidate === button;
        candidate.classList.toggle("active", active);
        candidate.setAttribute("aria-selected", String(active));
      });
      if (contextLabel) {
        contextLabel.textContent = target === "candidate" ? "幻想栈候选正文" : "忠实正文";
      }
      setStatus("已切换预览，复制将使用当前标签页正文。");
    });
  });
})();
