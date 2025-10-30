// static/js/chatbot.js
// Merged version: JWT-secure chat, KYC prompts, notifications, and simple JSON-paste support.

(async function () {
  const backendURL = window.backendURL || 'https://safihash.onrender.com';

  // Helpers
  function el(sel) { return document.querySelector(sel); }

  function appendMessage(cssClass, text) {
    const chatBox = document.querySelector('#chat-box');
    if (!chatBox) return;
    const div = document.createElement('div');
    div.className = `chat-message ${cssClass}`;
    if (cssClass === 'bot') div.innerHTML = text;       // ⬅️ allow links
    else div.innerText = text;                          // user text stays safe
    chatBox.appendChild(div);
    chatBox.scrollTop = chatBox.scrollHeight;
  }

// ---------------- Session / User ----------------
async function checkSession() {
  const token = localStorage.getItem('jwt_token');
  console.log("🔑 DEBUG (checkSession): jwt_token in localStorage =", token);   // ⬅️ DEBUG

  if (!token) {
    alert('Please login first.');
    window.location.href = '/api/users/auth';
    return null;
  }

  try {
    const res = await fetch((backendURL || '') + '/api/users/me', {
      method: 'GET',
      headers: { 'Authorization': `Bearer ${token}` }
    });

    if (!res.ok) {
      localStorage.removeItem('jwt_token');
      alert('Session expired. Please login again.');
      window.location.href = '/api/users/auth';
      return null;
    }

    const user = await res.json();
    console.log("👤 DEBUG (checkSession): logged-in user =", user);   // ⬅️ DEBUG

    window.loggedInUserId = user.id;
    el('.card-header').innerHTML = 
      `🆔 Hedera ID - <span class="text-warning">${user.username}</span>`;

    // Load notifications after session validated
    fetchNotifications(window.loggedInUserId).catch(err => console.warn('fetchNotifications failed', err));
    return user;
  } catch (err) {
    console.error('Session check failed', err);
    alert('Unable to verify session. Please login.');
    window.location.href = '/api/users/auth';
    return null;
  }
}
  // ---------------- Notifications ----------------
  async function fetchNotifications(userId) {
    if (!userId) return;
    try {
      const res = await fetch((backendURL || '') + `/api/notifications/${userId}`, {
        headers: { 'Authorization': `Bearer ${localStorage.getItem('jwt_token')}` }
      });
      if (!res.ok) {
        console.warn('No notifications or fetch failed');
        return;
      }
      const data = await res.json();
      const notificationBox = el('#notification-box');
      if (!notificationBox) return;

      notificationBox.innerHTML = ''; // Clear previous

      if (!Array.isArray(data) || data.length === 0) {
        notificationBox.innerHTML = '<p>No notifications</p>';
        return;
      }

      data.forEach(n => {
        const div = document.createElement('div');
        div.className = 'notification-item mb-2';
        const msg = n.message || n.msg || 'Notification';
        const ts = n.created_at || n.timestamp || '';
        div.innerHTML = `<strong>${msg}</strong> <br><small>${ts}</small>`;
        notificationBox.appendChild(div);
      });
    } catch (e) {
      console.error('fetchNotifications error', e);
    }
  }

  let notifTimer = null;
  async function startNotificationsPolling() {
    const user = await checkSession();
    if (user && !notifTimer) {
      fetchNotifications(user.id); // initial load
      notifTimer = setInterval(() => fetchNotifications(user.id), 15000); // every 15s
    }
  }


// ---------------- Network send helper ----------------
async function sendToServer(payload) {
  const token = localStorage.getItem('jwt_token');
  console.log("🔑 DEBUG (sendToServer): jwt_token in localStorage =", token);   // ⬅️ DEBUG

  if (!token) {
    alert('Not authenticated. Please login.');
    window.location.href = '/api/users/auth';
    return { ok: false, data: { response: 'Not authenticated' } };
  }

  try {
    const res = await fetch((backendURL || '') + '/api/chat/message', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify(payload)
    });

    const data = await res.json();
    console.log("📌 DEBUG (sendToServer): server response =", data);   // ⬅️ DEBUG
    return { ok: res.ok, data };
  } catch (err) {
    console.error('Network error', err);
    return { ok: false, data: { response: 'Network error: ' + err.message } };
  }
}


// ---------------- Main sendMessage handler ----------------
window.sendMessage = async function sendMessage() {
  const input = el('#user-input');
  if (!input) return;
  const raw = input.value.trim();

  const fileInput = el('#kyc-file');
  const file = fileInput && fileInput.files && fileInput.files[0];

  // show user message or filename in chat UI
  appendMessage('user', raw || (file && file.name) || '');
  input.value = '';

// 🔹 File upload branch (FormData)
if (file) {
  const token = localStorage.getItem('jwt_token');
  if (!token) {
    appendMessage('bot', '❌ Not authenticated. Please login.');
    return;
  }

  const form = new FormData();
  // if raw is empty send default 'kyc' so backend gets a message field
  form.append('message', raw || 'kyc');
  form.append('file', file);

  // ⬇️ extract extra fields from raw text
  let nationalId = null;
  let fullName = null;

  if (raw) {
    // extract nationalId (GH123456 or 6 digit number)
    const idMatch = raw.match(/\b([A-Z]{2}\d{6})\b/i) || raw.match(/\b(\d{6})\b/);
    if (idMatch) nationalId = (idMatch[1] || idMatch[0]).toUpperCase();

    // extract fullName (after 'name' keyword or words before ID)
    const nameMatch = raw.match(/(?:naam|name)\s+([A-Za-z\s]{3,50}?)(?=\s+(?:id|janam|dob|$))/i);
    if (nameMatch) {
      fullName = nameMatch[1].trim();
    } else if (nationalId) {
      const before = raw.split(nationalId)[0].replace(/^kyc\s*/i, '').trim();
      if (before) fullName = before;
    }
  }

  // append parsed data
  if (raw) form.append('user_text', raw);
  if (nationalId) form.append('document_number', nationalId);
  if (fullName) form.append('name', fullName);

    // --- DEBUG: show exactly what will be sent ---
    try {
      // convert FormData entries to array for readable logging
      const entries = [];
      for (const e of form.entries()) entries.push([e[0], e[1] && e[1].name ? e[1].name : e[1]]);
      console.log('DEBUG: FormData entries about to send ->', entries);
    } catch (e) {
      console.warn('DEBUG: could not list FormData entries', e);
    }

    console.log('DEBUG: backendURL ->', (backendURL || '') + '/api/chat/message');

    try {
      const res = await fetch((backendURL || '') + '/api/chat/message', {
        method: 'POST',
        // IMPORTANT: do NOT set Content-Type here. Browser will set multipart/form-data boundary.
        headers: {
          'Authorization': `Bearer ${token}`
          // if you use cookies-based auth uncomment next line and enable server-side CORS credentials:
          // 'Credentials': 'include'
        },
        body: form,
        // credentials: 'include' // uncomment only if your server expects cookies
      });

      console.log('DEBUG: fetch status', res.status, res.statusText);

      // read raw text first for robust debugging (server might return non-json)
      const rawText = await res.clone().text();
      console.log('DEBUG: raw response text ->', rawText);

      // try parse JSON if possible
      let data;
      try { data = JSON.parse(rawText); } catch (err) { data = { response: rawText }; }

      // show bot response in UI
      appendMessage('bot', data.response || data.message || JSON.stringify(data));

    } catch (err) {
      console.error('DEBUG: upload error', err);
      appendMessage('bot', '❌ Upload failed: ' + (err.message || err));
    }

    // clear file input after attempt
    try { fileInput.value = ''; } catch (e) { /* ignore */ }
    return;
  }

  // 🔹 JSON / text branch
  if (!raw) return;
  let payload = { message: raw };

  if (raw.toLowerCase() === 'kyc') {
    const name = prompt('Enter full name (e.g., John Doe):');
    if (!name) { appendMessage('bot', 'KYC cancelled — name required.'); return; }
    const nationalId = prompt('Enter national ID (format e.g., GH123456):');
    if (!nationalId) { appendMessage('bot', 'KYC cancelled — national ID required.'); return; }
    let dob = prompt('Enter DOB (yyyy-mm-dd):');
    if (!dob) { appendMessage('bot', 'KYC cancelled — DOB required.'); return; }
    const isoMatch = dob.match(/^\d{4}-\d{2}-\d{2}$/);
    const dmyMatch = dob.match(/^(\d{2})-(\d{2})-(\d{4})$/);
    if (!isoMatch && dmyMatch) { dob = `${dmyMatch[3]}-${dmyMatch[2]}-${dmyMatch[1]}`; }

    payload.document = {
      document_type: 'National ID',
      document_number: nationalId.toUpperCase(),
      national_id: nationalId.toUpperCase(),
      name: name.trim(),
      dob: dob.trim()
    };
  }

  // Agar user ne JSON paste kiya hai
  try {
    if (raw.startsWith('{') && raw.endsWith('}')) {
      const asObj = JSON.parse(raw);
      if (asObj.document_number || asObj.national_id || asObj.name || asObj.document_type) {
        payload.document = asObj;
      }
    }
  } catch (e) { /* ignore parse errors */ }

  appendMessage('bot', '...processing');

  try {
    const res = await sendToServer(payload);
    const chatBox = el('#chat-box');
    if (chatBox && chatBox.lastElementChild) {
      const last = chatBox.lastElementChild;
      if (last && last.classList.contains('bot') && last.innerText.trim() === '...processing') {
        chatBox.removeChild(last);
      }
    }

    if (!res.ok) {
      appendMessage('bot', res.data.response || JSON.stringify(res.data));
      return;
    }

    const reply = res.data.response || res.data.message || JSON.stringify(res.data);
    appendMessage('bot', reply);
  } catch (err) {
    appendMessage('bot', '❌ Network error: ' + err.message);
  }

  if (window.loggedInUserId) {
    fetchNotifications(window.loggedInUserId).catch(err => console.warn('refresh notifications failed', err));
  }
};



  // ---------------- Simple appendMessage exposure for older code ----------------
  // Keep a globally available appendMessage for other inline scripts that expect it.
  window.appendMessage = appendMessage;
  // ---- intercept group links and load in-chat (SPA style) ----
// Paste this right after: window.appendMessage = appendMessage;
document.addEventListener('click', async function (e) {
  const a = e.target.closest && e.target.closest('a.group-link');
  if (!a) return;
  e.preventDefault();

  // Determine slug (prefer data-slug)
  const slug = a.dataset.slug || (a.getAttribute('href') || '').split('/').filter(Boolean).pop();
  if (!slug) {
    appendMessage('bot', 'Group link invalid.');
    return;
  }

  appendMessage('bot', `...loading group ${slug}`);

  const token = localStorage.getItem('jwt_token');
  if (!token) {
    appendMessage('bot', 'Not authenticated — please login.');
    return;
  }

  try {
    const res = await fetch((backendURL || '') + `/api/coops/${slug}`, {
      headers: { 'Authorization': `Bearer ${token}` }
    });

    if (!res.ok) {
      const txt = await res.text().catch(() => '');
      console.warn('Group fetch failed', res.status, txt);
      appendMessage('bot', `Failed to load group (${res.status}).`);
      return;
    }

    const group = await res.json();

    // Prefer existing loader if present
    if (typeof loadGroup === 'function') {
      loadGroup(slug, group);
    } else if (typeof openGroupInChat === 'function') {
      openGroupInChat(group);
    } else {
      // fallback: update header + notify user
      const hdr = document.getElementById('chat-header-title') || document.querySelector('.card-header');
      if (hdr) hdr.textContent = group.name || slug;
      appendMessage('bot', `Loaded group: ${group.name || slug}`);
    }
  } catch (err) {
    console.error('Error loading group', err);
    appendMessage('bot', 'Error loading group — check console.');
  }
});


  // ---------------- Logout handler ----------------
  const logoutBtn = el('#logout-btn');
  if (logoutBtn) {
    logoutBtn.addEventListener('click', async () => {
      try {
        const token = localStorage.getItem('jwt_token');
        await fetch((backendURL || '') + '/api/users/logout', {
          method: 'POST',
          credentials: 'include',
          headers: { Authorization: `Bearer ${token}` }
        });
      } catch (e) {
        console.warn('Logout failed', e);
      }
      localStorage.removeItem('jwt_token');
      window.location.href = '/api/users/auth';
    });
  }

  // ---------------- Wire Enter key to send ----------------
  const userInput = el('#user-input');
  if (userInput) {
    userInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        sendMessage();
      }
    });
  }

  // Initialize session + UI
  await checkSession();

})();
