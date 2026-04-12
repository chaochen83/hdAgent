const app = document.getElementById("app");

const state = {
  bootstrap: null,
  authConfig: null,
  user: null,
  sessions: [],
  activeSessionId: null,
  messages: [],
  productModels: [],
  provider: "openai",
  model: "",
  currentProductModel: "",
  view: "chat",
  authMode: "request-code",
  email: "",
  inviteCode: "",
  debugCode: "",
  error: "",
  success: "",
  sending: false,
  userPanelOpen: false,
  usageItems: [],
  adminSection: "overview",
  adminRange: "7d",
  adminOverview: null,
  adminUsers: [],
  adminChats: [],
  adminChatMessages: [],
  adminSelectedChatId: null,
  adminChatUserFilter: "",
  inviteCodes: [],
  adminScrollTop: 0,
  adminForceScrollTop: false,
  knowledgeSection: "ingest",
  boardItems: [],
  knowledgeDocuments: [],
  selectedBoardId: "",
  knowledgeFilterType: "",
  knowledgeFilterStatus: "",
  boardForm: {
    id: "",
    code: "",
    name: "",
    description: "",
    defaultHint: "",
    aliases: "",
    isEnabled: true,
  },
  knowledgeInputType: "file",
  retrievalQuery: "",
  retrievalResults: [],
  activeKnowledgeDetail: null,
  activeKnowledgeJobs: [],
  activeKnowledgeChunks: [],
  boardCreateOpen: false,
  inviteCreateOpen: false,
};

let messageTimer = null;
let knowledgePollTimer = null;

async function apiFetch(url, options = {}) {
  const isFormData = options.body instanceof FormData;
  const response = await fetch(url, {
    credentials: "include",
    headers: {
      ...(isFormData ? {} : { "Content-Type": "application/json" }),
      ...(options.headers || {}),
    },
    ...options,
  });

  if (response.status === 401) {
    state.user = null;
    state.sessions = [];
    state.activeSessionId = null;
    state.messages = [];
    render();
    throw new Error("请先登录。");
  }

  if (!response.ok) {
    let detail = "请求失败。";
    try {
      const payload = await response.json();
      detail = payload.detail || detail;
    } catch {
      detail = await response.text();
    }
    throw new Error(detail);
  }

  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return response.json();
  }
  return response;
}

function setMessage(type, text) {
  state.error = type === "error" ? text : "";
  state.success = type === "success" ? text : "";
  if (messageTimer) {
    clearTimeout(messageTimer);
    messageTimer = null;
  }
  if (text && type === "success") {
    messageTimer = window.setTimeout(() => {
      state.success = "";
      render();
      messageTimer = null;
    }, 3000);
  }
  render();
}

function clearMessages() {
  if (messageTimer) {
    clearTimeout(messageTimer);
    messageTimer = null;
  }
  state.error = "";
  state.success = "";
  render();
}

function escapeHtml(text) {
  return (text || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function formatTime(isoString) {
  if (!isoString) return "";
  const date = new Date(isoString);
  return `${date.getMonth() + 1}/${date.getDate()} ${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

function saveAdminScrollPosition() {
  const panel = document.querySelector(".admin-scroll");
  if (panel) {
    state.adminScrollTop = panel.scrollTop;
  }
}

function restoreAdminScrollPosition() {
  const panel = document.querySelector(".admin-scroll");
  if (panel) {
    if (state.adminForceScrollTop) {
      panel.scrollTop = 0;
      requestAnimationFrame(() => {
        const nextPanel = document.querySelector(".admin-scroll");
        if (nextPanel) {
          nextPanel.scrollTop = 0;
        }
      });
      state.adminForceScrollTop = false;
      return;
    }
    panel.scrollTop = state.adminScrollTop || 0;
  }
}

function renderMarkdownLite(text) {
  const source = text || "";
  const blocks = [];
  const regex = /```(\w+)?\n?([\s\S]*?)```/g;
  let lastIndex = 0;
  let match;

  while ((match = regex.exec(source)) !== null) {
    if (match.index > lastIndex) {
      blocks.push({ type: "text", text: source.slice(lastIndex, match.index) });
    }
    blocks.push({ type: "code", lang: match[1] || "", text: match[2] || "" });
    lastIndex = regex.lastIndex;
  }
  if (lastIndex < source.length) {
    blocks.push({ type: "text", text: source.slice(lastIndex) });
  }

  return blocks
    .map((block) => {
      if (block.type === "code") {
        return `<pre><code>${escapeHtml(block.text.trim())}</code></pre>`;
      }
      return escapeHtml(block.text)
        .replace(/\n{2,}/g, "</p><p>")
        .replace(/\n/g, "<br />")
        .replace(/`([^`]+)`/g, "<code>$1</code>")
        .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
        .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>');
    })
    .join("");
}

async function initialize() {
  try {
    const [bootstrap, authConfig, me, productModels] = await Promise.all([
      apiFetch("/api/bootstrap"),
      apiFetch("/api/auth/config"),
      apiFetch("/api/auth/me"),
      apiFetch("/product-model-list"),
    ]);
    state.bootstrap = bootstrap;
    state.authConfig = authConfig;
    state.user = me.user;
    state.productModels = productModels.product_model_list || [];
    if (state.user) {
      await loadProfile();
      await loadSessions();
    }
  } catch (error) {
    state.error = error.message;
  }
  render();
}

async function loadProfile() {
  const payload = await apiFetch("/api/user/profile");
  state.user = payload.profile;
}

async function loadSessions() {
  const payload = await apiFetch("/api/chat/sessions");
  state.sessions = payload.sessions || [];
  if (!state.activeSessionId && state.sessions.length) {
    await openSession(state.sessions[0].id);
    return;
  }
  if (state.activeSessionId) {
    const stillExists = state.sessions.find((item) => item.id === state.activeSessionId);
    if (!stillExists) {
      state.activeSessionId = null;
      state.messages = [];
    }
  }
}

async function openSession(sessionId) {
  state.activeSessionId = sessionId;
  const payload = await apiFetch(`/api/chat/sessions/${sessionId}/messages`);
  state.messages = payload.messages || [];
  const active = state.sessions.find((item) => item.id === sessionId);
  if (active) {
    state.provider = active.provider || state.provider;
    state.model = active.model || "";
    state.currentProductModel = active.current_product_model || "";
  }
  render();
}

async function createSession() {
  const payload = await apiFetch("/api/chat/sessions", {
    method: "POST",
    body: JSON.stringify({
      provider: state.provider,
      model: state.model || null,
      current_product_model: state.currentProductModel || null,
    }),
  });
  const session = payload.session;
  state.sessions = [session, ...state.sessions];
  state.activeSessionId = session.id;
  state.messages = [];
  render();
  return session;
}

async function requestEmailCode() {
  const email = document.getElementById("emailInput")?.value?.trim();
  if (!email) {
    setMessage("error", "请输入邮箱地址。");
    return;
  }
  state.email = email;
  state.debugCode = "";
  const payload = await apiFetch("/api/auth/email/request-code", {
    method: "POST",
    body: JSON.stringify({ email }),
  });
  state.authMode = "verify-code";
  state.debugCode = payload.dev_code || "";
  setMessage("success", "验证码已发送，请查收邮箱。");
}

async function verifyEmailCode() {
  const code = document.getElementById("codeInput")?.value?.trim();
  const inviteCode = document.getElementById("inviteCodeInput")?.value?.trim() || "";
  if (!state.email || !code) {
    setMessage("error", "请输入邮箱和验证码。");
    return;
  }
  const refreshed = await apiFetch("/api/auth/email/verify-code", {
    method: "POST",
    body: JSON.stringify({ email: state.email, code, invite_code: inviteCode || null }),
  });
  state.inviteCode = inviteCode;
  state.user = refreshed.user;
  state.authMode = "request-code";
  state.debugCode = "";
  state.error = "";
  await loadProfile();
  await loadSessions();
  setMessage("success", "登录成功。");
}

async function logout() {
  await apiFetch("/api/auth/logout", { method: "POST" });
  state.user = null;
  state.sessions = [];
  state.activeSessionId = null;
  state.messages = [];
  state.userPanelOpen = false;
  state.view = "chat";
  render();
}

async function loadUsage() {
  if (!state.user) return;
  const payload = await apiFetch("/api/user/usage/daily");
  state.usageItems = payload.items || [];
}

async function loadAdminData() {
  if (state.user?.role !== "admin") return;
  return loadAdminSection(state.adminSection);
}

async function loadKnowledgeData() {
  if (state.user?.role !== "admin") return;
  const query = new URLSearchParams();
  if (state.selectedBoardId) query.set("board_type_id", state.selectedBoardId);
  if (state.knowledgeFilterType) query.set("knowledge_type", state.knowledgeFilterType);
  if (state.knowledgeFilterStatus) query.set("parse_status", state.knowledgeFilterStatus);
  const [boardsPayload, docsPayload] = await Promise.all([
    apiFetch("/api/admin/boards"),
    apiFetch(`/api/admin/knowledge/documents${query.toString() ? `?${query.toString()}` : ""}`),
  ]);
  state.boardItems = boardsPayload.items || [];
  state.knowledgeDocuments = docsPayload.items || [];
  if (!state.selectedBoardId && state.boardItems.length) {
    state.selectedBoardId = String(state.boardItems[0].id);
  }
  if (!state.boardForm.id && !state.boardForm.name && state.boardItems.length) {
    resetBoardForm();
  }
  scheduleKnowledgePolling();
}

function scheduleKnowledgePolling() {
  if (knowledgePollTimer) {
    clearTimeout(knowledgePollTimer);
    knowledgePollTimer = null;
  }
  const isKnowledgeSurface = state.view === "knowledge";
  const hasActiveJobs = (state.knowledgeDocuments || []).some((item) =>
    ["uploaded", "queued", "parsing", "chunking", "embedding"].includes(item.parse_status),
  );
  if (!isKnowledgeSurface || !hasActiveJobs) return;
  knowledgePollTimer = window.setTimeout(() => {
    loadKnowledgeData()
      .then(() => render())
      .catch(() => {})
      .finally(() => {
        knowledgePollTimer = null;
      });
  }, 2000);
}

function resetBoardForm(board = null) {
  state.boardForm = {
    id: board ? String(board.id) : "",
    code: board?.code || "",
    name: board?.name || "",
    description: board?.description || "",
    defaultHint: board?.default_hint || "",
    aliases: board?.aliases?.join(", ") || "",
    isEnabled: board ? Boolean(board.is_enabled) : true,
  };
}

async function createBoard() {
  const payload = {
    code: document.getElementById("boardCodeInput")?.value?.trim(),
    name: document.getElementById("boardNameInput")?.value?.trim(),
    description: document.getElementById("boardDescriptionInput")?.value?.trim() || null,
    default_hint: document.getElementById("boardHintInput")?.value?.trim() || null,
    aliases: (document.getElementById("boardAliasesInput")?.value || "")
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean),
    is_enabled: Boolean(document.getElementById("boardEnabledInput")?.checked),
  };
  if (!payload.code || !payload.name) {
    setMessage("error", "请先填写板型编码和名称。");
    return;
  }
  await apiFetch("/api/admin/boards", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  resetBoardForm();
  await loadKnowledgeData();
  state.productModels = state.boardItems.map((item) => item.name);
  setMessage("success", "板型已创建。");
}

async function updateBoard() {
  const boardId = state.boardForm.id;
  if (!boardId) {
    setMessage("error", "请先选择要编辑的板型。");
    return;
  }
  const payload = {
    code: document.getElementById("boardCodeInput")?.value?.trim(),
    name: document.getElementById("boardNameInput")?.value?.trim(),
    description: document.getElementById("boardDescriptionInput")?.value?.trim() || null,
    default_hint: document.getElementById("boardHintInput")?.value?.trim() || null,
    aliases: (document.getElementById("boardAliasesInput")?.value || "")
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean),
    is_enabled: Boolean(document.getElementById("boardEnabledInput")?.checked),
  };
  await apiFetch(`/api/admin/boards/${boardId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
  await loadKnowledgeData();
  state.productModels = state.boardItems.map((item) => item.name);
  setMessage("success", "板型已更新。");
}

async function deleteBoard(boardId) {
  await apiFetch(`/api/admin/boards/${boardId}`, { method: "DELETE" });
  if (String(boardId) === String(state.selectedBoardId)) {
    state.selectedBoardId = "";
  }
  resetBoardForm();
  await loadKnowledgeData();
  state.productModels = state.boardItems.filter((item) => !item.deleted_at).map((item) => item.name);
  setMessage("success", "板型已软删除。");
}

async function createKnowledgeFromText() {
  const boardTypeId = Number(document.getElementById("knowledgeBoardSelect")?.value || state.selectedBoardId || 0);
  const title = document.getElementById("knowledgeTextTitleInput")?.value?.trim();
  const text = document.getElementById("knowledgeTextContentInput")?.value?.trim();
  if (!boardTypeId || !title || !text) {
    setMessage("error", "请先选择板型，并填写知识标题和正文。");
    return;
  }
  await apiFetch("/api/admin/knowledge/documents/text", {
    method: "POST",
    body: JSON.stringify({ board_type_id: boardTypeId, title, text }),
  });
  await loadKnowledgeData();
  setMessage("success", "文本知识已入库。");
}

async function createKnowledgeFromWebsite() {
  const boardTypeId = Number(document.getElementById("knowledgeBoardSelect")?.value || state.selectedBoardId || 0);
  const title = document.getElementById("knowledgeWebsiteTitleInput")?.value?.trim();
  const sourceUrl = document.getElementById("knowledgeWebsiteUrlInput")?.value?.trim();
  const content = document.getElementById("knowledgeWebsiteContentInput")?.value?.trim();
  if (!boardTypeId || !title || !sourceUrl || !content) {
    setMessage("error", "请填写网站知识的标题、链接和正文内容。");
    return;
  }
  await apiFetch("/api/admin/knowledge/documents/website", {
    method: "POST",
    body: JSON.stringify({ board_type_id: boardTypeId, title, source_url: sourceUrl, content }),
  });
  await loadKnowledgeData();
  setMessage("success", "网站知识已入库。");
}

async function createKnowledgeFromFile() {
  const boardTypeId = Number(document.getElementById("knowledgeBoardSelect")?.value || state.selectedBoardId || 0);
  const fileInput = document.getElementById("knowledgeFileInput");
  const file = fileInput?.files?.[0];
  if (!boardTypeId || !file) {
    setMessage("error", "请先选择板型并上传 txt 或 xlsx 文件。");
    return;
  }
  const formData = new FormData();
  formData.set("board_type_id", String(boardTypeId));
  formData.set("file", file);
  await apiFetch("/api/admin/knowledge/documents/file", {
    method: "POST",
    body: formData,
  });
  if (fileInput) fileInput.value = "";
  await loadKnowledgeData();
  setMessage("success", "文件知识已上传并入库。");
}

async function deleteKnowledgeDocument(documentId) {
  await apiFetch(`/api/admin/knowledge/documents/${documentId}`, { method: "DELETE" });
  await loadKnowledgeData();
  setMessage("success", "知识条目已删除。");
}

async function runKnowledgeRetrieve() {
  const boardTypeId = Number(document.getElementById("knowledgeRetrieveBoardSelect")?.value || state.selectedBoardId || 0);
  const query = document.getElementById("knowledgeRetrieveQueryInput")?.value?.trim();
  if (!boardTypeId || !query) {
    setMessage("error", "请输入检索问题并选择板型。");
    return;
  }
  const payload = await apiFetch("/api/admin/knowledge/retrieve", {
    method: "POST",
    body: JSON.stringify({ board_type_id: boardTypeId, query, top_k: 5 }),
  });
  state.retrievalQuery = query;
  state.retrievalResults = payload.items || [];
  render();
}

async function openKnowledgeDetail(documentId) {
  const [payload, jobsPayload, chunksPayload] = await Promise.all([
    apiFetch(`/api/admin/knowledge/documents/${documentId}`),
    apiFetch(`/api/admin/knowledge/documents/${documentId}/jobs`),
    apiFetch(`/api/admin/knowledge/documents/${documentId}/chunks?limit=20`),
  ]);
  state.activeKnowledgeDetail = payload.document || null;
  state.activeKnowledgeJobs = jobsPayload.items || [];
  state.activeKnowledgeChunks = chunksPayload.items || [];
  render();
}

function closeKnowledgeDetail() {
  state.activeKnowledgeDetail = null;
  state.activeKnowledgeJobs = [];
  state.activeKnowledgeChunks = [];
  render();
}

async function retryKnowledgeDocument(documentId) {
  await apiFetch(`/api/admin/knowledge/documents/${documentId}/retry`, {
    method: "POST",
  });
  await loadKnowledgeData();
  await openKnowledgeDetail(documentId);
  setMessage("success", "已重新加入解析队列。");
}

async function loadAdminSection(section, options = {}) {
  if (state.user?.role !== "admin") return;
  const preserveScroll = options.preserveScroll !== false;
  if (preserveScroll) {
    saveAdminScrollPosition();
  } else {
    state.adminScrollTop = 0;
    state.adminForceScrollTop = true;
  }
  state.adminSection = section;
  if (section === "overview") {
    state.adminOverview = await apiFetch(`/api/admin/overview?range=${encodeURIComponent(state.adminRange)}`);
    return;
  }
  if (section === "invites") {
    const inviteCodes = await apiFetch("/api/admin/invite-codes");
    state.inviteCodes = inviteCodes.items || [];
    return;
  }
  if (section === "users") {
    const users = await apiFetch("/api/admin/users");
    state.adminUsers = users.items || [];
    return;
  }
  if (section === "chats") {
    if (!state.adminUsers.length) {
      const users = await apiFetch("/api/admin/users");
      state.adminUsers = users.items || [];
    }
    const query = new URLSearchParams({ range: state.adminRange });
    if (state.adminChatUserFilter) {
      query.set("user_id", state.adminChatUserFilter);
    }
    const chats = await apiFetch(`/api/admin/chats?${query.toString()}`);
    state.adminChats = chats.items || [];
    const stillExists = state.adminChats.find((item) => item.id === state.adminSelectedChatId);
    if (!stillExists) {
      state.adminSelectedChatId = null;
      state.adminChatMessages = [];
      return;
    }
    if (state.adminSelectedChatId) {
      await openAdminChat(state.adminSelectedChatId);
    }
  }
}

async function openAdminChat(sessionId) {
  saveAdminScrollPosition();
  state.adminSelectedChatId = sessionId;
  const payload = await apiFetch(`/api/admin/chats/${sessionId}/messages`);
  state.adminChatMessages = payload.items || [];
  render();
}

async function updateAdminUser(userId, patch) {
  await apiFetch(`/api/admin/users/${userId}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
  await loadAdminSection("users");
  await loadProfile();
  setMessage("success", "用户配置已更新。");
}

async function createInviteCode() {
  const code = document.getElementById("newInviteCodeInput")?.value?.trim();
  const quotaTier = document.getElementById("newInviteQuotaSelect")?.value?.trim() || null;
  if (!code) {
    setMessage("error", "请输入邀请码。");
    return;
  }
  await apiFetch("/api/admin/invite-codes", {
    method: "POST",
    body: JSON.stringify({
      code,
      assigned_quota_tier_code: quotaTier || null,
      max_uses: 1,
    }),
  });
  await loadAdminSection("invites");
  setMessage("success", "邀请码已创建。");
}

async function toggleUserPanel() {
  state.userPanelOpen = !state.userPanelOpen;
  if (state.userPanelOpen) {
    await loadUsage();
  }
  render();
}

async function sendMessage() {
  const textarea = document.getElementById("composerInput");
  const message = textarea?.value?.trim();
  if (!message || state.sending) return;

  state.sending = true;
  state.error = "";

  let sessionId = state.activeSessionId;
  if (!sessionId) {
    const session = await createSession();
    sessionId = session.id;
  }

  const userMessage = {
    id: `local-user-${Date.now()}`,
    role: "user",
    content: message,
    created_at: new Date().toISOString(),
  };
  const assistantMessage = {
    id: `local-assistant-${Date.now()}`,
    role: "assistant",
    content: "",
    created_at: new Date().toISOString(),
  };
  state.messages = [...state.messages, userMessage, assistantMessage];
  textarea.value = "";
  render();

  try {
    const response = await fetch(`/api/chat/sessions/${sessionId}/stream`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message,
        provider: state.provider,
        model: state.model || null,
        current_product_model: state.currentProductModel || null,
      }),
    });

    if (!response.ok || !response.body) {
      throw new Error("聊天请求失败。");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let currentEvent = "message";
    let currentData = [];

    const flushEvent = () => {
      if (!currentData.length) return;
      const data = currentData.join("\n");
      if (currentEvent === "token") {
        assistantMessage.content += data;
      } else if (currentEvent === "product_model") {
        state.currentProductModel = data;
      } else if (currentEvent === "error") {
        state.error = data;
      }
      currentEvent = "message";
      currentData = [];
      render();
    };

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      while (buffer.includes("\n")) {
        const index = buffer.indexOf("\n");
        const line = buffer.slice(0, index).replace(/\r$/, "");
        buffer = buffer.slice(index + 1);

        if (!line) {
          flushEvent();
          continue;
        }
        if (line.startsWith("event:")) {
          currentEvent = line.slice(6).trim();
          continue;
        }
        if (line.startsWith("data:")) {
          currentData.push(line.slice(5).trimStart());
        }
      }
    }

    flushEvent();
    await loadSessions();
    await loadProfile();
  } catch (error) {
    state.error = error.message;
  } finally {
    state.sending = false;
    render();
  }
}

function renderBanner() {
  const items = [];
  if (state.error) {
    items.push({ type: "error", text: state.error });
  }
  if (state.success) {
    items.push({ type: "success", text: state.success });
  }
  if (!items.length) return "";

  return `
    <div class="toast-stack">
      ${items
        .map(
          (item) => `
            <div class="toast toast-${item.type}">
              <div class="toast-content">${escapeHtml(item.text)}</div>
              <button class="toast-close" type="button" data-toast-close="true" aria-label="关闭通知">×</button>
            </div>
          `,
        )
        .join("")}
    </div>
  `;
}

function renderLogin() {
  const googleEnabled = state.authConfig?.googleAuthEnabled;
  const phoneEnabled = state.authConfig?.phoneLoginEnabled;

  app.innerHTML = `
    <div class="login-shell">
      <section class="login-hero">
        <div class="brand-lockup">
          <div class="brand-mark">M</div>
          <div>
            <div class="session-title">Makerfabs Agent</div>
            <div class="nav-item-meta">Hardware support copilot</div>
          </div>
        </div>
        <div class="hero-copy">
          <h1>先登录，再进入 Makerfabs Agent。</h1>
          <p>这一版先把登录、用户中心、Recent 会话和 Makerfabs Agent 主界面工程化。知识库模块会在下一阶段接入上传、解析和向量检索。</p>
        </div>
        <div class="hero-points">
          <div class="hero-point">Google OAuth 登录，后端完成回调、建档和会话创建。</div>
          <div class="hero-point">邮箱验证码登录，支持本地 console 模式和可切换的 SMTP 邮件发送。</div>
          <div class="hero-point">手机登录保留入口，当前展示“开发中”，后续接第三方验证码服务即可启用。</div>
        </div>
      </section>
      <section class="login-panel">
        <div class="login-panel-inner">
          ${renderBanner()}
          <div class="auth-card stack-lg">
            <div class="stack">
              <h2>登录 / 注册</h2>
              <div class="muted">Google 登录和邮箱验证码已经预留成可直接接生产配置的链路。</div>
            </div>
            <div class="stack">
              <button class="button" id="googleLoginBtn" ${googleEnabled ? "" : "disabled"}>继续使用 Google</button>
              <div class="auth-divider">或者使用邮箱</div>
              <div class="field">
                <label for="emailInput">邮箱</label>
                <input class="input" id="emailInput" type="email" placeholder="you@example.com" value="${escapeHtml(state.email)}" />
              </div>
              <div class="field">
                <label for="inviteCodeInput">邀请码（新用户必填）</label>
                <input class="input" id="inviteCodeInput" type="text" placeholder="请输入邀请码" value="${escapeHtml(state.inviteCode)}" />
              </div>
              ${
                state.authMode === "verify-code"
                  ? `
                    <div class="field">
                      <label for="codeInput">6 位验证码</label>
                      <input class="input" id="codeInput" type="text" maxlength="6" placeholder="请输入验证码" />
                    </div>
                    <button class="button" id="verifyCodeBtn">验证并登录</button>
                  `
                  : `<button class="button button-secondary" id="requestCodeBtn">发送验证码</button>`
              }
              ${
                state.debugCode
                  ? `<div class="dev-note">当前使用 console 邮件模式，开发验证码：<strong>${escapeHtml(state.debugCode)}</strong></div>`
                  : ""
              }
              <button class="button button-secondary" id="phoneLoginBtn" disabled>
                手机登录 ${phoneEnabled ? "" : '<span class="badge badge-warning">开发中</span>'}
              </button>
            </div>
          </div>
        </div>
      </section>
    </div>
  `;

  document.getElementById("googleLoginBtn")?.addEventListener("click", () => {
    window.location.href = "/api/auth/google/login";
  });
  document.getElementById("requestCodeBtn")?.addEventListener("click", () => requestEmailCode().catch((error) => setMessage("error", error.message)));
  document.getElementById("verifyCodeBtn")?.addEventListener("click", () => verifyEmailCode().catch((error) => setMessage("error", error.message)));
}

function renderMessages() {
  if (!state.messages.length) {
    return `
      <div class="empty-state">
        <h2>Makerfabs Agent</h2>
        <p class="muted">登录后已支持 Recent 会话存储。你可以先告诉我板卡型号，再继续问接线、代码生成和调试问题。</p>
        <div class="stack">
          <div class="dev-note">建议第一句就带上产品型号，例如：<strong>帮我写一个 MaTouch_ESP32S3 触摸屏示例</strong></div>
        </div>
      </div>
    `;
  }

  return `
    <div class="chat-stack">
      ${state.messages
        .map(
          (message) => `
            <article class="message">
              <div class="avatar ${message.role === "assistant" ? "assistant" : "user"}">${message.role === "assistant" ? "M" : "U"}</div>
              <div class="bubble ${message.role === "assistant" ? "assistant" : ""}">
                <div class="bubble-header">
                  <strong>${message.role === "assistant" ? "Makerfabs Agent" : "你"}</strong>
                  <span>${formatTime(message.created_at)}</span>
                </div>
                <div>${renderMarkdownLite(message.content || "")}</div>
              </div>
            </article>
          `,
        )
        .join("")}
    </div>
  `;
}

function renderUsageSummary() {
  if (!state.user) return "";
  if (state.user.is_unlimited) {
    return `<div class="dev-note">当前账号为无限额度。</div>`;
  }
  return `
    <div class="quota-card">
      <div><strong>${escapeHtml(state.user.quota_tier_code || "basic")}</strong> 档位</div>
      <div class="muted">今日已用 ${Number(state.user.today_used_tokens || 0).toLocaleString()} / ${Number(state.user.daily_token_limit || 0).toLocaleString()} tokens</div>
      <div class="muted">剩余 ${Number(state.user.remaining_tokens || 0).toLocaleString()} tokens</div>
    </div>
  `;
}

function renderLineChart(items, rangeKey) {
  const points = items || [];
  const width = 720;
  const height = 260;
  const paddingLeft = 64;
  const paddingRight = 24;
  const paddingTop = 24;
  const paddingBottom = 48;
  if (!points.length) {
    return `<div class="muted">当前时间范围还没有 token 数据。</div>`;
  }
  const maxValue = Math.max(...points.map((item) => Number(item.total_tokens || 0)), 1);
  const plotWidth = width - paddingLeft - paddingRight;
  const plotHeight = height - paddingTop - paddingBottom;
  const stepX = points.length > 1 ? plotWidth / (points.length - 1) : 0;
  const yTicks = 4;
  const isHourlyRange = rangeKey === "1d";
  const labelStep = points.length > 12 ? Math.ceil(points.length / 6) : 1;
  const tickValues = Array.from({ length: yTicks + 1 }, (_, index) => Math.round((maxValue * (yTicks - index)) / yTicks));
  const path = points
    .map((item, index) => {
      const x = paddingLeft + stepX * index;
      const y = paddingTop + plotHeight - (plotHeight * Number(item.total_tokens || 0)) / maxValue;
      return `${index === 0 ? "M" : "L"} ${x} ${y}`;
    })
    .join(" ");
  const gridLines = tickValues
    .map((value, index) => {
      const y = paddingTop + (plotHeight * index) / yTicks;
      return `
        <line class="chart-grid" x1="${paddingLeft}" y1="${y}" x2="${width - paddingRight}" y2="${y}"></line>
        <text class="chart-label chart-y-label" x="${paddingLeft - 10}" y="${y + 4}" text-anchor="end">${Number(value).toLocaleString()}</text>
      `;
    })
    .join("");
  const dots = points
    .map((item, index) => {
      const x = paddingLeft + stepX * index;
      const y = paddingTop + plotHeight - (plotHeight * Number(item.total_tokens || 0)) / maxValue;
      const rawLabel = isHourlyRange
        ? `${String(Number(item.usage_hour || 0)).padStart(2, "0")}:00`
        : item.usage_date.slice(5);
      const label = index % labelStep === 0 || index === points.length - 1 ? rawLabel : "";
      const tooltip = isHourlyRange
        ? `${item.usage_date} · ${Number(item.total_tokens || 0).toLocaleString()} tokens`
        : `${item.usage_date} · ${Number(item.total_tokens || 0).toLocaleString()} tokens`;
      return `
        <circle cx="${x}" cy="${y}" r="4">
          <title>${escapeHtml(tooltip)}</title>
        </circle>
        ${label ? `<text class="chart-label" x="${x}" y="${height - 16}" text-anchor="middle">${escapeHtml(label)}</text>` : ""}
      `;
    })
    .join("");
  return `
    <svg class="chart-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="Token usage timeline">
      <text class="chart-axis-title" x="${width / 2}" y="${height - 2}" text-anchor="middle">${isHourlyRange ? "时间（HH:00）" : "日期（MM-DD）"}</text>
      <text class="chart-axis-title" x="16" y="${height / 2}" text-anchor="middle" transform="rotate(-90 16 ${height / 2})">Token 数量</text>
      ${gridLines}
      <line x1="${paddingLeft}" y1="${height - paddingBottom}" x2="${width - paddingRight}" y2="${height - paddingBottom}"></line>
      <line x1="${paddingLeft}" y1="${paddingTop}" x2="${paddingLeft}" y2="${height - paddingBottom}"></line>
      <path d="${path}"></path>
      ${dots}
    </svg>
  `;
}

function renderAdmin() {
  const overview = state.adminOverview;
  const summary = overview?.summary || { total_tokens: 0, active_users: 0, average_tokens: 0 };
  const section = state.adminSection;
  const tabs = [
    { key: "overview", label: "Token 总览" },
    { key: "invites", label: "邀请码" },
    { key: "users", label: "用户用量" },
    { key: "chats", label: "聊天记录" },
  ];
  return `
    <section class="admin-layout">
      <div class="content-toast-wrap">
        ${renderBanner()}
      </div>
      <div class="admin-scroll">
        <section class="admin-subnav-card">
          <div class="admin-subnav">
            ${tabs
              .map(
                (tab) => `
                  <button class="admin-subnav-item ${tab.key === section ? "active" : ""}" data-admin-section="${tab.key}">${tab.label}</button>
                `,
              )
              .join("")}
          </div>
        </section>
        ${
          section === "overview"
            ? `
              <section class="admin-section">
                <div class="admin-section-header">
                  <div>
                    <h2>Token 总览</h2>
                    <div class="muted">可切换 1 天、7 天、30 天区间。</div>
                  </div>
                  <div class="range-switch">
                    ${["1d", "7d", "30d"]
                      .map(
                        (range) => `<button class="button button-secondary ${range === state.adminRange ? "is-active" : ""}" data-admin-range="${range}">${range}</button>`,
                      )
                      .join("")}
                  </div>
                </div>
                <div class="stats-grid">
                  <div class="stat-card"><span>总 token</span><strong>${Number(summary.total_tokens).toLocaleString()}</strong></div>
                  <div class="stat-card"><span>活跃用户</span><strong>${Number(summary.active_users).toLocaleString()}</strong></div>
                  <div class="stat-card"><span>人均 token</span><strong>${Number(summary.average_tokens).toLocaleString()}</strong></div>
                </div>
                <div class="chart-card">${renderLineChart(overview?.timeline || [], state.adminRange)}</div>
              </section>
            `
            : ""
        }
        ${
          section === "invites"
            ? `
              <section class="admin-section">
                <div class="admin-section-header">
                  <div>
                    <h2>邀请码</h2>
                    <div class="muted">新账号必须通过邀请码注册。</div>
                  </div>
                </div>
                <div class="collapsible-card">
                  <button class="collapsible-trigger ${state.inviteCreateOpen ? "is-open" : ""}" id="inviteCreateToggleBtn">
                    <span>创建邀请码</span>
                    <span>${state.inviteCreateOpen ? "收起" : "展开"}</span>
                  </button>
                  ${
                    state.inviteCreateOpen
                      ? `
                        <div class="collapsible-body">
                          <div class="invite-create-row">
                            <input class="input" id="newInviteCodeInput" type="text" placeholder="例如 maker-2026-001" />
                            <select class="select" id="newInviteQuotaSelect">
                              <option value="">basic</option>
                              <option value="pro">pro</option>
                              <option value="vip">vip</option>
                            </select>
                            <button class="button" id="createInviteBtn">创建邀请码</button>
                          </div>
                        </div>
                      `
                      : ""
                  }
                </div>
                <div class="table-card">
                  <table class="data-table">
                    <thead><tr><th>邀请码</th><th>档位</th><th>使用</th><th>状态</th></tr></thead>
                    <tbody>
                      ${
                        state.inviteCodes.length
                          ? state.inviteCodes
                              .map(
                                (item) => `
                                  <tr>
                                    <td>${escapeHtml(item.code)}</td>
                                    <td>${escapeHtml(item.assigned_quota_tier_code || "basic")}</td>
                                    <td>${item.used_count}/${item.max_uses}</td>
                                    <td>${escapeHtml(item.status)}</td>
                                  </tr>
                                `,
                              )
                              .join("")
                          : `<tr><td colspan="4" class="muted">暂无邀请码。</td></tr>`
                      }
                    </tbody>
                  </table>
                </div>
              </section>
            `
            : ""
        }
        ${
          section === "users"
            ? `
              <section class="admin-section">
                <div class="admin-section-header">
                  <div>
                    <h2>用户用量</h2>
                    <div class="muted">支持直接切换角色、档位和无限额度。</div>
                  </div>
                </div>
                <div class="table-card">
                  <table class="data-table">
                    <thead>
                      <tr><th>用户</th><th>角色</th><th>档位</th><th>今日</th><th>7天</th><th>30天</th><th>无限</th></tr>
                    </thead>
                    <tbody>
                      ${
                        state.adminUsers.length
                          ? state.adminUsers
                              .map(
                                (item) => `
                                  <tr>
                                    <td>
                                      <strong>${escapeHtml(item.display_name || "")}</strong>
                                      <div class="muted">${escapeHtml(item.email || "")}</div>
                                    </td>
                                    <td>
                                      <select class="select admin-user-role" data-user-id="${item.id}">
                                        ${["user", "admin"]
                                          .map((role) => `<option value="${role}" ${role === item.role ? "selected" : ""}>${role}</option>`)
                                          .join("")}
                                      </select>
                                    </td>
                                    <td>
                                      <select class="select admin-user-tier" data-user-id="${item.id}">
                                        ${["basic", "pro", "vip"]
                                          .map((tier) => `<option value="${tier}" ${tier === (item.quota_tier_code || "basic") ? "selected" : ""}>${tier}</option>`)
                                          .join("")}
                                      </select>
                                    </td>
                                    <td>${Number(item.today_tokens || 0).toLocaleString()}</td>
                                    <td>${Number(item.last_7d_tokens || 0).toLocaleString()}</td>
                                    <td>${Number(item.last_30d_tokens || 0).toLocaleString()}</td>
                                    <td><input type="checkbox" class="admin-user-unlimited" data-user-id="${item.id}" ${item.is_unlimited ? "checked" : ""} /></td>
                                  </tr>
                                `,
                              )
                              .join("")
                          : `<tr><td colspan="7" class="muted">暂无用户数据。</td></tr>`
                      }
                    </tbody>
                  </table>
                </div>
              </section>
            `
            : ""
        }
        ${
          section === "chats"
            ? `
              <section class="admin-section">
                <div class="admin-section-header">
                  <div>
                    <h2>聊天记录</h2>
                    <div class="muted">查看历史会话和消息明细。</div>
                  </div>
                </div>
                <div class="admin-chat-filters">
                  <select class="select" id="adminChatUserFilter">
                    <option value="">全部用户</option>
                    ${state.adminUsers
                      .map(
                        (item) => `
                          <option value="${item.id}" ${String(item.id) === String(state.adminChatUserFilter || "") ? "selected" : ""}>
                            ${escapeHtml(item.display_name || "用户")}${item.email ? ` · ${escapeHtml(item.email)}` : ""}
                          </option>
                        `,
                      )
                      .join("")}
                  </select>
                </div>
                <div class="admin-chat-grid">
                  <div class="table-card admin-chat-list">
                    ${
                      state.adminChats.length
                        ? state.adminChats
                            .map(
                              (chat) => `
                                <button class="admin-chat-item ${chat.id === state.adminSelectedChatId ? "active" : ""}" data-admin-chat-id="${chat.id}">
                                  <strong>${escapeHtml(chat.title || "New chat")}</strong>
                                  <div class="muted">${escapeHtml(chat.display_name || "")} · ${escapeHtml(chat.email || "")}</div>
                                  <div class="muted">${formatTime(chat.last_message_at)}</div>
                                </button>
                              `,
                            )
                            .join("")
                        : `<div class="muted">当前区间没有聊天记录。</div>`
                    }
                  </div>
                  <div class="table-card admin-chat-detail">
                    ${
                      state.adminChatMessages.length
                        ? state.adminChatMessages
                            .map(
                              (message) => `
                                <article class="admin-message">
                                  <div class="bubble-header">
                                    <strong>${escapeHtml(message.role)}</strong>
                                    <span>${formatTime(message.created_at)} · ${Number(message.total_tokens || 0).toLocaleString()} tokens</span>
                                  </div>
                                  <div>${renderMarkdownLite(message.content || "")}</div>
                                </article>
                              `,
                            )
                            .join("")
                        : `<div class="muted">选择左侧会话后查看消息内容。</div>`
                    }
                  </div>
                </div>
              </section>
            `
            : ""
        }
      </div>
    </section>
  `;
}

function renderKnowledgeStatus(status) {
  const map = {
    uploaded: "上传中",
    queued: "排队中",
    parsing: "解析中",
    chunking: "解析中",
    embedding: "解析中",
    completed: "已完成",
    failed: "失败",
  };
  const key = status || "queued";
  return `<span class="status-pill status-${escapeHtml(key)}">${escapeHtml(map[key] || key)}</span>`;
}

function renderBoardManagement() {
  return `
    <section class="admin-section">
      <div class="collapsible-card">
        <button class="collapsible-trigger ${state.boardCreateOpen ? "is-open" : ""}" id="boardCreateToggleBtn">
          <span>${state.boardForm.id ? "编辑板型" : "新增板型"}</span>
          <span>${state.boardCreateOpen ? "收起" : "展开"}</span>
        </button>
        ${
          state.boardCreateOpen || state.boardForm.id
            ? `
              <div class="collapsible-body">
                <div class="admin-section-header">
                  <div>
                    <div class="muted">建议编码使用小写加下划线，例如 <code>esp32_s3_wroom_1</code>。</div>
                  </div>
                  ${state.boardForm.id ? `<button class="button button-secondary" id="boardResetBtn">取消编辑</button>` : ""}
                </div>
                <div class="stack">
                  <div class="field">
                    <label for="boardCodeInput">板型编码</label>
                    <input class="input" id="boardCodeInput" value="${escapeHtml(state.boardForm.code)}" placeholder="matouch_esp32s3" />
                  </div>
                  <div class="field">
                    <label for="boardNameInput">板型名称</label>
                    <input class="input" id="boardNameInput" value="${escapeHtml(state.boardForm.name)}" placeholder="MaTouch_ESP32S3" />
                  </div>
                  <div class="field">
                    <label for="boardAliasesInput">别名列表</label>
                    <input class="input" id="boardAliasesInput" value="${escapeHtml(state.boardForm.aliases)}" placeholder="matouch, esp32 s3, wroom-1" />
                  </div>
                  <div class="field">
                    <label for="boardDescriptionInput">描述</label>
                    <textarea class="composer-input form-textarea" id="boardDescriptionInput" placeholder="板型说明">${escapeHtml(state.boardForm.description)}</textarea>
                  </div>
                  <div class="field">
                    <label for="boardHintInput">默认提示语</label>
                    <textarea class="composer-input form-textarea" id="boardHintInput" placeholder="聊天里给用户的引导提示">${escapeHtml(state.boardForm.defaultHint)}</textarea>
                  </div>
                  <label class="checkbox-row">
                    <input type="checkbox" id="boardEnabledInput" ${state.boardForm.isEnabled ? "checked" : ""} />
                    <span>启用该板型</span>
                  </label>
                  <div class="inline-actions">
                    <button class="button" id="boardSaveBtn">${state.boardForm.id ? "保存修改" : "创建板型"}</button>
                  </div>
                </div>
              </div>
            `
            : ""
        }
      </div>
      <div class="table-card">
        <div class="admin-section-header">
          <div>
            <h2>板型列表</h2>
            <div class="muted">所有知识条目都挂在板型下，删除采用软删除。</div>
          </div>
        </div>
        <table class="data-table">
          <thead>
            <tr><th>板型名称</th><th>编码</th><th>别名</th><th>知识数</th><th>状态</th><th>更新时间</th><th>操作</th></tr>
          </thead>
          <tbody>
            ${
              state.boardItems.length
                ? state.boardItems
                    .map(
                      (item) => `
                        <tr>
                          <td>
                            <strong>${escapeHtml(item.name)}</strong>
                            <div class="muted">${escapeHtml(item.description || "")}</div>
                          </td>
                          <td>${escapeHtml(item.code)}</td>
                          <td>${escapeHtml((item.aliases || []).join(", ") || "-")}</td>
                          <td>${Number(item.knowledge_count || 0).toLocaleString()}</td>
                          <td>${item.deleted_at ? '<span class="status-pill status-failed">已删除</span>' : item.is_enabled ? '<span class="status-pill status-completed">启用</span>' : '<span class="status-pill status-queued">停用</span>'}</td>
                          <td>${formatTime(item.updated_at)}</td>
                          <td>
                            <div class="inline-actions">
                              <button class="button button-secondary" data-board-edit="${item.id}">编辑</button>
                              ${item.deleted_at ? "" : `<button class="button button-secondary" data-board-delete="${item.id}">删除</button>`}
                            </div>
                          </td>
                        </tr>
                      `,
                    )
                    .join("")
                : `<tr><td colspan="7" class="muted">暂无板型数据，请先执行知识库迁移 SQL。</td></tr>`
            }
          </tbody>
        </table>
      </div>
    </section>
  `;
}

function renderKnowledgeInput() {
  const activeBoardId = state.selectedBoardId || (state.boardItems[0] ? String(state.boardItems[0].id) : "");
  const boardOptions = state.boardItems
    .filter((item) => !item.deleted_at)
    .map(
      (item) => `<option value="${item.id}" ${String(item.id) === String(activeBoardId) ? "selected" : ""}>${escapeHtml(item.name)}</option>`,
    )
    .join("");

  return `
    <section class="admin-section">
      <div class="table-card">
        <div class="admin-section-header">
          <div>
            <h2>知识录入</h2>
            <div class="muted">先选择板型，再录入 txt、excel、网站正文或直接输入文本。</div>
          </div>
        </div>
        <div class="stack">
          <div class="field">
            <label for="knowledgeBoardSelect">所属板型</label>
            <select class="select" id="knowledgeBoardSelect">
              <option value="">请选择板型</option>
              ${boardOptions}
            </select>
          </div>
          <div class="admin-subnav">
            ${[
              { key: "file", label: "上传文件" },
              { key: "text", label: "直接输入" },
              { key: "website", label: "网站内容" },
            ]
              .map(
                (item) => `
                  <button class="admin-subnav-item ${state.knowledgeInputType === item.key ? "active" : ""}" data-knowledge-input-type="${item.key}">
                    ${item.label}
                  </button>
                `,
              )
              .join("")}
          </div>
          ${
            state.knowledgeInputType === "file"
              ? `
                <div class="field">
                  <label for="knowledgeFileInput">上传 txt / xlsx</label>
                  <input class="input" id="knowledgeFileInput" type="file" accept=".txt,.xlsx,.xlsm,.xltx,.xltm" />
                </div>
                <button class="button" id="knowledgeFileSubmitBtn">上传并入库</button>
              `
              : ""
          }
          ${
            state.knowledgeInputType === "text"
              ? `
                <div class="field">
                  <label for="knowledgeTextTitleInput">知识名称</label>
                  <input class="input" id="knowledgeTextTitleInput" type="text" placeholder="例如：ESP32-S3 I2C 接线说明" />
                </div>
                <div class="field">
                  <label for="knowledgeTextContentInput">正文</label>
                  <textarea class="composer-input form-textarea form-textarea-lg" id="knowledgeTextContentInput" placeholder="直接粘贴知识内容"></textarea>
                </div>
                <button class="button" id="knowledgeTextSubmitBtn">保存文本知识</button>
              `
              : ""
          }
          ${
            state.knowledgeInputType === "website"
              ? `
                <div class="field">
                  <label for="knowledgeWebsiteTitleInput">知识名称</label>
                  <input class="input" id="knowledgeWebsiteTitleInput" type="text" placeholder="例如：官方文档摘录" />
                </div>
                <div class="field">
                  <label for="knowledgeWebsiteUrlInput">网站链接</label>
                  <input class="input" id="knowledgeWebsiteUrlInput" type="url" placeholder="https://example.com/docs/esp32" />
                </div>
                <div class="field">
                  <label for="knowledgeWebsiteContentInput">正文内容</label>
                  <textarea class="composer-input form-textarea form-textarea-lg" id="knowledgeWebsiteContentInput" placeholder="当前阶段先手工粘贴已清洗的网站正文"></textarea>
                </div>
                <button class="button" id="knowledgeWebsiteSubmitBtn">保存网站知识</button>
              `
              : ""
          }
        </div>
      </div>
    </section>
  `;
}

function renderKnowledgeManage() {
  return `
    <section class="admin-section">
      <div class="table-card">
        <div class="admin-section-header">
          <div>
            <h2>知识库管理</h2>
            <div class="muted">当前展示所选板型下的知识条目。Excel/TXT 支持下载源文件。</div>
          </div>
          <div class="knowledge-filter-row">
            <div class="knowledge-filters knowledge-filters-compact">
              <select class="select" id="knowledgeFilterBoardSelect">
                <option value="">全部板型</option>
                ${state.boardItems.map((item) => `<option value="${item.id}" ${String(item.id) === String(state.selectedBoardId) ? "selected" : ""}>${escapeHtml(item.name)}</option>`).join("")}
              </select>
              <select class="select" id="knowledgeFilterTypeSelect">
                <option value="">全部类型</option>
                ${["txt", "excel", "website", "text"].map((item) => `<option value="${item}" ${item === state.knowledgeFilterType ? "selected" : ""}>${escapeHtml(item)}</option>`).join("")}
              </select>
              <select class="select" id="knowledgeFilterStatusSelect">
                <option value="">全部状态</option>
                ${["uploaded", "queued", "parsing", "chunking", "embedding", "completed", "failed"].map((item) => `<option value="${item}" ${item === state.knowledgeFilterStatus ? "selected" : ""}>${escapeHtml(item)}</option>`).join("")}
              </select>
            </div>
          </div>
        </div>
        <table class="data-table">
          <thead>
            <tr><th>知识名称</th><th>知识类型</th><th>状态</th><th>创建时间</th><th>更新时间</th><th>操作</th></tr>
          </thead>
          <tbody>
            ${
              state.knowledgeDocuments.length
                ? state.knowledgeDocuments
                    .map(
                      (item) => `
                        <tr>
                          <td>
                            <strong>${escapeHtml(item.title || item.source_name || "Untitled")}</strong>
                            <div class="muted">${escapeHtml(item.board_name || "")}</div>
                          </td>
                          <td>${escapeHtml(item.knowledge_type || item.source_type || "-")}</td>
                          <td>${renderKnowledgeStatus(item.parse_status)}</td>
                          <td>${formatTime(item.created_at)}</td>
                          <td>${formatTime(item.updated_at)}</td>
                          <td>
                            <div class="inline-actions">
                              ${["txt", "excel"].includes(item.knowledge_type) ? `<a class="button button-secondary inline-link-button" href="/api/admin/knowledge/documents/${item.id}/download">下载源文件</a>` : ""}
                              <button class="button button-secondary" data-knowledge-detail="${item.id}">详情</button>
                              <button class="button button-secondary" data-knowledge-delete="${item.id}">删除</button>
                            </div>
                          </td>
                        </tr>
                      `,
                    )
                    .join("")
                : `<tr><td colspan="6" class="muted">当前筛选下还没有知识条目。</td></tr>`
            }
          </tbody>
        </table>
      </div>
    </section>
  `;
}

function renderKnowledgeDetailModal() {
  if (!state.activeKnowledgeDetail) return "";
  return `
    <div class="modal-backdrop" id="knowledgeDetailBackdrop">
      <div class="modal-panel modal-panel-lg" role="dialog" aria-modal="true" aria-label="知识详情">
        <div class="admin-section-header">
          <div>
            <h2>知识详情</h2>
            <div class="muted">${escapeHtml(state.activeKnowledgeDetail.title || "Untitled")}</div>
          </div>
          <div class="inline-actions">
            <a class="button button-secondary inline-link-button" href="/knowledge/chunks/${state.activeKnowledgeChunks[0]?.id || ""}" target="_blank" rel="noreferrer">新开页查看</a>
            <button class="button button-secondary" id="knowledgeDetailCloseBtn">关闭</button>
          </div>
        </div>
        <div class="stack">
          <div class="detail-grid">
            <div><span class="muted">板型</span><strong>${escapeHtml(state.activeKnowledgeDetail.board_name || "-")}</strong></div>
            <div><span class="muted">类型</span><strong>${escapeHtml(state.activeKnowledgeDetail.knowledge_type || "-")}</strong></div>
            <div><span class="muted">状态</span><strong>${renderKnowledgeStatus(state.activeKnowledgeDetail.parse_status)}</strong></div>
            <div><span class="muted">Chunk 数</span><strong>${Number(state.activeKnowledgeDetail.chunk_count || 0).toLocaleString()}</strong></div>
            <div><span class="muted">Token 估算</span><strong>${Number(state.activeKnowledgeDetail.token_count || 0).toLocaleString()}</strong></div>
            <div><span class="muted">文件名</span><strong>${escapeHtml(state.activeKnowledgeDetail.file_name || "-")}</strong></div>
          </div>
          <div class="field">
            <label>来源</label>
            <div class="detail-box">${escapeHtml(state.activeKnowledgeDetail.source_name || "-")}</div>
          </div>
          ${
            state.activeKnowledgeDetail.source_url
              ? `
                <div class="field">
                  <label>链接</label>
                  <a class="detail-box detail-link" href="${escapeHtml(state.activeKnowledgeDetail.source_url)}" target="_blank" rel="noreferrer">
                    ${escapeHtml(state.activeKnowledgeDetail.source_url)}
                  </a>
                </div>
              `
              : ""
          }
          ${
            state.activeKnowledgeDetail.parse_error
              ? `
                <div class="field">
                  <label>解析提示</label>
                  <div class="detail-box detail-error">${escapeHtml(state.activeKnowledgeDetail.parse_error)}</div>
                </div>
              `
              : ""
          }
          <div class="field">
            <label>元数据</label>
            <pre class="detail-box detail-pre">${escapeHtml(JSON.stringify(state.activeKnowledgeDetail.metadata || {}, null, 2))}</pre>
          </div>
          <div class="field">
            <label>正文预览</label>
            <div class="detail-box detail-preview">${renderMarkdownLite((state.activeKnowledgeDetail.raw_text || "").slice(0, 2400) || "暂无正文预览")}</div>
          </div>
          ${
            state.activeKnowledgeDetail.parse_status === "failed"
              ? `<button class="button" id="knowledgeRetryBtn" data-knowledge-retry="${state.activeKnowledgeDetail.id}">重试解析</button>`
              : ""
          }
          <div class="field">
            <label>Chunk 预览</label>
            <div class="chunk-list">
              ${
                state.activeKnowledgeChunks.length
                  ? state.activeKnowledgeChunks
                      .map(
                        (chunk) => `
                          <article class="job-card">
                            <div class="bubble-header">
                              <strong>Chunk #${Number(chunk.chunk_index || 0) + 1}</strong>
                              <span>${Number(chunk.token_count || 0).toLocaleString()} tokens</span>
                            </div>
                            <div class="detail-box detail-preview">${renderMarkdownLite((chunk.content || "").slice(0, 600))}</div>
                          </article>
                        `,
                      )
                      .join("")
                  : `<div class="muted">当前还没有 chunk 预览。</div>`
              }
            </div>
          </div>
          <div class="field">
            <label>任务历史</label>
            <div class="job-list">
              ${
                state.activeKnowledgeJobs.length
                  ? state.activeKnowledgeJobs
                      .map(
                        (job) => `
                          <article class="job-card">
                            <div class="bubble-header">
                              <strong>${escapeHtml(job.job_type || "ingest")}</strong>
                              <span>${renderKnowledgeStatus(job.status === "succeeded" ? "completed" : job.status === "running" ? "parsing" : job.status || "queued")}</span>
                            </div>
                            <div class="muted">尝试次数：${Number(job.attempt_count || 0)} · 创建时间：${formatTime(job.created_at)}</div>
                            ${job.error_message ? `<div class="detail-box detail-error">${escapeHtml(job.error_message)}</div>` : ""}
                          </article>
                        `,
                      )
                      .join("")
                  : `<div class="muted">当前还没有任务历史。</div>`
              }
            </div>
          </div>
        </div>
      </div>
    </div>
  `;
}

function renderKnowledgeRetrieve() {
  const activeBoardId = state.selectedBoardId || (state.boardItems[0] ? String(state.boardItems[0].id) : "");
  const boardOptions = state.boardItems
    .filter((item) => !item.deleted_at)
    .map(
      (item) => `<option value="${item.id}" ${String(item.id) === String(activeBoardId) ? "selected" : ""}>${escapeHtml(item.name)}</option>`,
    )
    .join("");

  return `
    <section class="admin-section">
      <div class="table-card">
        <div class="admin-section-header">
          <div>
            <h2>检索调试</h2>
            <div class="muted">用于验证当前板型下的 RAG 召回结果，后续聊天链路会复用这套检索。</div>
          </div>
        </div>
        <div class="stack">
          <div class="field">
            <label for="knowledgeRetrieveBoardSelect">检索板型</label>
            <select class="select" id="knowledgeRetrieveBoardSelect">
              <option value="">请选择板型</option>
              ${boardOptions}
            </select>
          </div>
          <div class="field">
            <label for="knowledgeRetrieveQueryInput">问题</label>
            <textarea class="composer-input form-textarea" id="knowledgeRetrieveQueryInput" placeholder="例如：ESP32-S3-WROOM-1 的 I2C 默认引脚是什么？">${escapeHtml(state.retrievalQuery)}</textarea>
          </div>
          <button class="button" id="knowledgeRetrieveBtn">执行检索</button>
          <div class="retrieval-results">
            ${
              state.retrievalResults.length
                ? state.retrievalResults
                    .map(
                      (item, index) => `
                        <article class="retrieval-card">
                          <div class="bubble-header">
                            <strong>#${index + 1} ${escapeHtml(item.title || "Untitled")}</strong>
                            <span>${escapeHtml(item.retrieval_mode || "")} · ${Number(item.score || 0).toFixed(4)}</span>
                          </div>
                          <div>${renderMarkdownLite(item.content || "")}</div>
                        </article>
                      `,
                    )
                    .join("")
                : `<div class="muted">执行一次检索后，这里会显示命中的知识片段。</div>`
            }
          </div>
        </div>
      </div>
    </section>
  `;
}

function renderKnowledge() {
  const tabs = [
    { key: "ingest", label: "知识录入" },
    { key: "manage", label: "知识库管理" },
    { key: "retrieve", label: "检索调试" },
  ];
  return `
    <section class="admin-layout">
      <div class="content-toast-wrap">
        ${renderBanner()}
      </div>
      <div class="admin-scroll">
        <section class="admin-subnav-card">
          <div class="admin-subnav">
            ${tabs
              .map(
                (tab) => `
                  <button class="admin-subnav-item ${tab.key === state.knowledgeSection ? "active" : ""}" data-knowledge-section="${tab.key}">
                    ${tab.label}
                  </button>
                `,
              )
              .join("")}
          </div>
        </section>
        ${state.knowledgeSection === "ingest" ? renderKnowledgeInput() : state.knowledgeSection === "manage" ? renderKnowledgeManage() : renderKnowledgeRetrieve()}
      </div>
    </section>
  `;
}

function renderApp() {
  const activeSession = state.sessions.find((item) => item.id === state.activeSessionId);
  const isAdmin = state.user?.role === "admin";
  const knowledgeTitle =
    state.view === "board"
      ? "板型管理"
      : state.knowledgeSection === "ingest"
        ? "知识录入"
        : state.knowledgeSection === "manage"
          ? "知识库管理"
          : "检索调试";

  app.innerHTML = `
    <div class="app-shell">
      <aside class="sidebar">
        <div class="sidebar-brand">
          <div class="brand-mark">M</div>
          <div>
            <div class="session-title">Makerfabs Agent</div>
            <div class="session-meta">Authenticated workspace</div>
          </div>
        </div>
        <button class="button" id="newChatBtn">+ New Chat</button>

        <div class="sidebar-section-divider"></div>
        <div class="sidebar-heading"><span>Modules</span></div>
        <div class="nav-list">
          <button class="nav-item ${state.view === "chat" ? "active" : ""}" id="chatNavBtn">
            <div class="nav-item-title">Makerfabs Agent</div>
            <div class="nav-item-meta">聊天、Recent、板卡上下文</div>
          </button>
          ${
            isAdmin
              ? `
                <button class="nav-item ${state.view === "board" ? "active" : ""}" id="boardNavBtn">
                  <div class="nav-item-title">板型管理</div>
                  <div class="nav-item-meta">板型、别名、软删除</div>
                </button>
                <button class="nav-item ${state.view === "knowledge" ? "active" : ""}" id="knowledgeNavBtn">
                  <div class="nav-item-title">知识库</div>
                  <div class="nav-item-meta">录入、管理、检索调试</div>
                </button>
                <button class="nav-item ${state.view === "admin" ? "active" : ""}" id="adminNavBtn">
                  <div class="nav-item-title">管理面板</div>
                  <div class="nav-item-meta">用户、用量、邀请码、聊天记录</div>
                </button>
              `
              : ""
          }
        </div>

        <div class="recent-section">
          <div class="sidebar-section-divider"></div>
          <div class="sidebar-heading"><span>Recent</span></div>
          <div class="recent-list-scroll">
            <div class="session-list">
              ${
                state.sessions.length
                  ? state.sessions
                      .map(
                        (session) => `
                          <button class="session-item ${session.id === state.activeSessionId ? "active" : ""}" data-session-id="${session.id}">
                            <div class="session-title">${escapeHtml(session.title || "New chat")}</div>
                            <div class="session-meta">${escapeHtml(session.current_product_model || "未设置产品型号")} · ${formatTime(session.last_message_at)}</div>
                          </button>
                        `,
                      )
                      .join("")
                  : `<div class="nav-item-meta" style="padding: 0 8px">还没有历史会话。</div>`
              }
            </div>
          </div>
        </div>
        <div class="sidebar-footer" id="sidebarFooter">
          ${
            state.userPanelOpen
              ? `
                <div class="user-panel" id="userPanel">
                  <div class="stack">
                    <h3 style="margin: 0">${escapeHtml(state.user.display_name || "用户")}</h3>
                    <div class="muted">${escapeHtml(state.user.email || "")}</div>
                  </div>
                  <div class="usage-grid">
                    ${renderUsageSummary()}
                    ${
                      state.usageItems.length
                        ? state.usageItems
                            .map(
                              (item) => `
                                <div class="usage-row">
                                  <span>${escapeHtml(item.usage_date)}</span>
                                  <strong>${item.total_tokens.toLocaleString()} tokens</strong>
                                </div>
                              `,
                            )
                            .join("")
                        : `<div class="muted">最近 7 天还没有 token 使用记录。</div>`
                    }
                  </div>
                  <div class="actions-row">
                    <button class="button button-secondary" id="profileBtn">Profile</button>
                    <button class="button button-secondary" id="settingsBtn">Settings</button>
                  </div>
                  <div class="actions-row">
                    <button class="button" id="logoutBtn">Logout</button>
                  </div>
                </div>
              `
              : ""
          }
          <button class="user-trigger" id="userTriggerBtn">
            <div class="session-title">${escapeHtml(state.user.display_name || "用户")}</div>
            <div class="session-meta">${escapeHtml(state.user.email || "已登录用户")}</div>
          </button>
        </div>
      </aside>

      <main class="main">
        <header class="topbar">
          <div class="topbar-title">
            <h1>${
              escapeHtml(
                activeSession?.title ||
                  (state.view === "chat" ? "New chat" : state.view === "admin" ? "管理面板" : knowledgeTitle),
              )
            }</h1>
            <div class="topbar-subtitle">
              ${
                state.view === "chat"
                  ? `当前产品型号：${escapeHtml(state.currentProductModel || "未设置")}`
                  : state.view === "admin"
                    ? "邀请码、用户档位、token 统计和聊天记录均在这里管理。"
                    : state.view === "board"
                      ? "维护板型主数据、别名和软删除状态。"
                      : state.knowledgeSection === "ingest"
                        ? "录入 txt、excel、网站正文和手工文本。"
                        : state.knowledgeSection === "manage"
                          ? "查看并维护各板型下的知识条目。"
                          : "验证板型知识库的 RAG 召回结果。"
              }
            </div>
          </div>
          ${
            state.view === "chat"
              ? `
                <div class="topbar-controls">
                  <div class="control">
                    <select class="select" id="productSelect">
                      <option value="">请选择产品型号</option>
                      ${state.productModels
                        .map(
                          (model) => `
                            <option value="${escapeHtml(model)}" ${model === state.currentProductModel ? "selected" : ""}>${escapeHtml(model)}</option>
                          `,
                        )
                        .join("")}
                    </select>
                  </div>
                  <div class="control">
                    <select class="select" id="providerSelect">
                      ${["openai", "deepseek", "claude", "qwen"]
                        .map(
                          (provider) => `
                            <option value="${provider}" ${provider === state.provider ? "selected" : ""}>${provider}</option>
                          `,
                        )
                        .join("")}
                    </select>
                  </div>
                </div>
              `
              : state.view === "admin"
                ? ""
                : ""
          }
        </header>

        ${
          state.view === "chat"
            ? `
              <section class="chat-layout">
                <div class="content-toast-wrap">
                  ${renderBanner()}
                </div>
                <div class="chat-feed">
                  ${renderMessages()}
                </div>
                <div class="composer-shell">
                  <div class="composer-card">
                    <div class="composer-row">
                      <textarea class="composer-input" id="composerInput" placeholder="描述你的需求，例如：帮我写一个 ESP32-S3-WROOM-1 读取 MPU-6050 的示例">${""}</textarea>
                      <button class="button" id="sendBtn" ${state.sending ? "disabled" : ""}>${state.sending ? "生成中" : "发送"}</button>
                    </div>
                    <div class="composer-footer">
                      <span>登录后才能进入聊天界面，当前已经接入 Recent 历史会话。</span>
                      <span>${escapeHtml(state.provider)} ${state.model ? `· ${escapeHtml(state.model)}` : ""}</span>
                    </div>
                  </div>
                </div>
              </section>
            `
            : state.view === "admin"
              ? renderAdmin()
                : state.view === "board"
                  ? renderBoardManagement()
                  : renderKnowledge()
        }
        ${renderKnowledgeDetailModal()}
      </main>
    </div>

  `;

  document.getElementById("newChatBtn")?.addEventListener("click", async () => {
    state.activeSessionId = null;
    state.messages = [];
    state.view = "chat";
    render();
  });

  document.getElementById("chatNavBtn")?.addEventListener("click", () => {
    state.view = "chat";
    render();
  });
  document.getElementById("boardNavBtn")?.addEventListener("click", () => {
    state.view = "board";
    loadKnowledgeData()
      .then(() => render())
      .catch((error) => setMessage("error", error.message));
  });
  document.getElementById("knowledgeNavBtn")?.addEventListener("click", () => {
    state.view = "knowledge";
    loadKnowledgeData()
      .then(() => render())
      .catch((error) => setMessage("error", error.message));
  });
  document.getElementById("adminNavBtn")?.addEventListener("click", () => {
    state.view = "admin";
    loadAdminSection(state.adminSection)
      .then(() => render())
      .catch((error) => setMessage("error", error.message));
  });

  document.querySelectorAll("[data-session-id]").forEach((button) => {
    button.addEventListener("click", () => {
      openSession(button.getAttribute("data-session-id")).catch((error) => setMessage("error", error.message));
    });
  });

  document.getElementById("productSelect")?.addEventListener("change", (event) => {
    state.currentProductModel = event.target.value;
  });
  document.getElementById("providerSelect")?.addEventListener("change", (event) => {
    state.provider = event.target.value;
  });
  document.getElementById("sendBtn")?.addEventListener("click", () => {
    sendMessage().catch((error) => setMessage("error", error.message));
  });
  document.getElementById("composerInput")?.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      sendMessage().catch((error) => setMessage("error", error.message));
    }
  });
  document.getElementById("userTriggerBtn")?.addEventListener("click", () => {
    toggleUserPanel().catch((error) => setMessage("error", error.message));
  });
  document.querySelectorAll("[data-toast-close='true']").forEach((button) => {
    button.addEventListener("click", () => clearMessages());
  });
  document.getElementById("logoutBtn")?.addEventListener("click", () => {
    logout().catch((error) => setMessage("error", error.message));
  });
  document.getElementById("profileBtn")?.addEventListener("click", () => setMessage("success", "Profile 面板下一步会拆成独立弹窗。"));
  document.getElementById("settingsBtn")?.addEventListener("click", () => setMessage("success", "Settings 面板下一步会拆成独立弹窗。"));
  document.getElementById("createInviteBtn")?.addEventListener("click", () => {
    createInviteCode().catch((error) => setMessage("error", error.message));
  });
  document.getElementById("inviteCreateToggleBtn")?.addEventListener("click", () => {
    state.inviteCreateOpen = !state.inviteCreateOpen;
    render();
  });
  document.querySelectorAll("[data-admin-section]").forEach((button) => {
    button.addEventListener("click", () => {
      const section = button.getAttribute("data-admin-section");
      state.adminSelectedChatId = section === "chats" ? state.adminSelectedChatId : null;
      state.adminChatMessages = section === "chats" ? state.adminChatMessages : [];
      loadAdminSection(section, { preserveScroll: false })
        .then(() => render())
        .catch((error) => setMessage("error", error.message));
    });
  });
  document.querySelectorAll("[data-admin-range]").forEach((button) => {
    button.addEventListener("click", () => {
      state.adminRange = button.getAttribute("data-admin-range");
      loadAdminSection(state.adminSection)
        .then(() => render())
        .catch((error) => setMessage("error", error.message));
    });
  });
  document.querySelectorAll(".admin-user-role").forEach((select) => {
    select.addEventListener("change", () => {
      updateAdminUser(Number(select.getAttribute("data-user-id")), { role: select.value }).catch((error) => setMessage("error", error.message));
    });
  });
  document.querySelectorAll(".admin-user-tier").forEach((select) => {
    select.addEventListener("change", () => {
      updateAdminUser(Number(select.getAttribute("data-user-id")), { quota_tier_code: select.value }).catch((error) => setMessage("error", error.message));
    });
  });
  document.querySelectorAll(".admin-user-unlimited").forEach((checkbox) => {
    checkbox.addEventListener("change", () => {
      updateAdminUser(Number(checkbox.getAttribute("data-user-id")), { is_unlimited: checkbox.checked }).catch((error) =>
        setMessage("error", error.message),
      );
    });
  });
  document.querySelectorAll("[data-admin-chat-id]").forEach((button) => {
    button.addEventListener("click", () => {
      openAdminChat(button.getAttribute("data-admin-chat-id")).catch((error) => setMessage("error", error.message));
    });
  });
  document.getElementById("adminChatUserFilter")?.addEventListener("change", (event) => {
    state.adminChatUserFilter = event.target.value;
    state.adminSelectedChatId = null;
    state.adminChatMessages = [];
    loadAdminSection("chats")
      .then(() => render())
      .catch((error) => setMessage("error", error.message));
  });
  document.querySelectorAll("[data-knowledge-section]").forEach((button) => {
    button.addEventListener("click", () => {
      state.knowledgeSection = button.getAttribute("data-knowledge-section");
      render();
    });
  });
  document.getElementById("boardCreateToggleBtn")?.addEventListener("click", () => {
    state.boardCreateOpen = !state.boardCreateOpen;
    render();
  });
  document.querySelectorAll("[data-board-edit]").forEach((button) => {
    button.addEventListener("click", () => {
      const board = state.boardItems.find((item) => String(item.id) === String(button.getAttribute("data-board-edit")));
      if (board) {
        resetBoardForm(board);
        state.boardCreateOpen = true;
        render();
      }
    });
  });
  document.querySelectorAll("[data-board-delete]").forEach((button) => {
    button.addEventListener("click", () => {
      deleteBoard(Number(button.getAttribute("data-board-delete"))).catch((error) => setMessage("error", error.message));
    });
  });
  document.getElementById("boardResetBtn")?.addEventListener("click", () => {
    resetBoardForm();
    state.boardCreateOpen = false;
    render();
  });
  document.getElementById("boardSaveBtn")?.addEventListener("click", () => {
    const action = state.boardForm.id ? updateBoard : createBoard;
    action().catch((error) => setMessage("error", error.message));
  });
  document.querySelectorAll("[data-knowledge-input-type]").forEach((button) => {
    button.addEventListener("click", () => {
      state.knowledgeInputType = button.getAttribute("data-knowledge-input-type");
      render();
    });
  });
  document.getElementById("knowledgeFileSubmitBtn")?.addEventListener("click", () => {
    createKnowledgeFromFile().catch((error) => setMessage("error", error.message));
  });
  document.getElementById("knowledgeTextSubmitBtn")?.addEventListener("click", () => {
    createKnowledgeFromText().catch((error) => setMessage("error", error.message));
  });
  document.getElementById("knowledgeWebsiteSubmitBtn")?.addEventListener("click", () => {
    createKnowledgeFromWebsite().catch((error) => setMessage("error", error.message));
  });
  document.getElementById("knowledgeFilterBoardSelect")?.addEventListener("change", (event) => {
    state.selectedBoardId = event.target.value;
    loadKnowledgeData()
      .then(() => render())
      .catch((error) => setMessage("error", error.message));
  });
  document.getElementById("knowledgeFilterTypeSelect")?.addEventListener("change", (event) => {
    state.knowledgeFilterType = event.target.value;
    loadKnowledgeData()
      .then(() => render())
      .catch((error) => setMessage("error", error.message));
  });
  document.getElementById("knowledgeFilterStatusSelect")?.addEventListener("change", (event) => {
    state.knowledgeFilterStatus = event.target.value;
    loadKnowledgeData()
      .then(() => render())
      .catch((error) => setMessage("error", error.message));
  });
  document.getElementById("knowledgeBoardSelect")?.addEventListener("change", (event) => {
    state.selectedBoardId = event.target.value || state.selectedBoardId;
  });
  document.getElementById("knowledgeRetrieveBoardSelect")?.addEventListener("change", (event) => {
    state.selectedBoardId = event.target.value || state.selectedBoardId;
  });
  document.getElementById("knowledgeRetrieveBtn")?.addEventListener("click", () => {
    runKnowledgeRetrieve().catch((error) => setMessage("error", error.message));
  });
  document.querySelectorAll("[data-knowledge-delete]").forEach((button) => {
    button.addEventListener("click", () => {
      deleteKnowledgeDocument(button.getAttribute("data-knowledge-delete")).catch((error) => setMessage("error", error.message));
    });
  });
  document.querySelectorAll("[data-knowledge-detail]").forEach((button) => {
    button.addEventListener("click", () => {
      openKnowledgeDetail(button.getAttribute("data-knowledge-detail")).catch((error) => setMessage("error", error.message));
    });
  });
  document.getElementById("knowledgeDetailCloseBtn")?.addEventListener("click", () => closeKnowledgeDetail());
  document.getElementById("knowledgeDetailBackdrop")?.addEventListener("click", (event) => {
    if (event.target?.id === "knowledgeDetailBackdrop") {
      closeKnowledgeDetail();
    }
  });
  document.getElementById("knowledgeRetryBtn")?.addEventListener("click", () => {
    const documentId = document.getElementById("knowledgeRetryBtn")?.getAttribute("data-knowledge-retry");
    if (!documentId) return;
    retryKnowledgeDocument(documentId).catch((error) => setMessage("error", error.message));
  });
}

function render() {
  if (state.user && state.user.role !== "admin" && ["admin", "knowledge", "board"].includes(state.view)) {
    state.view = "chat";
  }
  if (!state.user) {
    renderLogin();
    return;
  }
  renderApp();
  scheduleKnowledgePolling();
  if (state.view === "admin") {
    requestAnimationFrame(() => restoreAdminScrollPosition());
  }
}

document.addEventListener("click", (event) => {
  if (!state.userPanelOpen) return;
  const target = event.target;
  if (!(target instanceof Element)) return;
  if (target.closest("#userPanel") || target.closest("#userTriggerBtn")) return;
  state.userPanelOpen = false;
  render();
});

initialize();
