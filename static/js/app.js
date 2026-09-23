"use strict";

const input = document.getElementById("recording");
const dropZone = document.getElementById("drop-zone");
const selectedFile = document.getElementById("selected-file");
const processButton = document.getElementById("process");
const error = document.getElementById("file-error");
const status = document.getElementById("processing-status");
let recording = null;
let processing = false;
const transcriptText = document.getElementById("transcript-text");
const transcriptEmpty = document.getElementById("transcript-empty");

function resetSelection() {
  if (processing) return;
  recording = null;
  input.value = "";
  selectedFile.hidden = true;
  processButton.disabled = true;
  status.hidden = true;
  error.hidden = true;
  transcriptText.textContent = "";
  transcriptText.hidden = true;
  transcriptEmpty.hidden = false;
  document.getElementById("file-name").textContent = "";
  document.getElementById("file-size").textContent = "";
}

function selectFile(files) {
  if (processing) return;
  resetSelection();
  if (files.length !== 1) {
    error.textContent = "Выберите одну запись совещания.";
    error.hidden = false;
    return;
  }
  const file = files[0];
  if (!/\.(mp3|wav|m4a)$/i.test(file.name) || file.size === 0) {
    error.textContent = "Выберите непустой файл в формате MP3, WAV или M4A.";
    error.hidden = false;
    return;
  }
  recording = file;
  document.getElementById("file-name").textContent = file.name;
  document.getElementById("file-size").textContent = `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 }).format(file.size / 1024 / 1024)} МБ · выбран на устройстве`;
  selectedFile.hidden = false;
  processButton.disabled = false;
}

input.addEventListener("change", () => {
  const files = Array.from(input.files);
  if (files.length) selectFile(files);
});
document.getElementById("remove-file").addEventListener("click", () => {
  resetSelection();
  input.focus();
});
// Upload only to the same local FastAPI server.
window.addEventListener("dragover", (event) => event.preventDefault());
window.addEventListener("drop", (event) => event.preventDefault());
dropZone.addEventListener("dragover", (event) => {
  event.preventDefault();
  dropZone.classList.add("drag-over");
});
dropZone.addEventListener("dragleave", (event) => {
  if (!dropZone.contains(event.relatedTarget)) dropZone.classList.remove("drag-over");
});
dropZone.addEventListener("drop", (event) => {
  event.preventDefault();
  dropZone.classList.remove("drag-over");
  selectFile(Array.from(event.dataTransfer.files));
});
processButton.addEventListener("click", async () => {
  if (!recording || processing) return;
  processing = true;
  processButton.disabled = true;
  input.disabled = true;
  document.getElementById("remove-file").disabled = true;
  error.hidden = true;
  transcriptText.textContent = "";
  transcriptText.hidden = true;
  transcriptEmpty.hidden = false;
  status.textContent = "Обрабатываем запись...";
  status.hidden = false;
  try {
    const form = new FormData();
    form.append("file", recording);
    const response = await fetch("/api/transcribe", { method: "POST", body: form });
    const result = await response.json().catch(() => null);
    if (!response.ok) {
      throw new Error(typeof result?.detail === "string" ? result.detail : "Локальный сервер не смог обработать запись. Повторите попытку.");
    }
    if (typeof result?.transcript !== "string") {
      throw new Error("Сервер вернул некорректный результат. Повторите попытку.");
    }
    transcriptText.textContent = result.transcript || "Речь в записи не обнаружена.";
    transcriptText.hidden = false;
    transcriptEmpty.hidden = true;
    activateTab(document.getElementById("tab-transcript"));
    status.textContent = "Обработка завершена.";
  } catch (exception) {
    status.hidden = true;
    error.textContent = exception instanceof TypeError
      ? "Нет связи с локальным сервером. Убедитесь, что приложение запущено, и повторите попытку."
      : exception.message;
    error.hidden = false;
  } finally {
    processing = false;
    processButton.disabled = !recording;
    input.disabled = false;
    document.getElementById("remove-file").disabled = false;
  }
});

const tabs = Array.from(document.querySelectorAll('[role="tab"]'));
function activateTab(activeTab) {
  tabs.forEach((tab) => {
    const active = tab === activeTab;
    tab.setAttribute("aria-selected", String(active));
    tab.tabIndex = active ? 0 : -1;
    document.getElementById(tab.getAttribute("aria-controls")).hidden = !active;
  });
}
tabs.forEach((tab, index) => {
  tab.addEventListener("click", () => activateTab(tab));
  tab.addEventListener("keydown", (event) => {
    let next;
    if (event.key === "ArrowRight") next = (index + 1) % tabs.length;
    if (event.key === "ArrowLeft") next = (index - 1 + tabs.length) % tabs.length;
    if (event.key === "Home") next = 0;
    if (event.key === "End") next = tabs.length - 1;
    if (next === undefined) return;
    event.preventDefault();
    activateTab(tabs[next]);
    tabs[next].focus();
  });
});
