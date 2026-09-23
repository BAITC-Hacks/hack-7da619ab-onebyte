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
const summaryText = document.getElementById("summary-text");
const summaryEmpty = document.getElementById("summary-empty");
const tasksBody = document.getElementById("tasks-body");
const analysisNote = document.getElementById("analysis-note");
const exportButton = document.getElementById("export-docx");
const exportStatus = document.getElementById("export-status");
const retryAnalysis = document.getElementById("retry-analysis");
let currentTranscript = null;
let exporting = false;

function emptyTasks(message) {
  tasksBody.replaceChildren();
  const row = document.createElement("tr");
  const cell = document.createElement("td");
  cell.colSpan = 4;
  cell.className = "table-empty";
  cell.textContent = message;
  row.appendChild(cell);
  tasksBody.appendChild(row);
}

function clearAnalysis() {
  currentTranscript = null;
  summaryText.textContent = "";
  summaryText.hidden = true;
  summaryEmpty.hidden = false;
  analysisNote.hidden = true;
  exportButton.disabled = true;
  retryAnalysis.hidden = true;
  exportStatus.hidden = true;
  emptyTasks("Загрузите и обработайте запись, чтобы выделить поручения.");
}

async function readResponse(response, fallback) {
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new Error(typeof data?.detail === "string" ? data.detail : fallback);
  return data;
}

async function analyzeCurrentTranscript() {
  retryAnalysis.hidden = true;
  status.textContent = "Формируем саммари и поручения...";
  status.hidden = false;
  try {
    const response = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ transcript: currentTranscript }),
    });
    const result = await readResponse(response, "Не удалось проанализировать транскрипт.");
    if (typeof result?.summary !== "string" || !Array.isArray(result?.tasks)) {
      throw new Error("Сервер вернул некорректный результат анализа.");
    }
    summaryText.textContent = result.summary;
    summaryText.hidden = false;
    summaryEmpty.hidden = true;
    tasksBody.replaceChildren();
    for (const task of result.tasks) {
      const row = document.createElement("tr");
      for (const value of [task.assignee || "Не определён", task.description, task.deadline || "Не определён", "В работе"]) {
        const cell = document.createElement("td");
        cell.textContent = value;
        if (value === "Не определён") cell.className = "undetermined";
        row.appendChild(cell);
      }
      tasksBody.appendChild(row);
    }
    if (!result.tasks.length) emptyTasks("Явные поручения не найдены. Проверьте полный транскрипт.");
    analysisNote.textContent = result.analysis_note;
    analysisNote.hidden = false;
    exportButton.disabled = exporting;
    activateTab(document.getElementById("tab-summary"));
    status.textContent = "Готово: транскрипт, саммари и поручения. Протокол можно скачать в DOCX.";
  } catch (exception) {
    summaryText.textContent = "Анализ не завершён. Транскрипт доступен в своей вкладке.";
    summaryText.hidden = false;
    summaryEmpty.hidden = true;
    emptyTasks("Не удалось выделить поручения. Повторите анализ.");
    status.textContent = "Транскрипт готов. Анализ не выполнен: " + (exception instanceof TypeError ? "нет связи с локальным сервером." : exception.message);
    retryAnalysis.hidden = false;
  }
}

function setProcessing(value) {
  processing = value;
  processButton.disabled = value || !recording;
  input.disabled = value;
  document.getElementById("remove-file").disabled = value;
  retryAnalysis.disabled = value;
}

function resetSelection() {
  if (processing) return;
  clearAnalysis();
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
  setProcessing(true);
  clearAnalysis();
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
    currentTranscript = result.transcript;
    activateTab(document.getElementById("tab-transcript"));
    await analyzeCurrentTranscript();
  } catch (exception) {
    status.hidden = true;
    error.textContent = exception instanceof TypeError
      ? "Нет связи с локальным сервером. Убедитесь, что приложение запущено, и повторите попытку."
      : exception.message;
    error.hidden = false;
  } finally {
    setProcessing(false);
  }
});

retryAnalysis.addEventListener("click", async () => {
  if (processing || currentTranscript === null) return;
  setProcessing(true);
  try {
    await analyzeCurrentTranscript();
  } finally {
    setProcessing(false);
  }
});

exportButton.addEventListener("click", async () => {
  if (exporting || processing || currentTranscript === null) return;
  const transcript = currentTranscript;
  exporting = true;
  exportButton.disabled = true;
  exportStatus.textContent = "Создаём DOCX...";
  exportStatus.hidden = false;
  try {
    const response = await fetch("/api/export/docx", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ transcript }),
    });
    if (!response.ok) await readResponse(response, "Не удалось создать DOCX.");
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "meeting-ai-protocol.docx";
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    if (currentTranscript === transcript) exportStatus.textContent = "Протокол DOCX подготовлен для скачивания.";
  } catch (exception) {
    if (currentTranscript === transcript) exportStatus.textContent = exception instanceof TypeError
      ? "Нет связи с сервером. Повторите экспорт DOCX."
      : exception.message;
  } finally {
    exporting = false;
    exportButton.disabled = processing || currentTranscript === null || !retryAnalysis.hidden;
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
