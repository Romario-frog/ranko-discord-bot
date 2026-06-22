(() => {
  const form = document.getElementById("settingsForm");
  const status = document.getElementById("autosaveStatus");
  if (!form || !status) return;

  let timer = null;
  let saving = false;

  function setStatus(text, cls = "") {
    status.textContent = text;
    status.className = "autosave-status " + cls;
  }

  async function save() {
    if (saving) return;
    saving = true;
    setStatus("Сохраняю...", "saving");

    try {
      const response = await fetch("/dashboard/autosave", {
        method: "POST",
        body: new FormData(form),
      });

      const data = await response.json();
      if (data.ok) {
        setStatus("✅ Автосохранено", "ok");
      } else {
        setStatus("⚠️ Не удалось сохранить", "bad");
      }
    } catch (e) {
      setStatus("⚠️ Ошибка автосохранения", "bad");
    } finally {
      saving = false;
    }
  }

  function scheduleSave() {
    setStatus("Есть изменения...", "pending");
    clearTimeout(timer);
    timer = setTimeout(save, 900);
  }

  form.querySelectorAll("input, textarea, select").forEach((el) => {
    el.addEventListener("change", scheduleSave);
    el.addEventListener("input", scheduleSave);
  });
})();
