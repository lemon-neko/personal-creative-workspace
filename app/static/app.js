document.addEventListener("htmx:configRequest", (event) => {
  for (const [key, value] of Object.entries(event.detail.parameters)) {
    if (value === "") {
      delete event.detail.parameters[key];
    }
  }
});
