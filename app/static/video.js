(() => {
  const renumber = (list) => {
    list.querySelectorAll("[data-scene]").forEach((scene, index) => {
      const number = scene.querySelector("[data-scene-number]");
      if (number) number.textContent = String(index + 1);
    });
  };

  document.querySelectorAll("[data-storyboard-form]").forEach((form) => {
    const list = form.querySelector("[data-scene-list]");
    const add = form.querySelector("[data-add-scene]");
    if (!list || !add) return;

    add.addEventListener("click", () => {
      const source = list.querySelector("[data-scene]:last-child");
      if (!source || list.querySelectorAll("[data-scene]").length >= 40) return;
      const scene = source.cloneNode(true);
      scene.querySelectorAll("textarea, input").forEach((field) => {
        if (field.name === "scene_duration") field.value = "6";
        else field.value = "";
      });
      list.append(scene);
      renumber(list);
      scene.querySelector("textarea")?.focus();
    });

    list.addEventListener("click", (event) => {
      const button = event.target.closest("[data-remove-scene]");
      if (!button) return;
      const scenes = list.querySelectorAll("[data-scene]");
      if (scenes.length === 1) return;
      button.closest("[data-scene]")?.remove();
      renumber(list);
    });
  });
})();
