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
