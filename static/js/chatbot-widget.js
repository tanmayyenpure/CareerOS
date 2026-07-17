// ── CHATBOT WIDGET LOGIC ──
// Wires up #bot-launcher / #bot-panel to the /api/chat endpoint.
// Safe to include on every page — it no-ops if the widget isn't present.
//
// NOTE: common.js also wires up these same #bot-* ids (its own
// "FLOATING ROBOT ASSISTANT" section). If a page loads both scripts,
// only the one that runs first will attach — the guard below prevents
// double listeners (double sends, duplicate messages) rather than
// silently letting both bind to the same buttons.
(function () {
  if (window.__botWidgetInitialized) return;

  const btn = document.getElementById('bot-btn');
  const panel = document.getElementById('bot-panel');
  const closeBtn = document.getElementById('bot-close');
  const introBubble = document.getElementById('bot-intro-bubble');
  const notif = document.getElementById('bot-notif');
  const messagesEl = document.getElementById('bot-messages');
  const inputEl = document.getElementById('bot-input');
  const sendBtn = document.getElementById('bot-send');

  // If this page doesn't include the widget partial, do nothing.
  if (!btn || !panel || !messagesEl || !inputEl || !sendBtn) return;

  window.__botWidgetInitialized = true;

  let greeted = false;

  function openPanel() {
    panel.classList.add('open');
    if (introBubble) introBubble.classList.add('hidden');
    if (notif) notif.style.display = 'none';
    if (!greeted) {
      addMessage("Hi! I'm Cara. Ask me anything — about CareerOS or otherwise.", 'bot');
      greeted = true;
    }
    inputEl.focus();
  }

  function closePanel() {
    panel.classList.remove('open');
  }

  btn.addEventListener('click', () => {
    panel.classList.contains('open') ? closePanel() : openPanel();
  });
  if (closeBtn) closeBtn.addEventListener('click', closePanel);
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && panel.classList.contains('open')) closePanel();
  });

  function addMessage(text, sender) {
    const msg = document.createElement('div');
    msg.className = 'bot-msg ' + sender;

    if (sender === 'bot') {
      const avatar = document.createElement('div');
      avatar.className = 'bot-mini-avatar';
      avatar.textContent = 'C';
      msg.appendChild(avatar);
    }

    const bubble = document.createElement('div');
    bubble.className = 'bot-msg-bubble';
    bubble.textContent = text;
    msg.appendChild(bubble);

    messagesEl.appendChild(msg);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function showTyping() {
    const typing = document.createElement('div');
    typing.className = 'bot-typing';
    typing.id = 'bot-typing-indicator';
    typing.innerHTML =
      '<div class="bot-mini-avatar">C</div>' +
      '<div class="bot-typing-dots"><span></span><span></span><span></span></div>';
    messagesEl.appendChild(typing);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function hideTyping() {
    const typing = document.getElementById('bot-typing-indicator');
    if (typing) typing.remove();
  }

  let sending = false;

  async function sendMessage(prefilledText) {
    const question = (prefilledText !== undefined ? prefilledText : inputEl.value).trim();
    if (!question || sending) return;

    sending = true;
    sendBtn.disabled = true;

    addMessage(question, 'user');
    inputEl.value = '';
    showTyping();

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question })
      });
      const data = await res.json();
      hideTyping();

      if (data.output) {
        addMessage(data.output, 'bot');
      } else {
        addMessage(data.error || "Something went wrong on my end. Try again in a moment.", 'bot');
      }
    } catch (err) {
      hideTyping();
      addMessage("I couldn't reach the server. Check your connection and try again.", 'bot');
    } finally {
      sending = false;
      sendBtn.disabled = false;
    }
  }

  sendBtn.addEventListener('click', () => sendMessage());
  inputEl.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      sendMessage();
    }
  });

  // Called directly by the onclick="" on each .bot-qr button in _chatbot_widget.html
  window.botQuickReply = function (text) {
    openPanel();
    sendMessage(text);
  };
})();
