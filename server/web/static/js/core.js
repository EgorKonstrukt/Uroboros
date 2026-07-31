/* ===================== Core: shared state + utilities ===================== */

var currentServerId = null;
var expandedProjects = {};
var serverPollTimer = null;

function getToken() { return sessionStorage.getItem('admin_token'); }
function setToken(t) { if (t) sessionStorage.setItem('admin_token', t); else sessionStorage.removeItem('admin_token'); }

async function apiFetch(url, options) {
    if (!options) options = {};
    if (!options.headers) options.headers = {};
    var token = getToken();
    if (token) options.headers['Authorization'] = 'Bearer ' + token;
    try {
        var r = await fetch(url, options);
        if (r.status === 401) { setToken(null); window.location.href = '/admin/login'; return null; }
        return r;
    } catch (e) { throw e; }
}

function toast(msg, type) {
    var el = document.getElementById('toast');
    el.textContent = msg;
    el.className = 'toast toast-' + (type || 'info');
    el.style.display = 'block';
    setTimeout(function () { el.style.display = 'none'; }, 4000);
}

function openModal(id) {
    document.getElementById(id).style.display = 'flex';
}

function closeModal(id) { document.getElementById(id).style.display = 'none'; }

function esc(s) { var d = document.createElement('div'); d.textContent = s || ''; return d.innerHTML; }
function escAttr(s) { return (s || '').replace(/'/g, "\\'"); }

function formatSize(bytes) {
    if (bytes >= 1073741824) return (bytes / 1073741824).toFixed(1) + ' GB';
    if (bytes >= 1048576) return (bytes / 1048576).toFixed(1) + ' MB';
    if (bytes >= 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return bytes + ' B';
}

async function downloadBlob(url, fallbackName) {
    try {
        var r = await apiFetch(url);
        if (!r) return;
        if (!r.ok) {
            var d = await r.json().catch(function () { return { error: 'Download failed (' + r.status + ')' }; });
            toast(d.error || 'Download failed', 'error');
            return;
        }
        var blob = await r.blob();
        var cd = r.headers.get('Content-Disposition') || '';
        var m = cd.match(/filename="?([^";]+)"?/);
        var dlName = m ? m[1] : fallbackName;
        var a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = dlName;
        document.body.appendChild(a);
        a.click();
        setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
    } catch (e) { toast('Download failed: ' + e.message, 'error'); }
}

/* ===================== Theme ===================== */

window.__themeListeners = window.__themeListeners || [];

function notifyThemeChanged() {
    for (var i = 0; i < window.__themeListeners.length; i++) {
        try { window.__themeListeners[i](); } catch (e) {}
    }
}

function toggleTheme() {
    var dark = document.documentElement.classList.contains('theme-dark');
    var t = dark ? 'light' : 'dark';
    document.documentElement.classList.toggle('theme-dark', t === 'dark');
    try { localStorage.setItem('uroboros_theme', t); } catch (e) {}
    notifyThemeChanged();
}

/* ===================== MD2 ripple ===================== */

document.addEventListener('click', function (e) {
    var el = e.target && e.target.closest ? e.target.closest('.btn,.icon-btn,.nav-item,.server-tab,.sub-nav-item,#logoutBtn') : null;
    if (!el || el.disabled) return;
    var r = el.getBoundingClientRect();
    var d = Math.max(r.width, r.height) * 1.1;
    var s = document.createElement('span');
    s.className = 'ripple';
    s.style.width = Math.round(d) + 'px';
    s.style.height = Math.round(d) + 'px';
    s.style.left = Math.round(e.clientX - r.left - d / 2) + 'px';
    s.style.top = Math.round(e.clientY - r.top - d / 2) + 'px';
    el.appendChild(s);
    setTimeout(function () { if (s.parentNode) s.parentNode.removeChild(s); }, 500);
});
