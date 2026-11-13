(() => {
  const desk = () => document.querySelector("#daily-desk");
  const live = document.querySelector("[data-desk-live]");
  const fieldNames = ["title", "deliverable_id", "due_on", "status", "start_time"];
  const editor = ".desk-row-details";
  const row = (id) => document.getElementById("event-" + id);
  const focus = (target) => target?.focus({ preventScroll: true });
  let saving = false;

  function keepInputs(oldForm, newForm) {
    if (!oldForm || !newForm) return;
    for (const name of fieldNames) {
      if (oldForm.elements[name] && newForm.elements[name]) {
        newForm.elements[name].value = oldForm.elements[name].value;
      }
    }
  }

  desk()?.parentElement.addEventListener("submit", async (event) => {
    const form = event.target;
    const action = form.dataset.deskAction;
    if (!action || !window.fetch || !window.FormData) return;
    event.preventDefault();
    if (saving) return;

    const current = desk();
    const id = form.dataset.eventId;
    const active = document.activeElement;
    const nextRow = row(id)?.nextElementSibling?.id;
    const data = new URLSearchParams(new FormData(form));
    current.setAttribute("aria-busy", "true");
    saving = true;

    try {
      const response = await fetch(form.action, {
        method: "POST",
        body: data,
        headers: { "X-Workspace-Board": "1" },
      });
      if (!response.ok && response.status !== 422) throw new Error();
      const html = new DOMParser().parseFromString(await response.text(), "text/html");
      const updated = html.querySelector("#daily-desk");
      if (!updated) throw new Error();
      const oldAdd = current.querySelector(".board-add");
      const newAdd = updated.querySelector(".board-add");
      if (oldAdd && newAdd && (action !== "add" || oldAdd.elements.title.value !== data.get("title"))) {
        keepInputs(oldAdd, newAdd);
        newAdd.querySelector("details").open = oldAdd.querySelector("details").open;
      }
      if (current.querySelector(".desk-done[open]") && updated.querySelector(".desk-done")) {
        updated.querySelector(".desk-done").open = true;
      }
      for (const oldDetails of current.querySelectorAll(editor + "[open]")) {
        const oldRow = oldDetails.closest(".board-event");
        if (form.closest(".board-event") === oldRow && action === "edit") continue;
        const newDetails = updated.querySelector("#" + oldRow.id + " " + editor);
        if (!newDetails) continue;
        newDetails.open = true;
        keepInputs(oldDetails.querySelector("form"), newDetails.querySelector("form"));
      }
      const scrollTop = current.querySelector(".planner-scroll")?.scrollTop;
      current.replaceWith(updated);
      if (scrollTop !== undefined) updated.querySelector(".planner-scroll").scrollTop = scrollTop;
      document.dispatchEvent(new Event("desk:updated"));
      if (live) live.textContent = updated.dataset.message;
      const targetRow = id && row(id);
      const visibleRow = targetRow && !targetRow.closest("details:not([open])") ? targetRow : null;
      if (action === "add") {
        focus(updated.querySelector("#new-event"));
      } else if (!response.ok) {
        focus(visibleRow?.querySelector(editor + " input:not([type=hidden]), " + editor + " summary") || updated.querySelector("nav [aria-current]"));
      } else if (action === "edit") {
        focus(visibleRow?.querySelector(editor + " summary") || updated.querySelector("nav [aria-current]"));
      } else {
        focus(visibleRow?.querySelector(".desk-check") || (nextRow && document.getElementById(nextRow)?.querySelector(".desk-check")) ||
          updated.querySelector("#desk-undo") || updated.querySelector("#new-event") || updated.querySelector("nav [aria-current]"));
      }
    } catch (_) {
      const feedback = current.querySelector("#desk-feedback");
      const error = document.createElement("p");
      error.className = "message error";
      error.setAttribute("role", "alert");
      error.textContent = "未能确认保存。请检查连接后刷新，确认待办状态。";
      feedback?.replaceChildren(error);
      focus(active);
    } finally {
      current.removeAttribute("aria-busy");
      saving = false;
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.defaultPrevented || event.isComposing || document.querySelector("dialog[open]")) return;
    if (event.altKey && !event.metaKey && !event.ctrlKey && event.code === "KeyN") {
      const input = document.getElementById("new-event");
      if (!input) return;
      event.preventDefault();
      input.focus();
    }
    if (["ArrowDown", "ArrowUp"].includes(event.key) && event.target.matches(".desk-check")) {
      const checks = [...desk().querySelectorAll(".desk-check")].filter((control) => !control.closest("details:not([open])"));
      const next = checks[checks.indexOf(event.target) + (event.key === "ArrowDown" ? 1 : -1)];
      if (next) {
        event.preventDefault();
        next.focus();
      }
    }
    if (event.key === "Escape") {
      const details = event.target.closest(editor + "[open]");
      if (!details) return;
      details.open = false;
      details.querySelector("summary")?.focus();
    }
  });
})();
