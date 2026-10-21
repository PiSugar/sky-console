(() => {
  const panel = document.querySelector("#settings-panel");
  const feedback = document.querySelector("#settings-feedback");
  const retry = document.querySelector("#settings-retry");
  const switches = [...panel.querySelectorAll('input[role="switch"]')];
  let values = null;
  let revision = -1;
  let editable = false;
  let busy = false;
  let opener = null;
  let loadRequest = 0;

  function render() {
    switches.forEach((input) => {
      input.checked = Boolean(values?.[input.name]);
      input.disabled = busy || !editable || !values;
    });
    document.querySelector("#settings-llm-note").hidden = !values || values.dialogue_enabled;
    panel.setAttribute("aria-busy", String(busy));
  }

  function apply(data) {
    if (!data?.features || !Number.isInteger(data.revision) || data.revision < revision) return;
    values = data.features;
    revision = data.revision;
    if (typeof data.editable === "boolean") editable = data.editable;
    render();
  }

  async function load() {
    const request = ++loadRequest;
    busy = true;
    retry.hidden = true;
    feedback.textContent = "Loading settings…";
    render();
    try {
      const response = await fetch("/api/v1/settings", { cache: "no-store" });
      if (!response.ok) throw new Error("Settings could not be loaded.");
      const data = await response.json();
      if (request !== loadRequest) return;
      apply(data);
      feedback.textContent = editable ? "Changes are saved automatically." : "View only. Open Settings on the device to make changes.";
    } catch (error) {
      if (request !== loadRequest) return;
      editable = false;
      feedback.textContent = error instanceof TypeError ? "Cannot reach this device. Check the connection and retry." : error.message;
      retry.hidden = false;
    } finally {
      if (request === loadRequest) {
        busy = false;
        render();
      }
    }
  }

  switches.forEach((input) => input.addEventListener("change", async () => {
    const change = { [input.name]: input.checked };
    busy = true;
    ++loadRequest;
    retry.hidden = true;
    feedback.textContent = "Saving…";
    render();
    try {
      const response = await fetch("/api/v1/settings", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(change),
      });
      if (!response.ok) throw new Error(response.status === 403
        ? "Open Settings on the device to make changes."
        : "Settings could not be saved. Please retry.");
      apply(await response.json());
      feedback.textContent = "Saved on this device.";
    } catch (error) {
      feedback.textContent = error instanceof TypeError
        ? "Save could not be confirmed. Check the connection and retry to see the saved settings."
        : error.message;
      retry.hidden = false;
    } finally {
      busy = false;
      render();
      if (panel.open) input.focus();
    }
  }));

  document.querySelectorAll(".settings-open").forEach((button) => button.addEventListener("click", () => {
    opener = button;
    panel.showModal();
    if (!busy) load();
  }));
  document.querySelector("#settings-close").addEventListener("click", () => panel.close());
  panel.addEventListener("close", () => opener?.focus());
  panel.addEventListener("keydown", (event) => {
    if (event.key === "Escape") event.stopPropagation();
  });
  panel.addEventListener("click", (event) => {
    const bounds = panel.getBoundingClientRect();
    if (event.target === panel && (event.clientX < bounds.left || event.clientX > bounds.right
      || event.clientY < bounds.top || event.clientY > bounds.bottom)) panel.close();
  });
  retry.addEventListener("click", load);
  window.skyTraceSettings = {
    apply,
    isOpen: () => panel.open,
    enabled: (name) => values?.[name] === true,
    reconnect: () => { revision = -1; if (!busy) load(); },
  };
  load();
})();
