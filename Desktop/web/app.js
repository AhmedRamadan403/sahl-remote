'use strict';

(() => {
  const byId = (id) => document.getElementById(id);
  const ui = {
    form: byId('pair-form'), code: byId('pair-code'), name: byId('device-name'),
    connect: byId('connect-button'), message: byId('connection-message'), cancel: byId('cancel-connect'),
    intro: byId('intro'), connectCard: byId('connect-card'), steps: byId('how-it-works'),
    session: byId('session'), host: byId('host-name'), description: byId('session-description'),
    viewport: byId('screen-viewport'), canvas: byId('screen'), placeholder: byId('frame-placeholder'),
    viewOnly: byId('view-only-label'), controls: byId('input-controls'), control: byId('control-toggle'),
    controlTitle: byId('control-title'), controlSubtitle: byId('control-subtitle'),
    drag: byId('drag-toggle'), dragState: byId('drag-state'), text: byId('remote-text'), notice: byId('input-notice'),
    stream: byId('stream-status'), size: byId('screen-size'), fps: byId('frame-stat'), fullscreen: byId('fullscreen-button')
  };
  const context = ui.canvas.getContext('2d', { alpha: false });
  const state = {
    socket: null, phase: 'idle', enabled: false, paused: false, drag: false, frameWidth: 1280, frameHeight: 720,
    heldButtons: new Set(), heldKeys: new Set(), pointer: null, nextMove: null, moveTimer: null,
    lastMoveAt: 0, latestFrame: null, decoding: false, generation: 0, frames: 0, hasFrame: false,
    heartbeat: null, watchdog: null, lastMessageAt: 0, noticeTimer: null, pairTimer: null
  };
  const modifierCodes = { 'ctrl-toggle': 'ControlLeft', 'alt-toggle': 'AltLeft', 'shift-toggle': 'ShiftLeft' };
  const validKey = /^(?:Key[A-Z]|Digit[0-9]|Numpad[0-9]|F(?:[1-9]|1[0-2])|Arrow(?:Up|Down|Left|Right)|Backspace|Tab|Enter|Escape|Space|Delete|Insert|Home|End|PageUp|PageDown|CapsLock|NumLock|ScrollLock|ShiftLeft|ShiftRight|ControlLeft|ControlRight|AltLeft|AltRight|MetaLeft|MetaRight|Minus|Equal|BracketLeft|BracketRight|Backslash|Semicolon|Quote|Backquote|Comma|Period|Slash|NumpadAdd|NumpadSubtract|NumpadMultiply|NumpadDivide|NumpadDecimal|NumpadEnter)$/;
  const digits = (value) => value.replace(/[٠-٩]/g, c => String(c.charCodeAt(0) - 0x660)).replace(/[۰-۹]/g, c => String(c.charCodeAt(0) - 0x6f0)).replace(/\D/g, '').slice(0, 8);
  ui.name.value = /Android|iPhone|iPad|Mobile/i.test(navigator.userAgent) ? 'الموبايل' : 'المتصفح';
  // QR/manual desktop lookup carries the short-lived code only in the fragment.
  // Remove it from the address bar immediately; it is never sent in HTTP URLs.
  const pairingFragment = new URLSearchParams(location.hash.slice(1));
  const incomingCode = pairingFragment.get('code') || '';
  if (pairingFragment.get('v') === '1' && /^[0-9]{8}$/.test(incomingCode)) {
    ui.code.value = incomingCode;
    history.replaceState(null, '', location.pathname + location.search);
  }

  function send(payload) {
    if (!state.socket || state.socket.readyState !== WebSocket.OPEN) return false;
    // Avoid building a queue of stale pointer updates on a slow connection.
    if (payload.type === 'move' && state.socket.bufferedAmount > 65536) return false;
    state.socket.send(JSON.stringify(payload));
    return true;
  }

  function canControl() { return state.phase === 'approved' && !state.paused && state.enabled && state.hasFrame; }

  function showMessage(text, kind = '') {
    ui.message.textContent = text;
    ui.message.className = `connection-message ${kind}`;
    ui.message.hidden = !text;
  }

  function notify(text) {
    clearTimeout(state.noticeTimer);
    ui.notice.textContent = text;
    state.noticeTimer = setTimeout(() => { ui.notice.textContent = ''; }, 4000);
  }

  function clearMove() {
    clearTimeout(state.moveTimer);
    state.moveTimer = null;
    state.nextMove = null;
  }

  function releaseInputs() {
    clearMove();
    if (state.phase === 'approved') send({ type: 'release' });
    state.heldButtons.clear();
    state.heldKeys.clear();
    if (state.pointer) {
      try { ui.viewport.releasePointerCapture(state.pointer.id); } catch (_) { /* Capture may already be gone. */ }
    }
    state.pointer = null;
    for (const id of Object.keys(modifierCodes)) byId(id).setAttribute('aria-pressed', 'false');
  }

  function enableControl(enabled) {
    releaseInputs();
    state.enabled = Boolean(enabled && state.phase === 'approved' && !state.paused && state.hasFrame);
    ui.control.setAttribute('aria-pressed', String(state.enabled));
    ui.controlTitle.textContent = state.enabled ? 'التحكم شغّال' : 'التحكم مقفول';
    ui.controlSubtitle.textContent = state.enabled ? 'لمساتك والكيبورد وصلوا لجهازك' : 'تقدر تشوف الشاشة فقط';
    ui.controls.disabled = !state.enabled;
    ui.viewport.classList.toggle('control-active', state.enabled);
    ui.viewOnly.hidden = state.enabled;
    ui.description.textContent = state.enabled ? 'متصل · التحكم شغّال' : 'متصل · عرض الشاشة فقط';
    if (!state.enabled) setDrag(false);
    else ui.viewport.focus({ preventScroll: true });
  }

  function setDrag(enabled) {
    releaseInputs();
    state.drag = Boolean(enabled);
    ui.drag.setAttribute('aria-pressed', String(state.drag));
    ui.dragState.textContent = state.drag ? 'شغّال' : 'مقفول';
  }

  function resetDisplay() {
    state.paused = false;
    state.hasFrame = false;
    state.frames = 0;
    state.latestFrame = null;
    ui.canvas.classList.remove('has-frame');
    context.clearRect(0, 0, ui.canvas.width, ui.canvas.height);
    ui.placeholder.hidden = false;
    ui.stream.textContent = 'في انتظار الصورة';
    ui.fps.textContent = '— fps';
    ui.control.disabled = true;
  }

  function showPairing() {
    document.body.classList.remove('in-session');
    ui.session.hidden = true;
    ui.intro.hidden = false;
    ui.connectCard.hidden = false;
    ui.steps.hidden = false;
  }

  function endSession(message = 'الجلسة انتهت. تقدر تتصل من جديد برمز الكمبيوتر.', kind = '') {
    enableControl(false);
    clearTimeout(state.pairTimer);
    clearInterval(state.heartbeat);
    clearInterval(state.watchdog);
    state.heartbeat = state.watchdog = null;
    state.phase = 'idle';
    state.generation += 1;
    const socket = state.socket;
    state.socket = null;
    if (socket && socket.readyState < WebSocket.CLOSING) socket.close(1000, 'Viewer disconnected');
    ui.form.hidden = false;
    ui.connect.disabled = false;
    ui.cancel.hidden = true;
    resetDisplay();
    showPairing();
    showMessage(message, kind);
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
  }

  function startSession(message) {
    clearTimeout(state.pairTimer);
    state.phase = 'approved';
    state.frameWidth = Number(message.width) || 1280;
    state.frameHeight = Number(message.height) || 720;
    ui.host.textContent = String(message.host || 'الكمبيوتر');
    ui.size.textContent = `${state.frameWidth} × ${state.frameHeight}`;
    document.body.classList.add('in-session');
    ui.session.hidden = false;
    ui.intro.hidden = true;
    ui.connectCard.hidden = true;
    ui.steps.hidden = true;
    ui.cancel.hidden = true;
    ui.code.value = '';
    enableControl(false);
    ui.session.scrollIntoView({ block: 'start', behavior: 'auto' });
  }

  async function drawFrames() {
    if (state.decoding) return;
    state.decoding = true;
    try {
      while (state.latestFrame) {
        const pending = state.latestFrame;
        state.latestFrame = null;
        let bitmap;
        try {
          bitmap = await createImageBitmap(pending.blob);
          if (pending.generation !== state.generation || state.phase !== 'approved' || state.paused) continue;
          if (bitmap.width > 16384 || bitmap.height > 16384 || bitmap.width * bitmap.height > 64000000) continue;
          if (ui.canvas.width !== bitmap.width || ui.canvas.height !== bitmap.height) {
            ui.canvas.width = bitmap.width;
            ui.canvas.height = bitmap.height;
          }
          state.frameWidth = bitmap.width;
          state.frameHeight = bitmap.height;
          context.drawImage(bitmap, 0, 0);
          state.frames += 1;
          if (!state.hasFrame) {
            state.hasFrame = true;
            ui.canvas.classList.add('has-frame');
            ui.placeholder.hidden = true;
            ui.control.disabled = false;
            ui.stream.textContent = 'عرض مباشر';
          }
          ui.size.textContent = `${bitmap.width} × ${bitmap.height}`;
        } catch (_) {
          if (pending.generation === state.generation) ui.stream.textContent = 'في انتظار صورة سليمة…';
        } finally {
          if (bitmap) bitmap.close();
        }
      }
    } finally { state.decoding = false; }
  }

  ui.code.addEventListener('input', () => { ui.code.value = digits(ui.code.value); ui.code.removeAttribute('aria-invalid'); });
  ui.form.addEventListener('submit', event => {
    event.preventDefault();
    if (state.phase !== 'idle') return;
    let code = digits(ui.code.value);
    if (code.length !== 8) {
      ui.code.setAttribute('aria-invalid', 'true');
      showMessage('اكتب رمز الاتصال كامل: 8 أرقام من نافذة الكمبيوتر.', 'error');
      ui.code.focus();
      return;
    }
    if (location.protocol !== 'https:') {
      showMessage('افتح رابط HTTPS الظاهر في نافذة سهل ريموت على الكمبيوتر عشان يبدأ الاتصال الآمن.', 'error');
      return;
    }
    if (typeof createImageBitmap !== 'function') {
      showMessage('المتصفح ده مش بيدعم عرض الشاشة. افتح الرابط في إصدار حديث من Chrome أو Edge أو Safari.', 'error');
      return;
    }
    resetDisplay();
    showMessage('بنوصّل بالكمبيوتر…', 'waiting');
    state.phase = 'connecting';
    ui.connect.disabled = true;
    ui.form.hidden = true;
    ui.cancel.hidden = false;
    const generation = ++state.generation;
    let socket;
    try { socket = new WebSocket(`wss://${location.host}/ws`); }
    catch (_) { endSession('تعذّر بدء الاتصال. افتح رابط الكمبيوتر تاني وحاول من جديد.', 'error'); return; }
    state.socket = socket;
    socket.binaryType = 'blob';
    state.lastMessageAt = Date.now();
    state.pairTimer = setTimeout(() => {
      if (state.phase !== 'approved' && state.socket === socket) endSession('انتهى وقت الانتظار. شوف نافذة الكمبيوتر وحاول تاني.', 'error');
    }, 120000);
    socket.addEventListener('open', () => {
      if (state.socket !== socket) return;
      send({ type: 'pair', code, name: ui.name.value.trim().slice(0, 48) || 'المتصفح' });
      code = '';
      ui.code.value = '';
      state.heartbeat = setInterval(() => send({ type: 'ping' }), 10000);
      state.watchdog = setInterval(() => {
        if (Date.now() - state.lastMessageAt > 45000) endSession('الاتصال توقف. اتأكد إن الكمبيوتر صاحي وإنكم على نفس الشبكة، واتصل من جديد.', 'error');
      }, 10000);
    });
    socket.addEventListener('message', event => {
      if (state.socket !== socket) return;
      state.lastMessageAt = Date.now();
      if (event.data instanceof Blob) {
        if (state.phase !== 'approved' || event.data.size > 16000000) return;
        state.latestFrame = { blob: event.data, generation };
        void drawFrames();
        return;
      }
      let message;
      try { message = JSON.parse(event.data); } catch (_) { return; }
      if (!message || typeof message !== 'object') return;
      if (message.type === 'waiting') {
        if (state.phase !== 'approved') {
          state.phase = 'waiting';
          showMessage('طلبك وصل. وافق على الاتصال من نافذة سهل ريموت على الكمبيوتر.', 'waiting');
        }
      } else if (message.type === 'approved') {
        if (state.phase === 'connecting' || state.phase === 'waiting') startSession(message);
      } else if (message.type === 'paused' && state.phase === 'approved') {
        state.paused = true;
        enableControl(false);
        ui.control.disabled = true;
        ui.description.textContent = String(message.message || 'بانتظار رجوع سطح المكتب');
        ui.viewOnly.textContent = 'بانتظار نافذة الصلاحيات · متصل';
      } else if (message.type === 'resumed' && state.phase === 'approved') {
        state.paused = false;
        enableControl(false);
        ui.control.disabled = !state.hasFrame;
        ui.viewOnly.textContent = 'عرض فقط — فعّل التحكم من الشريط';
      } else if (message.type === 'notice' && state.phase === 'approved') {
        enableControl(false);
        ui.description.textContent = String(message.message || 'ويندوز منع أمر التحكم مؤقتًا.');
      } else if (message.type === 'error') {
        endSession(String(message.message || 'تعذّر الاتصال. راجع الرمز وحاول من جديد.'), 'error');
      } else if (message.type === 'ended') {
        endSession(String(message.message || 'الكمبيوتر أنهى الجلسة.'));
      }
    });
    socket.addEventListener('error', () => {
      if (state.socket === socket) endSession('مش قادرين نوصل للكمبيوتر. راجع نفس شبكة الواي فاي ورابط الاتصال الظاهر في نافذة سهل ريموت.', 'error');
    });
    socket.addEventListener('close', () => {
      if (state.socket === socket) endSession('الاتصال اتقفل. تقدر تتصل من جديد برمز الكمبيوتر.', 'error');
    });
  });

  ui.cancel.addEventListener('click', () => endSession('تم إلغاء طلب الاتصال.'));
  byId('disconnect-button').addEventListener('click', () => endSession('أنهيت الجلسة. تقدر تتصل تاني في أي وقت.'));
  ui.control.addEventListener('click', () => enableControl(!state.enabled));
  ui.drag.addEventListener('click', () => { if (canControl()) setDrag(!state.drag); });

  // CSS object-fit: contain adds letterboxing. Coordinates refer to the visible image, not the canvas box.
  function position(event, clamp = false) {
    const rect = ui.canvas.getBoundingClientRect();
    const scale = Math.min(rect.width / state.frameWidth, rect.height / state.frameHeight);
    if (!scale) return null;
    const width = state.frameWidth * scale;
    const height = state.frameHeight * scale;
    const x = (event.clientX - rect.left - (rect.width - width) / 2) / width;
    const y = (event.clientY - rect.top - (rect.height - height) / 2) / height;
    if (!clamp && (x < 0 || y < 0 || x > 1 || y > 1)) return null;
    return { x: Math.max(0, Math.min(1, x)), y: Math.max(0, Math.min(1, y)) };
  }

  function move(point, immediate = false) {
    if (!point || !canControl()) return;
    if (immediate) {
      clearMove();
      send({ type: 'move', ...point });
      state.lastMoveAt = performance.now();
      return;
    }
    state.nextMove = point;
    if (state.moveTimer) return;
    const delay = Math.max(0, 33 - (performance.now() - state.lastMoveAt));
    state.moveTimer = setTimeout(() => {
      state.moveTimer = null;
      if (state.nextMove && canControl()) {
        send({ type: 'move', ...state.nextMove });
        state.lastMoveAt = performance.now();
      }
      state.nextMove = null;
    }, delay);
  }

  function button(name, down) {
    if (!canControl()) return;
    if (down) state.heldButtons.add(name); else state.heldButtons.delete(name);
    send({ type: 'button', button: name, down });
  }
  function click(name) { if (canControl()) { button(name, true); button(name, false); } }
  const pointerButton = event => ({ 0: 'left', 1: 'middle', 2: 'right' })[event.button];

  ui.viewport.addEventListener('pointerdown', event => {
    if (!canControl() || state.pointer || !event.isPrimary) return;
    const point = position(event);
    if (!point) return;
    event.preventDefault();
    ui.viewport.focus({ preventScroll: true });
    const touch = event.pointerType !== 'mouse';
    const name = touch ? 'left' : pointerButton(event);
    if (!name) return;
    move(point, true);
    state.pointer = { id: event.pointerId, name, touch, down: !touch || state.drag, startX: event.clientX, startY: event.clientY, started: performance.now(), moved: false };
    if (state.pointer.down) button(name, true);
    ui.viewport.setPointerCapture(event.pointerId);
  });
  ui.viewport.addEventListener('pointermove', event => {
    if (!canControl()) return;
    const pointer = state.pointer;
    if (pointer && event.pointerId !== pointer.id) return;
    if (pointer) {
      if (Math.hypot(event.clientX - pointer.startX, event.clientY - pointer.startY) > 9) pointer.moved = true;
      move(position(event, true));
      event.preventDefault();
    } else if (event.pointerType === 'mouse') move(position(event));
  });
  ui.viewport.addEventListener('pointerup', event => {
    const pointer = state.pointer;
    if (!pointer || event.pointerId !== pointer.id) return;
    event.preventDefault();
    move(position(event, true), true);
    if (pointer.down) button(pointer.name, false);
    else if (pointer.touch && !pointer.moved && performance.now() - pointer.started < 650) click('left');
    state.pointer = null;
    try { ui.viewport.releasePointerCapture(event.pointerId); } catch (_) { /* Already released. */ }
  });
  const cancelPointer = event => {
    if (state.pointer && event.pointerId === state.pointer.id) releaseInputs();
  };
  ui.viewport.addEventListener('pointercancel', cancelPointer);
  ui.viewport.addEventListener('lostpointercapture', cancelPointer);
  ui.viewport.addEventListener('contextmenu', event => { if (state.enabled) event.preventDefault(); });
  ui.viewport.addEventListener('wheel', event => {
    if (!canControl() || !position(event)) return;
    event.preventDefault();
    move(position(event), true);
    const scale = event.deltaMode === 1 ? 3 : event.deltaMode === 2 ? 1 : 100;
    const magnitude = Math.min(10, Math.max(1, Math.round(Math.abs(event.deltaY) / scale)));
    // Win32 wheel direction: positive scrolls up, opposite to browser deltaY.
    if (event.deltaY) send({ type: 'scroll', delta: -Math.sign(event.deltaY) * magnitude });
  }, { passive: false });

  byId('left-click').addEventListener('click', () => click('left'));
  byId('right-click').addEventListener('click', () => click('right'));
  byId('scroll-up').addEventListener('click', () => { if (canControl()) send({ type: 'scroll', delta: 3 }); });
  byId('scroll-down').addEventListener('click', () => { if (canControl()) send({ type: 'scroll', delta: -3 }); });

  function key(code, down) {
    if (!canControl() || !validKey.test(code)) return;
    if (down) state.heldKeys.add(code); else state.heldKeys.delete(code);
    send({ type: 'key', key: code, down });
  }
  function tapKey(code) { key(code, true); key(code, false); }
  for (const [id, code] of Object.entries(modifierCodes)) {
    byId(id).addEventListener('click', () => {
      if (!canControl()) return;
      const down = !state.heldKeys.has(code);
      key(code, down);
      byId(id).setAttribute('aria-pressed', String(down));
    });
  }
  document.querySelectorAll('[data-key]').forEach(element => element.addEventListener('click', () => {
    if (canControl()) { tapKey(element.dataset.key); ui.viewport.focus({ preventScroll: true }); }
  }));
  ui.viewport.addEventListener('keydown', event => {
    if (!canControl() || event.isComposing || !validKey.test(event.code)) return;
    event.preventDefault();
    if (!event.repeat) key(event.code, true);
  });
  window.addEventListener('keyup', event => {
    if (!state.heldKeys.has(event.code)) return;
    event.preventDefault();
    key(event.code, false);
    for (const [id, code] of Object.entries(modifierCodes)) if (code === event.code) byId(id).setAttribute('aria-pressed', 'false');
  });
  ui.viewport.addEventListener('blur', () => releaseInputs());
  ui.text.addEventListener('focus', () => releaseInputs());
  byId('send-text').addEventListener('click', () => {
    if (!canControl()) return;
    const text = ui.text.value.slice(0, 500);
    if (!text) return;
    releaseInputs();
    send({ type: 'text', text });
    ui.text.value = '';
    notify('النص اتبعت للكمبيوتر.');
  });

  window.addEventListener('blur', () => { if (state.phase === 'approved') enableControl(false); });
  document.addEventListener('visibilitychange', () => {
    if (document.hidden && state.phase === 'approved') enableControl(false);
  });
  window.addEventListener('pagehide', () => {
    releaseInputs();
    if (state.socket) state.socket.close(1000, 'Page closed');
  });

  ui.fullscreen.addEventListener('click', async () => {
    releaseInputs();
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else if (byId('viewer-layout').requestFullscreen) await byId('viewer-layout').requestFullscreen();
      else notify('استخدم الوضع الأفقي أو ملء الشاشة من قائمة المتصفح.');
    } catch (_) { notify('استخدم الوضع الأفقي أو ملء الشاشة من قائمة المتصفح.'); }
  });
  document.addEventListener('fullscreenchange', () => {
    ui.fullscreen.innerHTML = document.fullscreenElement ? '⤢ <span>خروج</span>' : '⛶ <span>ملء الشاشة</span>';
    releaseInputs();
  });
  setInterval(() => {
    if (state.phase === 'approved') {
      ui.fps.textContent = `${state.frames} fps`;
      if (state.paused) ui.stream.textContent = 'ويندوز يعرض شاشة محمية · الاتصال مستمر';
      else if (state.hasFrame) ui.stream.textContent = state.frames ? 'عرض مباشر' : 'في انتظار تحديث الشاشة';
    }
    state.frames = 0;
  }, 1000);
  if (pairingFragment.get('v') === '1' && /^[0-9]{8}$/.test(incomingCode)) {
    // The desktop Connect button or a scanned QR already expressed pairing intent.
    // The host must still approve the request before any screen/input access.
    setTimeout(() => ui.form.requestSubmit(), 0);
  }
})();
