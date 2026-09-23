"use strict";

const input = document.getElementById("recording");
const dropZone = document.getElementById("drop-zone");
const selectedFile = document.getElementById("selected-file");
const processButton = document.getElementById("process");
const error = document.getElementById("file-error");
const status = document.getElementById("processing-status");
let recording = null;

function resetSelection() {
  recording = null;
  input.value = "";
  selectedFile.hidden = true;
  processButton.disabled = true;
  status.hidden = true;
  error.hidden = true;
  document.getElementById("file-name").textContent = "";
  document.getElementById("file-size").textContent = "";
}

function selectFile(files) {
  resetSelection();
  if (files.length !== 1) {
    error.textContent = "Выберите одну запись совещания.";
    error.hidden = false;
    return;
  }
  const file = files[0];
  if (!/\.(mp3|wav|m4a|mp4)$/i.test(file.name) || file.size === 0) {
    error.textContent = "Выберите непустой файл в формате MP3, WAV, M4A или MP4.";
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
// Files stay in browser memory: no upload, storage, or external requests.
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
processButton.addEventListener("click", () => {
  if (!recording) return;
  status.textContent = "Запись выбрана. Обработка пока не подключена: это прототип интерфейса. Файл не отправляется на сервер или во внешние сервисы; результаты не создаются.";
  status.hidden = false;
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
