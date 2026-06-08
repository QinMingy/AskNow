const API_BASE_URL = "http://127.0.0.1:8010";
const REQUIRED_API_VERSION = "0.3.0";
const acceptedExtensions = [".mp3", ".wav", ".m4a", ".mp4"];
const assistActions = ["explain", "conflict", "question", "catchup", "actions"];

const demoSegments = [
  {
    id: 1,
    start: 0,
    end: 8,
    speaker: "Speaker A",
    text: "上传课堂或会议录音后，带时间戳的字幕会出现在这里。",
  },
  {
    id: 2,
    start: 8,
    end: 15,
    speaker: "Speaker B",
    text: "第一阶段使用模拟说话人，后续会接入真正的说话人分离。",
  },
];

let selectedFile = null;
let latestResult = null;
let inputMode = "file";

const elements = {
  audioInput: document.querySelector("#audioInput"),
  browserCookieSelect: document.querySelector("#browserCookieSelect"),
  durationLabel: document.querySelector("#durationLabel"),
  errorMessage: document.querySelector("#errorMessage"),
  fileModeButton: document.querySelector("#fileModeButton"),
  fileMeta: document.querySelector("#fileMeta"),
  fileName: document.querySelector("#fileName"),
  focusMeterLast: document.querySelector("#focusMeterLast"),
  focusSummary: document.querySelector("#focusSummary"),
  focusTitle: document.querySelector("#focusTitle"),
  noticeMessage: document.querySelector("#noticeMessage"),
  pickFileButton: document.querySelector("#pickFileButton"),
  statusDot: document.querySelector("#statusDot"),
  statusText: document.querySelector("#statusText"),
  topicStatus: document.querySelector("#topicStatus"),
  transcribeButton: document.querySelector("#transcribeButton"),
  transcriptList: document.querySelector("#transcriptList"),
  uploadZone: document.querySelector("#uploadZone"),
  urlModeButton: document.querySelector("#urlModeButton"),
  urlTranscribeButton: document.querySelector("#urlTranscribeButton"),
  urlZone: document.querySelector("#urlZone"),
  videoUrlInput: document.querySelector("#videoUrlInput"),
};

function formatTimestamp(seconds) {
  const safeSeconds = Math.max(0, Math.floor(Number(seconds) || 0));
  const minutes = Math.floor(safeSeconds / 60);
  const remaining = safeSeconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(remaining).padStart(2, "0")}`;
}

function setState(state) {
  const labels = {
    idle: "等待音频",
    uploading: "正在上传",
    transcribing: "正在转写",
    complete: "转写完成",
    error: "转写失败",
  };

  elements.statusText.textContent = labels[state] || labels.idle;
  elements.statusDot.className = `status-dot status-${state}`;
  const isBusy = state === "uploading" || state === "transcribing";
  elements.transcribeButton.disabled = isBusy;
  elements.urlTranscribeButton.disabled = isBusy;

  if (state === "uploading" || state === "transcribing") {
    elements.transcribeButton.textContent = "处理中…";
    elements.urlTranscribeButton.textContent = "处理中…";
  } else if (selectedFile) {
    elements.transcribeButton.textContent = "开始转写";
    elements.urlTranscribeButton.textContent = "解析并转写";
  } else {
    elements.transcribeButton.textContent = "选择音频";
    elements.urlTranscribeButton.textContent = "解析并转写";
  }
}

function showError(message) {
  elements.errorMessage.hidden = !message;
  elements.errorMessage.textContent = message || "";
}

function showNotice(message) {
  elements.noticeMessage.hidden = !message;
  elements.noticeMessage.textContent = message || "";
}

async function checkBackendCapabilities() {
  try {
    const response = await fetch(`${API_BASE_URL}/health`, { cache: "no-store" });
    if (!response.ok) return;

    const health = await response.json();
    const supportsBrowserCookies =
      health.api_version === REQUIRED_API_VERSION &&
      Array.isArray(health.browser_cookie_sources) &&
      health.browser_cookie_sources.includes("chrome");

    if (!supportsBrowserCookies) {
      showError(
        `当前运行的后端版本过旧（检测到 ${health.api_version || "未知版本"}）。` +
          "请运行 stop_demo.bat 后再运行 start_demo.bat，确认新版后端运行在 8010 端口。",
      );
    }
  } catch {
    // The normal upload flow will show a useful connection error when needed.
  }
}

function validateFile(file) {
  const extension = `.${file.name.split(".").pop().toLowerCase()}`;
  if (!acceptedExtensions.includes(extension)) {
    showError(`暂不支持 ${extension} 文件，请上传 MP3、WAV、M4A 或 MP4。`);
    setState("error");
    return false;
  }
  return true;
}

function selectFile(file) {
  if (!validateFile(file)) return;

  selectedFile = file;
  latestResult = null;
  showError("");
  showNotice("");
  setState("idle");

  elements.fileName.textContent = file.name;
  elements.fileMeta.textContent = `${(file.size / 1024 / 1024).toFixed(1)} MB · 已准备转写`;
  elements.durationLabel.textContent = "等待转写";
  renderDemo();
}

async function transcribeAudio(file) {
  const body = new FormData();
  body.append("file", file);

  const response = await fetch(`${API_BASE_URL}/api/transcribe`, {
    method: "POST",
    body,
  });

  if (!response.ok) {
    let message = "转写失败，请确认后端服务和 GPU 环境正常。";
    try {
      const error = await response.json();
      message = error.detail || message;
    } catch {
      // Keep fallback message for non-JSON server errors.
    }
    throw new Error(message);
  }

  return response.json();
}

async function transcribeVideoUrl(url) {
  const browser = elements.browserCookieSelect.value || null;
  const response = await fetch(`${API_BASE_URL}/api/transcribe-url`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ url, browser }),
  });

  if (!response.ok) {
    let message = "链接解析或转写失败，请确认链接可访问。";
    try {
      const error = await response.json();
      message = error.detail || message;
    } catch {
      // Keep fallback message for non-JSON server errors.
    }
    throw new Error(message);
  }

  return response.json();
}

async function requestAssistance(action) {
  const response = await fetch(`${API_BASE_URL}/api/assist`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      action,
      window_seconds: action === "catchup" ? 180 : 60,
      segments: latestResult?.segments || [],
    }),
  });

  if (!response.ok) {
    let message = "理解辅助请求失败，请确认后端服务正常。";
    try {
      const error = await response.json();
      message = error.detail || message;
    } catch {
      // Keep fallback message for non-JSON server errors.
    }
    throw new Error(message);
  }

  return response.json();
}

function renderAssistance(result) {
  elements.noticeMessage.hidden = false;
  elements.noticeMessage.innerHTML = "";

  const title = document.createElement("strong");
  title.className = "assist-result-title";
  title.textContent = result.title;

  const summary = document.createElement("p");
  summary.className = "assist-result-summary";
  summary.textContent = result.summary;

  const list = document.createElement("ul");
  list.className = "assist-result-list";
  (result.bullets || []).forEach((bullet) => {
    const item = document.createElement("li");
    item.textContent = bullet;
    list.append(item);
  });

  const caution = document.createElement("small");
  caution.className = "assist-result-caution";
  caution.textContent = result.caution;

  elements.noticeMessage.append(title, summary, list, caution);
}

async function handleAssistance(action, button) {
  if (!latestResult?.segments?.length) {
    showNotice("请先完成一次音频或视频转写，再使用理解辅助。");
    return;
  }

  showError("");
  showNotice("正在整理最近的讨论上下文...");
  button.disabled = true;

  try {
    const result = await requestAssistance(action);
    renderAssistance(result);
  } catch (error) {
    showNotice("");
    showError(error instanceof Error ? error.message : "理解辅助请求失败，请稍后再试。");
  } finally {
    button.disabled = false;
  }
}

async function handleTranscribe() {
  if (!selectedFile) {
    elements.audioInput.click();
    return;
  }

  showError("");
  showNotice("");
  setState("uploading");

  try {
    window.setTimeout(() => setState("transcribing"), 300);
    latestResult = await transcribeAudio(selectedFile);
    renderResult(latestResult);
    setState("complete");
  } catch (error) {
    showError(error instanceof Error ? error.message : "转写失败，请稍后再试。");
    setState("error");
  }
}

async function handleUrlTranscribe() {
  const url = elements.videoUrlInput.value.trim();
  if (!url) {
    showError("请先粘贴 B 站或 YouTube 视频链接。");
    setState("error");
    return;
  }

  showError("");
  showNotice("");
  setState("uploading");

  try {
    window.setTimeout(() => setState("transcribing"), 300);
    latestResult = await transcribeVideoUrl(url);
    renderResult(latestResult);
    setState("complete");
  } catch (error) {
    showError(error instanceof Error ? error.message : "链接转写失败，请稍后再试。");
    setState("error");
  }
}

function setInputMode(nextMode) {
  inputMode = nextMode;
  const isFileMode = inputMode === "file";

  elements.uploadZone.hidden = !isFileMode;
  elements.urlZone.hidden = isFileMode;
  elements.fileModeButton.classList.toggle("active", isFileMode);
  elements.urlModeButton.classList.toggle("active", !isFileMode);

  showError("");
  showNotice("");
  setState("idle");
}

function renderTranscript(segments, isDemo) {
  elements.transcriptList.innerHTML = "";

  if (isDemo) {
    const label = document.createElement("p");
    label.className = "demo-label";
    label.textContent = "界面预览 · 上传后替换为真实字幕";
    elements.transcriptList.append(label);
  }

  segments.forEach((segment) => {
    const item = document.createElement("div");
    item.className = "transcript-item";

    const meta = document.createElement("div");
    meta.className = "transcript-meta";

    const time = document.createElement("span");
    time.textContent = formatTimestamp(segment.start);

    const speaker = document.createElement("span");
    speaker.className = `speaker-chip ${String(segment.speaker).endsWith("B") ? "speaker-b" : ""}`;
    speaker.textContent = segment.speaker;

    const text = document.createElement("p");
    text.textContent = segment.text;

    meta.append(time, speaker);
    item.append(meta, text);
    elements.transcriptList.append(item);
  });
}

function renderDemo() {
  renderTranscript(demoSegments, true);
  elements.focusTitle.textContent = "准备进入讨论";
  elements.focusSummary.textContent = "等待上传录音。转写完成后，这里会从开头几段内容中提取一条基础主题提示。";
  elements.topicStatus.textContent = "等待开始";
  elements.focusMeterLast.classList.remove("active");
}

function renderResult(result) {
  const segments = Array.isArray(result.segments) ? result.segments : [];
  renderTranscript(segments, false);

  const summary = segments
    .slice(0, 3)
    .map((segment) => segment.text)
    .join(" ");

  const sourceLabel = result.source?.provider ? ` · ${result.source.provider}` : "";
  elements.durationLabel.textContent = `${formatTimestamp(result.duration)} · ${result.language || "zh"}${sourceLabel}`;
  elements.focusTitle.textContent = result.source?.title || "从录音开头提取的主题线索";
  elements.focusSummary.textContent = summary.length > 150 ? `${summary.slice(0, 150)}…` : summary || "未识别到可摘要的文本。";
  elements.topicStatus.textContent = "已捕获初始上下文";
  elements.focusMeterLast.classList.add("active");
}

elements.pickFileButton.addEventListener("click", () => elements.audioInput.click());
elements.transcribeButton.addEventListener("click", handleTranscribe);
elements.urlTranscribeButton.addEventListener("click", handleUrlTranscribe);
elements.fileModeButton.addEventListener("click", () => setInputMode("file"));
elements.urlModeButton.addEventListener("click", () => setInputMode("url"));
elements.audioInput.addEventListener("change", (event) => {
  const file = event.target.files && event.target.files[0];
  if (file) selectFile(file);
});

elements.videoUrlInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    handleUrlTranscribe();
  }
});

elements.uploadZone.addEventListener("dragover", (event) => {
  event.preventDefault();
  elements.uploadZone.classList.add("is-dragging");
});

elements.uploadZone.addEventListener("dragleave", () => {
  elements.uploadZone.classList.remove("is-dragging");
});

elements.uploadZone.addEventListener("drop", (event) => {
  event.preventDefault();
  elements.uploadZone.classList.remove("is-dragging");
  const file = event.dataTransfer.files && event.dataTransfer.files[0];
  if (file) selectFile(file);
});

document.querySelectorAll(".action-button").forEach((button, index) => {
  const action = assistActions[index];
  button.dataset.action = action;
  button.addEventListener("click", () => {
    handleAssistance(action, button);
  });
});

renderDemo();
checkBackendCapabilities();
