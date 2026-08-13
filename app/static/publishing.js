(() => {
  "use strict";

  const preview = document.querySelector("#publish-preview");
  const plainText = document.querySelector("#publish-plain-text");
  const copyButton = document.querySelector("#copy-rich-text");
  const downloadButton = document.querySelector("#download-html");
  const status = document.querySelector("#publish-status");

  if (!preview || !plainText || !copyButton || !downloadButton || !status) {
    return;
  }

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

  const prepareExport = async () => {
    await waitForMathJax();
    const clone = preview.cloneNode(true);
    clone.removeAttribute("id");
    const originalFormulas = Array.from(
      preview.querySelectorAll("[data-formula-source]"),
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
    return {
      node: clone,
      formulaFallbackCount: fallbackCount,
      ...imageResult,
    };
  };

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
          "text/plain": new Blob([plainText.value], { type: "text/plain" }),
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
      const documentHtml = [
        "<!doctype html>",
        '<html lang="zh-CN"><head><meta charset="utf-8">',
        `<title>${escapeHtml(preview.dataset.exportTitle || "公众号文章")}</title>`,
        "</head><body>",
        prepared.node.outerHTML,
        "</body></html>",
      ].join("");
      const blob = new Blob([documentHtml], { type: "text/html;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      const safeTitle = (preview.dataset.exportTitle || "wechat-article")
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
})();
