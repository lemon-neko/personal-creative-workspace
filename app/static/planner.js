(() => {
  const selector = "[data-drop-day], [data-drop-clear], [data-drop-complete]";
  const view = () => document.querySelector(".planner");
  let source = null;
  let hover = null;
  let drag = null;
  let lastDrop = 0;
  const findTarget = (element) => element?.closest(selector);

  function highlight(target) {
    hover?.classList.remove("drop-target");
    hover = target;
    hover?.classList.add("drop-target");
  }

  function begin(grip) {
    source = grip.closest(".board-event");
    source.classList.add("drag-source");
    view().classList.add("planner-dragging");
    view().querySelectorAll("[data-drop-clear], [data-drop-complete]").forEach((target) => {
      target.hidden = false;
    });
  }

  function end() {
    highlight(null);
    source?.classList.remove("drag-source");
    view()?.classList.remove("planner-dragging");
    view()?.querySelectorAll("[data-drop-clear], [data-drop-complete]").forEach((target) => {
      target.hidden = true;
    });
    source = null;
  }

  function drop(target) {
    const row = source;
    end();
    if (!target || !row) return;
    if ("dropComplete" in target.dataset) {
      row.querySelector("form[data-desk-action=toggle]").requestSubmit();
      return;
    }
    const form = row.querySelector("form.planner-move-form");
    if ("dropClear" in target.dataset) {
      row.querySelector("form[data-desk-action=move]:not(.planner-move-form)")?.requestSubmit();
      return;
    }
    form.elements.start_on.value = target.dataset.dropDay;
    if ("dropTime" in target.dataset) form.elements.start_time.value = target.dataset.dropTime;
    form.requestSubmit();
  }

  document.addEventListener("pointerdown", (event) => {
    const grip = event.target.closest("[data-planner-grip]");
    if (!grip || event.button !== 0 || view().hasAttribute("aria-busy")) return;
    grip.setPointerCapture(event.pointerId);
    drag = {grip, id: event.pointerId, x: event.clientX, y: event.clientY};
  });
  document.addEventListener("pointermove", (event) => {
    if (drag?.id !== event.pointerId) return;
    if (!source && Math.hypot(event.clientX - drag.x, event.clientY - drag.y) < 8) return;
    if (!source) begin(drag.grip);
    const target = document.elementFromPoint(event.clientX, event.clientY);
    const scroller = target?.closest(".planner-scroll");
    if (scroller) {
      const bounds = scroller.getBoundingClientRect();
      if (event.clientY - bounds.top < 16) scroller.scrollTop -= 18;
      if (bounds.bottom - event.clientY < 16) scroller.scrollTop += 18;
    }
    highlight(findTarget(target));
  });
  document.addEventListener("pointerup", (event) => {
    if (drag?.id !== event.pointerId) return;
    drag = null;
    if (source) {
      lastDrop = performance.now();
      drop(findTarget(document.elementFromPoint(event.clientX, event.clientY)));
    }
  });
  document.addEventListener("pointercancel", () => {
    drag = null;
    end();
  });
  document.addEventListener("click", (event) => {
    const grip = event.target.closest("[data-planner-grip]");
    if (grip && !view().hasAttribute("aria-busy") && (!lastDrop || performance.now() - lastDrop > 250)) {
      const details = grip.closest(".board-event").querySelector("details");
      details.open = true;
      details.querySelector("[name=start_on]").focus();
    }
    const pick = event.target.closest("[data-pick-time]");
    if (pick) {
      const form = view().querySelector(".board-add");
      form.querySelector("details").open = true;
      form.elements.start_time.value = pick.dataset.pickTime;
      form.elements.title.focus();
    }
  });

  function updateCountdowns() {
    view()?.querySelectorAll("[data-countdown]").forEach((time) => {
      const remaining = Date.parse(time.dateTime) - Date.now();
      const start = time.dataset.countdown === "start";
      if (start && remaining <= 0) {
        time.textContent = "已到计划时间";
        return;
      }
      const minutes = Math.floor(Math.abs(remaining) / 60000);
      const days = Math.floor(minutes / 1440);
      const hours = Math.floor(minutes / 60) % 24;
      const rest = minutes % 60;
      const duration = days ? `${days}天${hours}小时` : hours ? `${hours}小时${rest}分` : rest ? `${rest}分钟` : "不到 1 分钟";
      time.textContent = (start ? "开始 · 剩余 " : remaining < 0 ? "逾期 " : "截止 · 剩余 ") + duration;
      time.classList.toggle("is-overdue", remaining < 0);
    });
  }

  if (view()) {
    const scroll = view().querySelector(".planner-scroll");
    const start = scroll.querySelector("[data-first-event]") || scroll.querySelector("[data-drop-time='08:00']");
    if (start) scroll.scrollTop = start.offsetTop;
    updateCountdowns();
    document.addEventListener("desk:updated", updateCountdowns);
    window.setInterval(updateCountdowns, 30000);
  }
})();
