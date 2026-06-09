const API_BASE_URL = "http://127.0.0.1:8010";
const REQUIRED_API_VERSION = "0.9.0";
const STREAM_CHUNK_DURATION_MS = 200;
const STREAM_TARGET_SAMPLE_RATE = 16000;
const STREAM_STOP_FLUSH_TIMEOUT_MS = 30000;
const LIVE_RENDER_INTERVAL_MS = 250;
const LIVE_TURN_GAP_SECONDS = 1.2;
const LIVE_TURN_MAX_SECONDS = 8;
const acceptedExtensions = [".mp3", ".wav", ".m4a", ".mp4"];
const assistActionLabels = {
  explain: "解释刚刚发生了什么",
  conflict: "梳理观点关系",
  question: "生成可确认的追问",
  catchup: "补上缺席内容",
  actions: "整理会后行动项",
  custom: "回答你的问题",
};
const taskStageLabels = {
  queued: "任务排队中",
  uploading: "正在上传音频",
  downloading: "正在获取视频音频",
  waiting_for_gpu: "等待 GPU 处理",
  transcribing: "正在生成字幕",
  diarizing: "正在识别说话人",
  completed: "处理完成",
  failed: "处理失败",
  cancelled: "任务已取消",
};

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
let currentTaskId = null;
let liveSocket = null;
let liveMediaStream = null;
let liveAudioContext = null;
let liveProcessorNode = null;
let liveSourceNode = null;
let liveSequence = 0;
let liveStartedAt = null;
let liveTimerHandle = null;
let liveCanSend = true;
let liveFinalSegments = [];
let livePartialSegments = [];
let liveSampleBuffers = [];
let liveSampleCount = 0;
let livePendingChunks = [];
let livePendingMs = 0;
let liveInFlightChunk = null;
let liveDrainTimer = null;
let liveRenderTimer = null;

const elements = {
  audioInput: document.querySelector("#audioInput"),
  browserCookieSelect: document.querySelector("#browserCookieSelect"),
  cancelTaskButton: document.querySelector("#cancelTaskButton"),
  customQuestionButton: document.querySelector("#customQuestionButton"),
  customQuestionForm: document.querySelector("#customQuestionForm"),
  customQuestionInput: document.querySelector("#customQuestionInput"),
  durationLabel: document.querySelector("#durationLabel"),
  errorMessage: document.querySelector("#errorMessage"),
  fileModeButton: document.querySelector("#fileModeButton"),
  fileMeta: document.querySelector("#fileMeta"),
  fileName: document.querySelector("#fileName"),
  focusMeterLast: document.querySelector("#focusMeterLast"),
  focusSummary: document.querySelector("#focusSummary"),
  focusTitle: document.querySelector("#focusTitle"),
  noticeMessage: document.querySelector("#noticeMessage"),
  liveBackpressure: document.querySelector("#liveBackpressure"),
  liveHint: document.querySelector("#liveHint"),
  liveModeButton: document.querySelector("#liveModeButton"),
  liveProcessing: document.querySelector("#liveProcessing"),
  livePulse: document.querySelector("#livePulse"),
  liveRevision: document.querySelector("#liveRevision"),
  liveStatus: document.querySelector("#liveStatus"),
  liveTimer: document.querySelector("#liveTimer"),
  liveZone: document.querySelector("#liveZone"),
  pickFileButton: document.querySelector("#pickFileButton"),
  providerStatus: document.querySelector("#providerStatus"),
  progressBar: document.querySelector("#progressBar"),
  progressLabel: document.querySelector("#progressLabel"),
  progressPercent: document.querySelector("#progressPercent"),
  statusDot: document.querySelector("#statusDot"),
  statusText: document.querySelector("#statusText"),
  startLiveButton: document.querySelector("#startLiveButton"),
  stopLiveButton: document.querySelector("#stopLiveButton"),
  taskProgress: document.querySelector("#taskProgress"),
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
    live: "实时字幕中",
  };

  elements.statusText.textContent = labels[state] || labels.idle;
  elements.statusDot.className = `status-dot status-${state}`;
  const isBusy = state === "uploading" || state === "transcribing" || state === "live";
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

function websocketUrl(path) {
  return `${API_BASE_URL.replace(/^http/, "ws")}${path}`;
}

function encodePcm16(samples) {
  const buffer = new ArrayBuffer(samples.length * 2);
  const view = new DataView(buffer);
  samples.forEach((sample, index) => {
    const clipped = Math.max(-1, Math.min(1, sample));
    view.setInt16(index * 2, clipped < 0 ? clipped * 32768 : clipped * 32767, true);
  });
  return buffer;
}

function downsampleAudio(samples, inputRate, outputRate) {
  if (inputRate === outputRate) return samples;
  const ratio = inputRate / outputRate;
  const output = new Float32Array(Math.round(samples.length / ratio));
  for (let outputIndex = 0; outputIndex < output.length; outputIndex += 1) {
    const start = Math.floor(outputIndex * ratio);
    const end = Math.min(samples.length, Math.floor((outputIndex + 1) * ratio));
    let sum = 0;
    for (let inputIndex = start; inputIndex < end; inputIndex += 1) sum += samples[inputIndex];
    output[outputIndex] = sum / Math.max(1, end - start);
  }
  return output;
}

function collectLiveSamples(samples) {
  liveSampleBuffers.push(new Float32Array(samples));
  liveSampleCount += samples.length;
  const targetSamples = Math.round(liveAudioContext.sampleRate * STREAM_CHUNK_DURATION_MS / 1000);
  while (liveSampleCount >= targetSamples) {
    const chunk = new Float32Array(targetSamples);
    let written = 0;
    while (written < targetSamples) {
      const current = liveSampleBuffers[0];
      const take = Math.min(current.length, targetSamples - written);
      chunk.set(current.subarray(0, take), written);
      written += take;
      if (take === current.length) liveSampleBuffers.shift();
      else liveSampleBuffers[0] = current.subarray(take);
      liveSampleCount -= take;
    }
    queueLiveAudioChunk(chunk);
  }
}

function queueLiveAudioChunk(samples, durationMs = STREAM_CHUNK_DURATION_MS) {
  if (!liveAudioContext) return;
  const normalized = downsampleAudio(samples, liveAudioContext.sampleRate, STREAM_TARGET_SAMPLE_RATE);
  livePendingChunks.push({
    sequence: null,
    durationMs: Math.max(1, Math.round(durationMs)),
    payload: encodePcm16(normalized),
  });
  livePendingMs += durationMs;
  updateLiveBacklog();
  drainLiveAudioQueue();
}

function drainLiveAudioQueue() {
  window.clearTimeout(liveDrainTimer);
  liveDrainTimer = null;
  if (
    !liveCanSend ||
    liveInFlightChunk ||
    !livePendingChunks.length ||
    !liveSocket ||
    liveSocket.readyState !== WebSocket.OPEN
  ) return;

  const chunk = livePendingChunks[0];
  if (!chunk.sequence) {
    liveSequence += 1;
    chunk.sequence = liveSequence;
  }
  liveInFlightChunk = chunk;
  liveSocket.send(JSON.stringify({
    type: "audio_chunk",
    sequence: chunk.sequence,
    duration_ms: chunk.durationMs,
  }));
  liveSocket.send(chunk.payload);
}

function scheduleLiveQueueDrain(delayMs = 30) {
  window.clearTimeout(liveDrainTimer);
  liveDrainTimer = window.setTimeout(drainLiveAudioQueue, delayMs);
}

function acknowledgeLiveChunk(session) {
  if (!liveInFlightChunk || (session.last_sequence || 0) < liveInFlightChunk.sequence) return;
  const acknowledged = livePendingChunks.shift();
  livePendingMs = Math.max(0, livePendingMs - acknowledged.durationMs);
  liveInFlightChunk = null;
}

function updateLiveBacklog(serverQueuedMs = 0) {
  elements.liveBackpressure.textContent = `${(serverQueuedMs / 1000).toFixed(1)}s 服务端 · ${(livePendingMs / 1000).toFixed(1)}s 本地`;
}

function waitForLiveQueueToFlush() {
  const startedAt = Date.now();
  return new Promise((resolve) => {
    const check = () => {
      if (!livePendingChunks.length && !liveInFlightChunk) {
        resolve(true);
      } else if (Date.now() - startedAt >= STREAM_STOP_FLUSH_TIMEOUT_MS) {
        resolve(false);
      } else {
        scheduleLiveQueueDrain(0);
        window.setTimeout(check, 100);
      }
    };
    check();
  });
}

function updateTaskProgress(task) {
  const progress = Math.max(0, Math.min(100, Number(task.progress) || 0));
  elements.progressBar.style.width = `${progress}%`;
  elements.progressLabel.textContent = taskStageLabels[task.stage] || task.message || task.stage;
  elements.progressPercent.textContent = `${progress}%`;
  elements.taskProgress.dataset.stage = task.stage;
  elements.taskProgress.classList.toggle("is-active", !["completed", "failed", "cancelled"].includes(task.stage));
  elements.cancelTaskButton.hidden = ["completed", "failed", "cancelled"].includes(task.stage);
  setState(["queued", "uploading", "downloading", "waiting_for_gpu"].includes(task.stage) ? "uploading" : "transcribing");
}

function resetTaskProgress() {
  elements.progressBar.style.width = "0%";
  elements.progressLabel.textContent = "等待创建任务";
  elements.progressPercent.textContent = "0%";
  elements.taskProgress.dataset.stage = "idle";
  elements.taskProgress.classList.remove("is-active");
  elements.cancelTaskButton.hidden = true;
}

function markTaskFailure() {
  elements.taskProgress.dataset.stage = "failed";
  elements.taskProgress.classList.remove("is-active");
  elements.progressLabel.textContent = "任务未完成";
  elements.cancelTaskButton.hidden = true;
}

function beginTaskProgress() {
  resetTaskProgress();
  elements.progressLabel.textContent = "正在创建任务…";
  elements.taskProgress.dataset.stage = "queued";
  elements.taskProgress.classList.add("is-active");
}

async function waitForTask(taskId) {
  currentTaskId = taskId;
  elements.cancelTaskButton.hidden = false;

  while (currentTaskId === taskId) {
    const response = await fetch(`${API_BASE_URL}/api/tasks/${taskId}`, { cache: "no-store" });
    if (!response.ok) throw new Error("无法读取任务状态。");
    const task = await response.json();
    updateTaskProgress(task);

    if (task.stage === "completed") {
      const resultResponse = await fetch(`${API_BASE_URL}/api/tasks/${taskId}/result`, { cache: "no-store" });
      if (!resultResponse.ok) throw new Error("任务已完成，但无法读取结果。");
      currentTaskId = null;
      elements.cancelTaskButton.hidden = true;
      return resultResponse.json();
    }
    if (task.stage === "failed") {
      currentTaskId = null;
      throw new Error(task.error || "转写任务失败。");
    }
    if (task.stage === "cancelled") {
      currentTaskId = null;
      throw new Error("任务已取消。");
    }

    await new Promise((resolve) => window.setTimeout(resolve, 800));
  }
  throw new Error("任务已取消。");
}

async function cancelCurrentTask() {
  if (!currentTaskId) return;
  const taskId = currentTaskId;
  elements.cancelTaskButton.disabled = true;
  try {
    await fetch(`${API_BASE_URL}/api/tasks/${taskId}/cancel`, { method: "POST" });
  } finally {
    elements.cancelTaskButton.disabled = false;
  }
}

function showError(message) {
  elements.errorMessage.hidden = !message;
  elements.errorMessage.textContent = message || "";
  elements.errorMessage.classList.toggle("is-visible", Boolean(message));
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
    if (health.live_asr_engine === "funasr" && !health.live_asr_ready) {
      elements.liveProcessing.textContent = "模型预热中";
      elements.liveHint.textContent = "后端正在预热实时识别模型；可以开始录音，首批字幕会在模型就绪后出现。";
      window.setTimeout(checkBackendCapabilities, 1000);
    } else if (!liveStartedAt) {
      elements.liveProcessing.textContent = "已就绪";
    }
  } catch {
    // The normal upload flow will show a useful connection error when needed.
  }
}

async function checkAssistProviderStatus() {
  try {
    const response = await fetch(`${API_BASE_URL}/api/assist/provider`, { cache: "no-store" });
    if (!response.ok) return;

    const status = await response.json();
    const missing = Array.isArray(status.missing) ? status.missing : [];
    elements.providerStatus.classList.toggle("provider-ready", Boolean(status.ready));
    elements.providerStatus.classList.toggle("provider-warning", !status.ready);
    elements.providerStatus.querySelector("strong").textContent = `辅助模型 · ${status.provider}`;
    elements.providerStatus.querySelector("p").textContent = status.ready
      ? `${status.mode} 已就绪。${status.next_step || ""}`
      : `${status.mode} 未就绪：缺少 ${missing.join(", ") || "配置"}。${status.next_step || ""}`;
  } catch {
    elements.providerStatus.classList.add("provider-warning");
    elements.providerStatus.querySelector("p").textContent = "暂时无法读取辅助模型配置状态。";
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
  resetTaskProgress();

  elements.fileName.textContent = file.name;
  elements.fileMeta.textContent = `${(file.size / 1024 / 1024).toFixed(1)} MB · 已准备转写`;
  elements.durationLabel.textContent = "等待转写";
  renderDemo();
}

async function transcribeAudio(file) {
  const body = new FormData();
  body.append("file", file);

  const response = await fetch(`${API_BASE_URL}/api/tasks/transcribe`, {
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

  const task = await response.json();
  return waitForTask(task.task_id);
}

async function transcribeVideoUrl(url) {
  const browser = elements.browserCookieSelect.value || null;
  const response = await fetch(`${API_BASE_URL}/api/tasks/transcribe-url`, {
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

  const task = await response.json();
  return waitForTask(task.task_id);
}

async function requestAssistance(action, customPrompt = null) {
  const response = await fetch(`${API_BASE_URL}/api/assist`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      action,
      window_seconds: action === "catchup" ? 180 : 60,
      segments: latestResult?.segments || [],
      custom_prompt: customPrompt,
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
  caution.textContent = `${result.caution} · Provider: ${result.provider || "unknown"}`;

  elements.noticeMessage.append(title, summary, list, caution);
}

async function handleAssistance(action, button, customPrompt = null) {
  if (!latestResult?.segments?.length) {
    showNotice("请先完成一次音频或视频转写，再使用理解辅助。");
    return;
  }

  showError("");
  showNotice(`正在${assistActionLabels[action] || "整理最近的讨论上下文"}...`);
  button.disabled = true;

  try {
    const result = await requestAssistance(action, customPrompt);
    renderAssistance(result);
  } catch (error) {
    showNotice("");
    showError(error instanceof Error ? error.message : "理解辅助请求失败，请稍后再试。");
  } finally {
    button.disabled = false;
  }
}

async function handleCustomQuestion(event) {
  event.preventDefault();
  const prompt = elements.customQuestionInput.value.trim();
  if (!prompt) {
    showError("请先输入你想结合当前字幕了解的问题。");
    elements.customQuestionInput.focus();
    return;
  }
  await handleAssistance("custom", elements.customQuestionButton, prompt);
}

function updateLiveTimer() {
  if (!liveStartedAt) return;
  elements.liveTimer.textContent = formatTimestamp((Date.now() - liveStartedAt) / 1000);
}

function updateLiveSessionStatus(session) {
  if (!session) return;
  acknowledgeLiveChunk(session);
  updateLiveBacklog(session.queued_ms || 0);
  elements.liveRevision.textContent = String(session.revision || 0);
  liveCanSend = !["degraded", "full"].includes(session.backpressure);
  elements.liveBackpressure.classList.toggle("is-warning", !liveCanSend);
  elements.liveHint.textContent = liveCanSend
    ? "麦克风音频正在本机处理；实时阶段先标记发言者待识别，会后再进行说话人修订。"
    : "服务端处理积压，未发送音频正在本地排队，不会直接丢弃。";
  scheduleLiveQueueDrain();
}

function mergeLiveSegments(finalSegments = [], partialSegments = null) {
  const finalizedIds = new Set(finalSegments.map((segment) => segment.id));
  if (finalizedIds.size) {
    livePartialSegments = livePartialSegments.filter((segment) => !finalizedIds.has(segment.id));
  }
  finalSegments.forEach((segment) => {
    const index = liveFinalSegments.findIndex((item) => item.id === segment.id);
    if (index >= 0) liveFinalSegments[index] = segment;
    else liveFinalSegments.push(segment);
  });
  liveFinalSegments.sort((left, right) => left.start - right.start);
  if (partialSegments !== null) livePartialSegments = partialSegments;
  latestResult = {
    language: "zh",
    duration: Math.max(0, ...[...liveFinalSegments, ...livePartialSegments].map((segment) => segment.end || 0)),
    segments: [...liveFinalSegments, ...livePartialSegments],
  };
  scheduleLiveTranscriptRender();
}

function scheduleLiveTranscriptRender({ immediate = false } = {}) {
  window.clearTimeout(liveRenderTimer);
  liveRenderTimer = window.setTimeout(renderLiveTranscript, immediate ? 0 : LIVE_RENDER_INTERVAL_MS);
}

function liveSpeakerLabel(speaker) {
  return ["Speaker pending", "Mixed speakers", "Unknown"].includes(speaker)
    ? "发言者待识别"
    : speaker;
}

function buildLiveDisplaySegments(segments) {
  return segments.reduce((turns, segment) => {
    const normalized = { ...segment, speaker: liveSpeakerLabel(segment.speaker) };
    const previous = turns[turns.length - 1];
    const canMerge = previous
      && previous.speaker === normalized.speaker
      && normalized.start - previous.end <= LIVE_TURN_GAP_SECONDS
      && normalized.end - previous.start <= LIVE_TURN_MAX_SECONDS
      && previous.final !== false
      && normalized.final !== false;
    if (!canMerge) {
      turns.push({ ...normalized, displayId: String(normalized.id) });
      return turns;
    }
    previous.end = normalized.end;
    const separator = /[a-z0-9]$/i.test(previous.text) && /^[a-z0-9]/i.test(normalized.text)
      ? " "
      : "";
    previous.text += `${separator}${normalized.text}`;
    return turns;
  }, []);
}

function createTranscriptItem(segment) {
  const item = document.createElement("div");
  item.className = "transcript-item";
  const meta = document.createElement("div");
  meta.className = "transcript-meta";
  const time = document.createElement("span");
  time.dataset.role = "time";
  const speaker = document.createElement("span");
  speaker.dataset.role = "speaker";
  const text = document.createElement("p");
  text.dataset.role = "text";
  meta.append(time, speaker);
  item.append(meta, text);
  updateTranscriptItem(item, segment);
  return item;
}

function updateTranscriptItem(item, segment) {
  item.classList.toggle("transcript-partial", segment.final === false);
  item.querySelector('[data-role="time"]').textContent = formatTimestamp(segment.start);
  const speaker = item.querySelector('[data-role="speaker"]');
  speaker.className = `speaker-chip ${String(segment.speaker).endsWith("B") ? "speaker-b" : ""} ${segment.speaker === "发言者待识别" ? "speaker-pending" : ""}`;
  speaker.textContent = segment.speaker;
  const text = item.querySelector('[data-role="text"]');
  if (text.textContent !== segment.text) text.textContent = segment.text;
}

function reconcileLiveTranscript(segments) {
  const wasNearBottom = elements.transcriptList.scrollHeight
    - elements.transcriptList.scrollTop
    - elements.transcriptList.clientHeight < 48;
  const existing = new Map(
    [...elements.transcriptList.querySelectorAll("[data-live-segment-id]")]
      .map((item) => [item.dataset.liveSegmentId, item]),
  );
  const keep = new Set();
  segments.forEach((segment) => {
    const id = segment.displayId;
    keep.add(id);
    let item = existing.get(id);
    if (!item) {
      item = createTranscriptItem(segment);
      item.dataset.liveSegmentId = id;
      elements.transcriptList.append(item);
    } else {
      updateTranscriptItem(item, segment);
    }
  });
  existing.forEach((item, id) => {
    if (!keep.has(id)) item.remove();
  });
  elements.transcriptList.querySelector(".live-empty")?.remove();
  if (wasNearBottom) elements.transcriptList.scrollTop = elements.transcriptList.scrollHeight;
}

function handleLiveEvent(event) {
  if (event.type === "session_ready" || event.type === "buffer_status") {
    updateLiveSessionStatus(event.session);
  } else if (event.type === "processing_status") {
    elements.liveProcessing.textContent = event.state === "initializing"
      ? "模型初始化中"
      : event.state === "processing"
        ? "GPU 转写中"
        : "等待音频";
    elements.livePulse.classList.toggle("is-processing", event.state === "processing");
  } else if (event.type === "backpressure") {
    liveCanSend = event.level === "normal" || event.level === "warning";
    if (event.level === "full") liveInFlightChunk = null;
    updateLiveBacklog(event.queued_ms || 0);
    elements.liveBackpressure.classList.toggle("is-warning", !liveCanSend);
    scheduleLiveQueueDrain();
  } else if (event.type === "transcript_partial") {
    elements.liveRevision.textContent = String(event.revision || 0);
    mergeLiveSegments([], event.segments || []);
  } else if (event.type === "transcript_final") {
    elements.liveRevision.textContent = String(event.revision || 0);
    mergeLiveSegments(event.segments || [], null);
  } else if (event.type === "processing_error" || event.type === "error") {
    showError(event.detail || "实时字幕处理失败。");
  } else if (event.type === "session_stopped") {
    finishLiveUi();
  }
}

async function startLiveSession() {
  if (!navigator.mediaDevices?.getUserMedia || !window.AudioContext) {
    showError("当前浏览器不支持实时麦克风采集，请使用最新版 Chrome、Edge 或 Firefox。");
    return;
  }

  showError("");
  liveFinalSegments = [];
  livePartialSegments = [];
  liveSequence = 0;
  liveCanSend = true;
  liveSampleBuffers = [];
  liveSampleCount = 0;
  livePendingChunks = [];
  livePendingMs = 0;
  liveInFlightChunk = null;
  window.clearTimeout(liveRenderTimer);
  liveRenderTimer = null;
  renderLiveTranscript();
  elements.startLiveButton.disabled = true;
  elements.liveStatus.textContent = "正在请求麦克风权限";

  try {
    liveMediaStream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
    });
    liveAudioContext = new AudioContext();
    const response = await fetch(`${API_BASE_URL}/api/stream/sessions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        mime_type: "audio/pcm;format=s16le",
        sample_rate: STREAM_TARGET_SAMPLE_RATE,
        channels: 1,
        chunk_duration_ms: STREAM_CHUNK_DURATION_MS,
      }),
    });
    if (!response.ok) throw new Error("无法创建实时字幕会话。");
    const session = await response.json();
    liveSocket = new WebSocket(websocketUrl(session.websocket_url));
    liveSocket.addEventListener("message", (message) => handleLiveEvent(JSON.parse(message.data)));
    liveSocket.addEventListener("error", () => showError("实时字幕连接发生错误。"));
    liveSocket.addEventListener("close", () => {
      if (liveStartedAt) {
        stopLiveCapture().finally(() => finishLiveUi());
      }
    });
    await new Promise((resolve, reject) => {
      liveSocket.addEventListener("open", resolve, { once: true });
      liveSocket.addEventListener("error", reject, { once: true });
    });

    liveSourceNode = liveAudioContext.createMediaStreamSource(liveMediaStream);
    liveProcessorNode = liveAudioContext.createScriptProcessor(4096, 1, 1);
    liveProcessorNode.onaudioprocess = (event) => collectLiveSamples(event.inputBuffer.getChannelData(0));
    liveSourceNode.connect(liveProcessorNode);
    liveProcessorNode.connect(liveAudioContext.destination);

    liveStartedAt = Date.now();
    liveTimerHandle = window.setInterval(updateLiveTimer, 500);
    elements.liveStatus.textContent = "正在聆听";
    elements.livePulse.classList.add("is-live");
    elements.startLiveButton.hidden = true;
    elements.stopLiveButton.hidden = false;
    elements.durationLabel.textContent = "实时字幕";
    setState("live");
  } catch (error) {
    showError(error instanceof Error ? error.message : "无法启动实时麦克风。");
    await releaseLiveResources();
    elements.startLiveButton.disabled = false;
    elements.liveStatus.textContent = "启动失败";
    setState("error");
  }
}

async function stopLiveSession() {
  elements.stopLiveButton.disabled = true;
  elements.liveStatus.textContent = "正在发送剩余音频";
  await stopLiveCapture();
  const flushed = await waitForLiveQueueToFlush();
  if (!flushed) showError("本地音频队列未能在 30 秒内排空，最后一小段音频可能未转写。");
  elements.liveStatus.textContent = "正在确认最后字幕";
  if (liveSocket?.readyState === WebSocket.OPEN) liveSocket.send(JSON.stringify({ type: "stop" }));
}

async function stopLiveCapture() {
  if (liveProcessorNode) liveProcessorNode.onaudioprocess = null;
  if (liveSampleCount && liveAudioContext) {
    const tail = new Float32Array(liveSampleCount);
    let offset = 0;
    liveSampleBuffers.forEach((samples) => {
      tail.set(samples, offset);
      offset += samples.length;
    });
    queueLiveAudioChunk(tail, tail.length / liveAudioContext.sampleRate * 1000);
  }
  liveSampleBuffers = [];
  liveSampleCount = 0;
  liveProcessorNode?.disconnect();
  liveSourceNode?.disconnect();
  liveMediaStream?.getTracks().forEach((track) => track.stop());
  if (liveAudioContext && liveAudioContext.state !== "closed") await liveAudioContext.close();
  liveProcessorNode = null;
  liveSourceNode = null;
  liveMediaStream = null;
  liveAudioContext = null;
}

async function releaseLiveResources() {
  await stopLiveCapture();
  window.clearTimeout(liveDrainTimer);
  liveDrainTimer = null;
  livePendingChunks = [];
  livePendingMs = 0;
  liveInFlightChunk = null;
  if (liveSocket && liveSocket.readyState < WebSocket.CLOSING) liveSocket.close();
  liveSocket = null;
}

function finishLiveUi() {
  window.clearInterval(liveTimerHandle);
  liveTimerHandle = null;
  liveStartedAt = null;
  liveSocket = null;
  elements.liveStatus.textContent = "实时字幕已结束";
  elements.liveProcessing.textContent = "已完成";
  elements.livePulse.classList.remove("is-live", "is-processing");
  elements.startLiveButton.hidden = false;
  elements.startLiveButton.disabled = false;
  elements.stopLiveButton.hidden = true;
  elements.stopLiveButton.disabled = false;
  setState("complete");
}

async function handleTranscribe() {
  if (!selectedFile) {
    elements.audioInput.click();
    return;
  }

  showError("");
  showNotice("");
  setState("uploading");
  beginTaskProgress();

  try {
    window.setTimeout(() => setState("transcribing"), 300);
    latestResult = await transcribeAudio(selectedFile);
    renderResult(latestResult);
    setState("complete");
  } catch (error) {
    showError(error instanceof Error ? error.message : "转写失败，请稍后再试。");
    markTaskFailure();
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
  beginTaskProgress();

  try {
    window.setTimeout(() => setState("transcribing"), 300);
    latestResult = await transcribeVideoUrl(url);
    renderResult(latestResult);
    setState("complete");
  } catch (error) {
    showError(error instanceof Error ? error.message : "链接转写失败，请稍后再试。");
    markTaskFailure();
    setState("error");
  }
}

function setInputMode(nextMode) {
  if (currentTaskId || liveStartedAt) {
    showError("当前仍有任务运行，请先结束或等待任务完成。");
    return;
  }
  window.clearTimeout(liveRenderTimer);
  liveRenderTimer = null;
  inputMode = nextMode;
  const isFileMode = inputMode === "file";
  const isUrlMode = inputMode === "url";
  const isLiveMode = inputMode === "live";

  elements.uploadZone.hidden = !isFileMode;
  elements.urlZone.hidden = !isUrlMode;
  elements.liveZone.hidden = !isLiveMode;
  elements.fileModeButton.classList.toggle("active", isFileMode);
  elements.urlModeButton.classList.toggle("active", isUrlMode);
  elements.liveModeButton.classList.toggle("active", isLiveMode);

  showError("");
  showNotice("");
  setState("idle");
  resetTaskProgress();
  elements.taskProgress.hidden = isLiveMode;
  if (isLiveMode) {
    liveFinalSegments = [];
    livePartialSegments = [];
    elements.durationLabel.textContent = "等待开始";
    renderLiveTranscript();
  } else {
    elements.durationLabel.textContent = selectedFile ? "等待转写" : "等待输入";
  }
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
    elements.transcriptList.append(createTranscriptItem(segment));
  });
}

function renderLiveTranscript() {
  liveRenderTimer = null;
  const segments = buildLiveDisplaySegments(
    [...liveFinalSegments, ...livePartialSegments].sort((left, right) => left.start - right.start),
  );
  if (!segments.length) {
    if (!elements.transcriptList.querySelector(".live-empty")) {
      elements.transcriptList.innerHTML = `
        <div class="live-empty">
          <span class="live-empty-wave">••••</span>
          <strong>实时字幕会出现在这里</strong>
          <p>实时阶段先标记为“发言者待识别”；单麦克风无法可靠区分同时说话的人。</p>
        </div>
      `;
    }
  } else {
    reconcileLiveTranscript(segments);
  }
  const context = segments.slice(-3).map((segment) => segment.text).join(" ");
  elements.focusTitle.textContent = context ? "实时讨论焦点" : "等待讨论开始";
  elements.focusSummary.textContent = context || "开始实时字幕后，这里会跟随最近的讨论内容更新。";
  elements.focusMeterLast.classList.toggle("active", Boolean(context));
}

function renderDemo() {
  renderTranscript(demoSegments, true);
  elements.focusTitle.textContent = "准备进入讨论";
  elements.focusSummary.textContent = "等待上传录音。转写完成后，这里会从开头几段内容中提取一条基础主题提示。";
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
  elements.focusMeterLast.classList.add("active");
}

elements.pickFileButton.addEventListener("click", () => elements.audioInput.click());
elements.transcribeButton.addEventListener("click", handleTranscribe);
elements.urlTranscribeButton.addEventListener("click", handleUrlTranscribe);
elements.cancelTaskButton.addEventListener("click", cancelCurrentTask);
elements.customQuestionForm.addEventListener("submit", handleCustomQuestion);
elements.fileModeButton.addEventListener("click", () => setInputMode("file"));
elements.urlModeButton.addEventListener("click", () => setInputMode("url"));
elements.liveModeButton.addEventListener("click", () => setInputMode("live"));
elements.startLiveButton.addEventListener("click", startLiveSession);
elements.stopLiveButton.addEventListener("click", stopLiveSession);
window.addEventListener("beforeunload", () => {
  liveMediaStream?.getTracks().forEach((track) => track.stop());
  if (liveSocket?.readyState === WebSocket.OPEN) liveSocket.close();
});
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

document.querySelectorAll(".action-button").forEach((button) => {
  const action = button.dataset.action;
  button.addEventListener("click", () => {
    handleAssistance(action, button);
  });
});

renderDemo();
checkBackendCapabilities();
checkAssistProviderStatus();
