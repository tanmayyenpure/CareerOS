/* =====================================================================
   CareerOS — shared common.js
   Runs on every page. All existing global functions and behavior are
   preserved: toggleFaq(), closeMobile(), window.botQuickReply().
   New in this pass (additive, nothing renamed):
   - window.CareerOS.debounce()   — utility for future search inputs
   - window.showToast()           — lightweight toast notifications
   - hero canvas now respects prefers-reduced-motion and pauses when
     the tab is hidden (perf), instead of running forever off-screen
   - theme toggle now delegates to theme.js's setTheme/getTheme
     instead of duplicating the localStorage read/write
   ===================================================================== */

window.CareerOS = window.CareerOS || {};

/**
 * Basic debounce utility, exposed for any page's search/filter inputs.
 * Usage: input.addEventListener('input', CareerOS.debounce(fn, 300))
 */
window.CareerOS.debounce = function (fn, wait) {
  var t;
  return function () {
    var args = arguments, ctx = this;
    clearTimeout(t);
    t = setTimeout(function () { fn.apply(ctx, args); }, wait || 250);
  };
};

/**
 * Lightweight toast notifications. New feature, additive only —
 * markup is injected on first use so no template changes are needed.
 * window.showToast('Saved!', 'success', 3000)
 */
window.showToast = function (message, type, duration) {
  var container = document.getElementById('toast-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toast-container';
    container.setAttribute('aria-live', 'polite');
    document.body.appendChild(container);
  }
  var toast = document.createElement('div');
  toast.className = 'toast' + (type ? ' ' + type : '');
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(function () {
    toast.classList.add('closing');
    toast.addEventListener('animationend', function () { toast.remove(); }, { once: true });
  }, duration || 3500);
};

(function () {
  "use strict";

  var prefersReducedMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // ── THEME ──
  // theme.js already applied the saved theme before paint. Here we just
  // wire up the toggle button, delegating to theme.js's public API
  // instead of touching localStorage directly (avoids duplicate logic).
  var themeToggle = document.getElementById('themeToggle');
  if (themeToggle) {
    themeToggle.addEventListener('click', function () {
      var current = window.getTheme ? window.getTheme() : document.documentElement.getAttribute('data-theme');
      var next = current === 'dark' ? 'light' : 'dark';
      if (window.setTheme) {
        window.setTheme(next);
      } else {
        document.documentElement.setAttribute('data-theme', next);
      }
    });
  }

  // ── NAVBAR ──
  var navbar = document.getElementById('navbar');
  if (navbar) {
    window.addEventListener('scroll', function () {
      navbar.classList.toggle('scrolled', window.scrollY > 50);
    }, { passive: true });
  }

  // ── HAMBURGER ──
  var hamburger = document.getElementById('hamburger');
  var mobileMenu = document.getElementById('mobileMenu');
  if (hamburger && mobileMenu) {
    hamburger.addEventListener('click', function () {
      hamburger.classList.toggle('open');
      mobileMenu.classList.toggle('open');
      hamburger.setAttribute('aria-expanded', hamburger.classList.contains('open'));
    });
  }
  // Kept as a global function — existing markup may call this directly.
  window.closeMobile = function () {
    if (hamburger && mobileMenu) {
      hamburger.classList.remove('open');
      mobileMenu.classList.remove('open');
      hamburger.setAttribute('aria-expanded', 'false');
    }
  };
  // Close the mobile menu on Escape for keyboard users.
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') window.closeMobile();
  });

  // ── HERO CANVAS (only runs if present) ──
  (function () {
    var canvas = document.getElementById('hero-canvas');
    if (!canvas) return;
    if (prefersReducedMotion) return; // respect reduced-motion: skip the animated particle field entirely

    var ctx = canvas.getContext('2d');
    var W, H, particles = [];
    var COLORS = ['rgba(99,102,241,', 'rgba(6,182,212,', 'rgba(248,113,113,'];
    var rafId = null;
    var running = true;

    function resize() {
      W = canvas.width = window.innerWidth;
      H = canvas.height = window.innerHeight;
    }
    function createParticle() {
      return {
        x: Math.random() * W, y: Math.random() * H,
        vx: (Math.random() - 0.5) * 0.4, vy: (Math.random() - 0.5) * 0.4,
        r: Math.random() * 2 + 1, a: Math.random(), da: Math.random() * 0.005 + 0.002,
        c: COLORS[Math.floor(Math.random() * COLORS.length)]
      };
    }
    function init() {
      resize();
      particles = [];
      for (var i = 0; i < 120; i++) particles.push(createParticle());
    }
    function draw() {
      if (!running) return;
      ctx.clearRect(0, 0, W, H);
      particles.forEach(function (p) {
        p.x += p.vx; p.y += p.vy;
        p.a += p.da;
        if (p.a > 1 || p.a < 0) p.da *= -1;
        if (p.x < 0 || p.x > W) p.vx *= -1;
        if (p.y < 0 || p.y > H) p.vy *= -1;
        ctx.beginPath(); ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
        ctx.fillStyle = p.c + p.a + ')'; ctx.fill();
      });
      particles.forEach(function (p, i) {
        particles.slice(i + 1).forEach(function (q) {
          var d = Math.hypot(p.x - q.x, p.y - q.y);
          if (d < 100) {
            ctx.beginPath(); ctx.moveTo(p.x, p.y); ctx.lineTo(q.x, q.y);
            ctx.strokeStyle = 'rgba(99,102,241,' + (1 - d / 100) * 0.15 + ')';
            ctx.lineWidth = 0.5; ctx.stroke();
          }
        });
      });
      rafId = requestAnimationFrame(draw);
    }
    // Pause when the tab isn't visible — saves battery/CPU for a purely decorative effect.
    document.addEventListener('visibilitychange', function () {
      running = !document.hidden;
      if (running && !rafId) draw();
    });
    window.addEventListener('resize', resize, { passive: true });
    init();
    draw();
  })();

  // ── FADE IN ──
  var fadeEls = document.querySelectorAll('.fade-in');
  var observer = new IntersectionObserver(function (entries) {
    entries.forEach(function (e) {
      if (e.isIntersecting) e.target.classList.add('visible');
    });
  }, { threshold: 0.15 });
  fadeEls.forEach(function (el) { observer.observe(el); });

  // ── FAQ TOGGLE (only matters on faq.html, harmless elsewhere) ──
  // Kept as a global function — existing onclick="toggleFaq(this)" markup calls this directly.
  window.toggleFaq = function (btn) {
    var item = btn.parentElement;
    var isOpen = item.classList.contains('open');
    document.querySelectorAll('.faq-item').forEach(function (i) { i.classList.remove('open'); });
    if (!isOpen) item.classList.add('open');
  };

  // ── SMOOTH SCROLL for in-page anchors ──
  document.querySelectorAll('a[href^="#"]').forEach(function (a) {
    a.addEventListener('click', function (e) {
      var target = document.querySelector(a.getAttribute('href'));
      if (target) {
        e.preventDefault();
        target.scrollIntoView({ behavior: prefersReducedMotion ? 'auto' : 'smooth' });
      }
    });
  });

  // ── FLOATING ROBOT ASSISTANT (present on every page) ──
  (function () {
    var panel = document.getElementById('bot-panel');
    var btn = document.getElementById('bot-btn');
    if (!panel || !btn) return;
    var closeBtn = document.getElementById('bot-close');
    var notif = document.getElementById('bot-notif');
    var introBubble = document.getElementById('bot-intro-bubble');
    var messagesEl = document.getElementById('bot-messages');
    var inputEl = document.getElementById('bot-input');
    var sendEl = document.getElementById('bot-send');
    var isOpen = false, introShown = false;

    setTimeout(function () {
      introBubble.classList.remove('hidden');
      btn.classList.add('wobble');
      setTimeout(function () { btn.classList.remove('wobble'); }, 700);
      setTimeout(function () { if (!isOpen) introBubble.classList.add('hidden'); }, 6000);
    }, 1500);

    function togglePanel() {
      isOpen = !isOpen;
      panel.classList.toggle('open', isOpen);
      btn.setAttribute('aria-expanded', isOpen);
      introBubble.classList.add('hidden');
      notif.style.display = 'none';
      if (isOpen && !introShown) { introShown = true; playIntro(); }
      if (isOpen) inputEl.focus();
    }
    btn.addEventListener('click', togglePanel);
    closeBtn.addEventListener('click', function () {
      isOpen = false;
      panel.classList.remove('open');
      btn.setAttribute('aria-expanded', 'false');
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && isOpen) { isOpen = false; panel.classList.remove('open'); }
    });

    function addMsg(role, text, delay) {
      return new Promise(function (resolve) {
        setTimeout(function () {
          var wrap = document.createElement('div');
          wrap.className = 'bot-msg ' + role;
          if (role === 'bot') {
            wrap.innerHTML = '<div class="bot-mini-avatar">C</div><div class="bot-msg-bubble">' + text + '</div>';
          } else {
            wrap.innerHTML = '<div class="bot-msg-bubble">' + text + '</div>';
          }
          messagesEl.appendChild(wrap);
          messagesEl.scrollTop = messagesEl.scrollHeight;
          resolve();
        }, delay || 0);
      });
    }

    function showTyping(duration) {
      return new Promise(function (resolve) {
        var wrap = document.createElement('div');
        wrap.className = 'bot-typing';
        wrap.id = 'bot-typing-el';
        wrap.innerHTML = '<div class="bot-mini-avatar">C</div><div class="bot-typing-dots"><span></span><span></span><span></span></div>';
        messagesEl.appendChild(wrap);
        messagesEl.scrollTop = messagesEl.scrollHeight;
        setTimeout(function () { wrap.remove(); resolve(); }, duration || 1200);
      });
    }

    async function playIntro() {
      await showTyping(900);
      await addMsg('bot', '👋 Hey there! I\'m <strong>Cara</strong>, your personal guide to CareerOS!');
      await showTyping(1000);
      await addMsg('bot', '🚀 <strong>CareerOS</strong> is an AI-powered career platform built for students, freshers & professionals in India.');
      await showTyping(1100);
      await addMsg('bot', 'Here\'s what you can do here:<br><br>🧠 <strong>AI Life Coach</strong> — chat with our AI anytime for career advice<br>📊 <strong>Skill Gap Analyzer</strong> — find exactly what to learn<br>🎮 <strong>Gamified Roadmaps</strong> — level up with XP & badges<br>📖 <strong>Real Career Stories</strong> — learn from people who made the switch');
      await showTyping(800);
      await addMsg('bot', '💰 Plans start at <strong>₹0</strong> — free forever for basics, or go Pro at just ₹499/mo for unlimited coaching + voice AI!');
      await showTyping(700);
      await addMsg('bot', 'Got any questions? Ask me anything or pick one below 👇');
    }

    var botKB = {
      'what can careeros do': '🧠 CareerOS offers:<br>• <strong>AI Career Coach</strong> — ask anything, anytime<br>• <strong>Skill Gap Analysis</strong> — know exactly what to learn<br>• <strong>Gamified XP Paths</strong> — structured learning with rewards<br>• <strong>Voice AI</strong> — speak your questions (Pro)<br>• <strong>Real career stories</strong> — from people like you!',
      'pricing': '💰 We have 3 plans:<br><br>🆓 <strong>Free (₹0)</strong> — 10 AI chats/day, 1 roadmap, 15 days<br>⭐ <strong>Pro (₹499/mo)</strong> — unlimited coaching, voice AI, all roadmaps<br>👥 <strong>Team (₹1,999/mo)</strong> — 10 users, analytics, custom paths<br><br>No credit card needed to start free!',
      'how does pricing work': '💰 We have 3 plans:<br><br>🆓 <strong>Free (₹0)</strong> — 10 AI chats/day, 1 roadmap, 15 days<br>⭐ <strong>Pro (₹499/mo)</strong> — unlimited coaching, voice AI, all roadmaps<br>👥 <strong>Team (₹1,999/mo)</strong> — 10 users, analytics, custom paths<br><br>No credit card needed to start free!',
      'get started': '🎯 Getting started is easy!<br><br>1️⃣ Click <strong>"Get Started Free"</strong> in the top navbar<br>2️⃣ Or scroll to the <strong>AI Chat section</strong> on the home page<br>3️⃣ Ask your first career question — no sign-up needed to try!',
      'how do i get started': '🎯 Getting started is easy!<br><br>1️⃣ Click <strong>"Get Started Free"</strong> in the top navbar<br>2️⃣ Or scroll to the <strong>AI Chat section</strong> on the home page<br>3️⃣ Ask your first career question — no sign-up needed to try!',
      'ai coach': '🤖 The <strong>AI Career Coach</strong> is the heart of CareerOS!<br><br>• Ask anything — career switch, resume, salary, interviews<br>• Gives <strong>personalized</strong> advice based on your situation<br>• Supports <strong>voice input</strong> (speak your question in Indian English)<br>• Available 24/7 — no booking, no waiting',
      'tell me about the ai coach': '🤖 The <strong>AI Career Coach</strong> is the heart of CareerOS!<br><br>• Ask anything — career switch, resume, salary, interviews<br>• Gives <strong>personalized</strong> advice based on your situation<br>• Supports <strong>voice input</strong> (speak your question in Indian English)<br>• Available 24/7 — no booking, no waiting'
    };

    function getBotReply(q) {
      var lq = q.toLowerCase().trim();
      for (var key in botKB) {
        if (botKB.hasOwnProperty(key) && (lq.indexOf(key) !== -1 || key.indexOf(lq) !== -1)) return botKB[key];
      }
      if (/hi|hello|hey/.test(lq)) return "👋 Hello! I'm Cara, the CareerOS guide. Ask me about features, pricing, or how to get started!";
      if (/free|trial/.test(lq)) return "🆓 Yes! CareerOS is free to start — no credit card needed. Click <strong>Get Started Free</strong> in the navbar!";
      return "🤔 Great question! The <strong>AI Coach</strong> on the home page can help. Want me to tell you more about any specific feature?";
    }
    // getBotReply() is kept available but unused by default, in case a future
    // pass wants an offline fallback — behavior below is unchanged from before.

    async function botReply(q) {
      await showTyping(600);
      var reply;
      try {
        var res = await fetch('/api/chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ question: q })
        });
        var data = await res.json();
        reply = data.error ? '❌ ' + data.error : data.output;
      } catch (e) {
        reply = '❌ Failed to connect to Flask.';
      }
      await addMsg('bot', reply);
    }

    function botQuickReply(text) { addMsg('user', text); botReply(text); }
    window.botQuickReply = botQuickReply;

    async function botSend() {
      var val = inputEl.value.trim();
      if (!val) return;
      inputEl.value = '';
      await addMsg('user', val);
      await botReply(val);
    }
    sendEl.addEventListener('click', botSend);
    inputEl.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') { e.preventDefault(); botSend(); }
    });
  })();
})();
