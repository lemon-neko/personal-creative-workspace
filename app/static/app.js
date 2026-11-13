document.addEventListener("htmx:configRequest", (event) => {
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content;
  if (csrf) event.detail.headers["X-CSRF-Token"] = csrf;
  for (const [key, value] of Object.entries(event.detail.parameters)) {
    if (value === "") {
      delete event.detail.parameters[key];
    }
  }
});

const palette = document.querySelector("#search-palette");
const paletteInput = document.querySelector("#palette-query");
function openSearch() {
  if (palette && !palette.open) {
    palette.showModal();
    paletteInput?.focus();
  }
}
document.addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    if (palette?.showModal) openSearch();
    else window.location.assign("/search");
  }
});
document.addEventListener("click", (event) => {
  if (event.target.closest("[data-open-search]") && palette?.showModal
      && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey) {
    event.preventDefault();
    openSearch();
  }
});
palette?.addEventListener("click", (event) => {
  if (event.target === palette) palette.close();
});

document.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-copy-target]");
  if (!button) return;
  const target = document.getElementById(button.dataset.copyTarget);
  if (!target) return;
  try {
    await navigator.clipboard.writeText(target.value || target.textContent || "");
    button.textContent = "已复制";
  } catch (_) {
    target.select?.();
    document.execCommand("copy");
    button.textContent = "已复制";
  }
});
