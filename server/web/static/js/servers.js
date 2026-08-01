/* ===================== Add server modal ===================== */

function showAddServer() {
    document.getElementById('newServerId').value = '';
    document.getElementById('newServerName').value = '';
    var projSelect = document.getElementById('newServerProject');
    var mpSelect = document.getElementById('newServerModpack');
    projSelect.innerHTML = '<option value="">(None)</option>';
    mpSelect.innerHTML = '<option value="">(None)</option>';
    apiFetch('/projects').then(function(r) {
        if (!r) return;
        r.json().then(function(projects) {
            for (var i = 0; i < projects.length; i++) {
                var opt = document.createElement('option');
                opt.value = projects[i].id;
                opt.textContent = projects[i].name;
                projSelect.appendChild(opt);
            }
        });
    });
    document.getElementById('addServerModal').style.display = 'flex';
    document.getElementById('newServerId').focus();
}

function onNewServerProjectChange() {
    var pid = document.getElementById('newServerProject').value;
    var mpSelect = document.getElementById('newServerModpack');
    mpSelect.innerHTML = '<option value="">(None)</option>';
    if (!pid) return;
    apiFetch('/admin/projects/' + pid + '/modpacks').then(function(r) {
        if (!r) return;
        r.json().then(function(modpacks) {
            for (var i = 0; i < modpacks.length; i++) {
                var opt = document.createElement('option');
                opt.value = modpacks[i].id;
                opt.textContent = modpacks[i].name + ' v' + modpacks[i].version;
                mpSelect.appendChild(opt);
            }
        });
    });
}

async function confirmAddServer() {
    var id = document.getElementById('newServerId').value.trim();
    var name = document.getElementById('newServerName').value.trim() || id;
    var projectId = document.getElementById('newServerProject').value;
    var modpackId = document.getElementById('newServerModpack').value;
    if (!id) { toast('Server ID is required', 'error'); return; }
    if (!/^[a-zA-Z0-9_-]+$/.test(id)) { toast('ID must be alphanumeric, hyphens, underscores only', 'error'); return; }
    try {
        var r = await apiFetch('/admin/instances', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id: id, name: name, project_id: projectId, modpack_id: modpackId })
        });
        if (!r) return;
        var d = await r.json();
        if (d.error) { toast(d.error, 'error'); return; }
        toast('Server "' + name + '" created', 'success');
        closeModal('addServerModal');
        loadServersList();
    } catch (e) { toast('Failed: ' + e.message, 'error'); }
}

/* ===================== Servers ===================== */

var consolePaused = false;
var consoleAutoScroll = true;
var consoleFontSizeVal = 13;
var seenLines = {};
var cmdHistory = [];
var cmdHistoryIdx = -1;
var currentSubTab = 'console';

async function loadServersList() {
    renderServerNav();
}

async function deleteServer(id) {
    if (!confirm('Delete server "' + id + '"?')) return;
    try {
        var r = await apiFetch('/admin/instances/' + id, { method: 'DELETE' });
        if (!r) return;
        var d = await r.json();
        if (d.error) { toast(d.error, 'error'); return; }
        toast('Server deleted', 'info');
        if (currentServerId === id) { currentServerId = null; }
        loadServersList();
    } catch (e) { toast('Failed: ' + e.message, 'error'); }
}

async function openServerDetail(id) {
    currentServerId = id;
    currentSubTab = 'overview';
    stopOverview();
    document.getElementById('serverDetailView').style.display = 'block';
    document.getElementById('serverMiniBar').style.display = 'flex';
    document.getElementById('serverConsoleOutput').innerHTML = '';
    seenLines = {};
    document.querySelectorAll('.sub-nav-item').forEach(function (n) { n.classList.remove('active'); });
    document.querySelector('.sub-nav-item[data-subtab="overview"]').classList.add('active');
    document.querySelectorAll('.server-sub-panel').forEach(function (p) { p.classList.remove('active'); });
    document.getElementById('serverOverviewView').classList.add('active');
    refreshServerStatus();
    startStatusPolling();
    startOverview();
}

function switchServerSubTab(tab) {
    currentSubTab = tab;
    document.querySelectorAll('.sub-nav-item').forEach(function (n) { n.classList.remove('active'); });
    document.querySelector('.sub-nav-item[data-subtab="' + tab + '"]').classList.add('active');
    document.querySelectorAll('.server-sub-panel').forEach(function (p) { p.classList.remove('active'); });
    document.getElementById('server' + tab.charAt(0).toUpperCase() + tab.slice(1) + 'View').classList.add('active');
    if (tab === 'console') {
        if (!serverPollTimer) pollServerOutput();
    } else {
        if (serverPollTimer) { clearInterval(serverPollTimer); serverPollTimer = null; }
    }
    if (tab === 'overview') { startOverview(); }
    else { stopOverview(); }
    if (tab === 'settings') loadServerSettings();
    if (tab === 'files') serverFM.load('');
}

function pollServerOutput() {
    if (serverPollTimer) clearInterval(serverPollTimer);
    serverPollTimer = setInterval(function () {
        refreshServerStatus();
        refreshServerOutput();
    }, 2000);
}

async function refreshServerStatus() {
    if (!currentServerId) return;
    try {
        var r = await apiFetch('/admin/instances/' + currentServerId + '/status');
        if (!r) return;
        var d = await r.json();
        applyServerStatus(d);
    } catch (e) {}
}

function applyServerStatus(d) {
    document.getElementById('serverDetailTitle').textContent = d.name || currentServerId;
        var modpackLink = document.getElementById('serverDetailModpack');
        if (d.modpack_name && d.modpack_id && d.project_id) {
            modpackLink.style.display = 'inline';
            modpackLink.innerHTML = 'Modpack: <a href="#" onclick="switchToProjectModpack(\'' + escAttr(d.project_id) + '\',\'' + escAttr(d.modpack_id) + '\');return false">' + esc(d.modpack_name) + '</a>';
        } else if (d.modpack_name) {
            modpackLink.style.display = 'inline';
            modpackLink.innerHTML = 'Modpack: ' + esc(d.modpack_name);
        } else {
            modpackLink.style.display = 'none';
        }
        var badge = document.getElementById('serverDetailBadge');
        var pid = document.getElementById('serverDetailPid');
        var startBtn = document.getElementById('detailBtnStart');
        var stopBtn = document.getElementById('detailBtnStop');
        var restartBtn = document.getElementById('detailBtnRestart');
        var reloadBtn = document.getElementById('detailBtnReload');
        if (d.stopping) {
            startBtn.disabled = true;
            stopBtn.disabled = true;
            restartBtn.disabled = true;
            if (reloadBtn) reloadBtn.disabled = true;
            badge.textContent = 'STOPPING';
            badge.className = 'badge badge-stopping';
            pid.textContent = 'Stopping server...';
        } else if (d.starting) {
            startBtn.disabled = true;
            stopBtn.disabled = false;
            restartBtn.disabled = true;
            if (reloadBtn) reloadBtn.disabled = true;
            badge.textContent = 'STARTING';
            badge.className = 'badge badge-starting';
            pid.textContent = 'Server is booting...';
        } else if (d.running) {
            startBtn.disabled = true;
            stopBtn.disabled = false;
            restartBtn.disabled = false;
            if (reloadBtn) reloadBtn.disabled = false;
            badge.textContent = 'RUNNING';
            badge.className = 'badge badge-running';
            pid.textContent = 'PID: ' + d.pid + (d.uptime_seconds ? ' | Uptime: ' + Math.floor(d.uptime_seconds / 60) + 'm' : '') + (d.memory_mb ? ' | ' + d.memory_mb + 'MB' : '');
        } else {
            startBtn.disabled = false;
            stopBtn.disabled = true;
            restartBtn.disabled = true;
            if (reloadBtn) reloadBtn.disabled = true;
            badge.textContent = 'STOPPED';
            badge.className = 'badge badge-stopped';
            pid.textContent = '';
        }
        var miniName = document.getElementById('selServerName');
        var miniBadge = document.getElementById('selServerBadge');
        miniName.textContent = d.name || currentServerId;
        if (d.stopping) {
            miniBadge.textContent = 'STOPPING';
            miniBadge.className = 'badge badge-stopping';
        } else if (d.starting) {
            miniBadge.textContent = 'STARTING';
            miniBadge.className = 'badge badge-starting';
        } else if (d.running) {
            miniBadge.textContent = 'RUNNING';
            miniBadge.className = 'badge badge-running';
        } else {
            miniBadge.textContent = 'STOPPED';
            miniBadge.className = 'badge badge-stopped';
        }
    if (currentServerId) updateServerDot(currentServerId, d);
}

async function serverAction(action) {
    if (!currentServerId) return;
    try {
        var r = await apiFetch('/admin/instances/' + currentServerId + '/' + action, { method: 'POST' });
        if (!r) return;
        var d = await r.json();
        refreshServerStatus();
        if (d.error) { toast(d.error, 'error'); }
        else if (action === 'start') {
            toast('Server started (PID: ' + (d.pid || '?') + ')', 'success');
            addServerLine('[SERVER] STARTED (PID: ' + (d.pid || '?') + ')', 'system');
        } else if (action === 'stop') {
            toast('Server is stopping gracefully...', 'info');
            addServerLine('[SERVER] STOP requested (graceful shutdown)', 'system');
        } else if (action === 'restart') {
            toast('Server is restarting...', 'info');
            addServerLine('[SERVER] RESTART requested', 'system');
        } else if (action === 'reload') {
            toast('Server reloading (reload command sent)', 'success');
            addServerLine('[SERVER] RELOAD requested', 'system');
        } else {
            toast('Server ' + action, 'info');
        }
    } catch (e) { toast('Failed: ' + e.message, 'error'); }
}

async function syncServerWhitelist() {
    if (!currentServerId) return;
    var btn = document.getElementById('detailBtnSyncWhitelist');
    btn.disabled = true;
    btn.textContent = 'Syncing...';
    try {
        var r = await apiFetch('/admin/instances/' + currentServerId + '/whitelist/sync', { method: 'POST' });
        if (!r) return;
        var d = await r.json();
        if (d.error) { toast(d.error, 'error'); }
        else { toast('Whitelist synced: ' + d.count + ' players', 'success'); }
    } catch (e) { toast('Failed: ' + e.message, 'error'); }
    btn.disabled = false;
    btn.textContent = 'Sync Whitelist';
}

async function refreshServerOutput() {
    if (!currentServerId || consolePaused || currentSubTab !== 'console') return;
    try {
        var r = await apiFetch('/admin/instances/' + currentServerId + '/output?tail=200');
        if (!r) return;
        var d = await r.json();
        var el = document.getElementById('serverConsoleOutput');
        if (!d.lines || !d.lines.length) return;
        if (el.querySelectorAll('.line').length > 2000) {
            var excess = el.querySelectorAll('.line').length - 1500;
            for (var i = 0; i < excess; i++) {
                var first = el.querySelector('.line');
                if (first) {
                    delete seenLines[first.textContent];
                    el.removeChild(first);
                }
            }
        }
        for (var i = 0; i < d.lines.length; i++) {
            var txt = d.lines[i];
            if (!seenLines[txt]) {
                addServerLine(txt);
                seenLines[txt] = true;
            }
        }
    } catch (e) {}
}

function addServerLine(text, clsOverride) {
    var el = document.getElementById('serverConsoleOutput');
    var cls = clsOverride || 'info';
    if (!clsOverride) {
        var upper = text.toUpperCase();
        if (/^\[SERVER\]/.test(text)) { cls = 'system'; }
        else if (/FATAL|CRITICAL/.test(upper)) { cls = 'fatal'; }
        else if (/ERROR|EXCEPTION|FAILED|UNEXPECTED/.test(upper)) { cls = 'error'; }
        else if (/WARN|WARNING/.test(upper)) { cls = 'warn'; }
        else if (/^\[.*DONE/.test(text) || /DONE/.test(upper)) { cls = 'done'; }
        else if (/DEBUG|TRACE/.test(upper)) { cls = 'debug'; }
        else if (/^\d/.test(text)) { cls = 'server'; }
    }
    var ts = '';
    var content = text;
    var tsMatch = text.match(/^\[?(\d{2}:\d{2}:\d{2})\]/);
    if (tsMatch) {
        ts = tsMatch[1];
        content = text.replace(/^\[\d{2}:\d{2}:\d{2}\]\s*/, '');
    }
    var escaped = esc(content);
    var lineHtml = '<div class="line ' + cls + '">' + (ts ? '<span class="timestamp">[' + esc(ts) + ']</span>' : '') + escaped + '</div>';
    el.insertAdjacentHTML('beforeend', lineHtml);
    if (consoleAutoScroll) { el.scrollTop = el.scrollHeight; }
}

function toggleConsolePause() {
    consolePaused = !consolePaused;
    var btn = document.getElementById('consolePauseBtn');
    btn.classList.toggle('active', consolePaused);
    btn.textContent = consolePaused ? 'Resume' : 'Pause';
    if (!consolePaused) refreshServerOutput();
}

function toggleConsoleScroll() {
    consoleAutoScroll = !consoleAutoScroll;
    var btn = document.getElementById('consoleScrollBtn');
    btn.classList.toggle('active', consoleAutoScroll);
    if (consoleAutoScroll) {
        var el = document.getElementById('serverConsoleOutput');
        el.scrollTop = el.scrollHeight;
    }
}

function consoleFontSize(delta) {
    consoleFontSizeVal = Math.max(9, Math.min(24, consoleFontSizeVal + delta));
    document.getElementById('serverConsoleOutput').style.fontSize = consoleFontSizeVal + 'px';
}

function clearServerConsole() {
    document.getElementById('serverConsoleOutput').innerHTML = '';
    seenLines = {};
}

function searchServerConsole() {
    var input = document.getElementById('consoleSearchInput');
    var term = input.value.trim().toLowerCase();
    var el = document.getElementById('serverConsoleOutput');
    var lines = el.querySelectorAll('.line');
    var matches = 0;
    for (var i = 0; i < lines.length; i++) {
        var show = !term || lines[i].textContent.toLowerCase().indexOf(term) !== -1;
        lines[i].style.display = show ? '' : 'none';
        if (show && term) matches++;
    }
    document.getElementById('consoleSearchCount').textContent = term ? matches + '/' + lines.length : '';
}

function sendServerCommand() {
    if (!currentServerId) return;
    var input = document.getElementById('consoleCmdInput');
    var cmd = input.value.trim();
    if (!cmd) return;
    input.value = '';
    cmdHistory.push(cmd);
    cmdHistoryIdx = cmdHistory.length;
    addServerLine('> ' + cmd, 'input');
    apiFetch('/admin/instances/' + currentServerId + '/command?command=' + encodeURIComponent(cmd), { method: 'POST' }).then(function (r) {
        if (r) r.json().then(function (d) { if (d && d.error) addServerLine('[ERROR] ' + d.error, 'error'); });
    }).catch(function () {});
}

function handleConsoleCmdKey(event) {
    if (event.key === 'Enter') { sendServerCommand(); return; }
    if (event.key === 'ArrowUp') {
        event.preventDefault();
        if (!cmdHistory.length) return;
        cmdHistoryIdx = Math.max(0, cmdHistoryIdx - 1);
        document.getElementById('consoleCmdInput').value = cmdHistory[cmdHistoryIdx];
    } else if (event.key === 'ArrowDown') {
        event.preventDefault();
        if (!cmdHistory.length) return;
        cmdHistoryIdx = Math.min(cmdHistory.length, cmdHistoryIdx + 1);
        document.getElementById('consoleCmdInput').value = cmdHistoryIdx < cmdHistory.length ? cmdHistory[cmdHistoryIdx] : '';
    }
}

/* ===================== Server settings ===================== */

async function loadServerSettings() {
    if (!currentServerId) return;
    try {
        var r = await apiFetch('/admin/instances/' + currentServerId + '/schema');
        if (!r) return;
        var fields = await r.json();
        renderConfigForm('serverSettingsForm', fields, 'saveServerSettings(event)');
    } catch (e) { toast('Failed: ' + e.message, 'error'); }
}

async function saveServerSettings(event) {
    event.preventDefault();
    if (!currentServerId) return;
    var data = collectFormData('serverSettingsForm');
    try {
        var r = await apiFetch('/admin/instances/' + currentServerId, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        if (!r) return;
        var d = await r.json();
        if (r.status === 400) { toast((d.errors || []).join('; ') || 'Validation failed', 'error'); }
        else { toast('Settings saved', 'success'); }
    } catch (e) { toast('Failed: ' + e.message, 'error'); }
}

/* ===================== Server files (advanced manager) ===================== */

var serverFM = new FileManager({
    managerVar: 'serverFM',
    listUrl: function (p) { return '/admin/instances/' + currentServerId + '/files?path=' + encodeURIComponent(p || ''); },
    uploadBatchUrl: function () { return '/admin/instances/' + currentServerId + '/files/upload-batch'; },
    deleteUrl: function () { return '/admin/instances/' + currentServerId + '/files'; },
    actionUrl: function (a) { return '/admin/instances/' + currentServerId + '/files/' + a; },
    downloadUrl: function (p) { return '/admin/instances/' + currentServerId + '/files/download?path=' + encodeURIComponent(p || ''); },
    readUrl: function (p) { return '/admin/instances/' + currentServerId + '/files/read?path=' + encodeURIComponent(p); },
    writeUrl: function () { return '/admin/instances/' + currentServerId + '/files/write'; },
    editorTextId: 'serverFileEditorText',
    ids: {
        browser: 'serverFilesBrowser',
        dir: 'serverFilesDir',
        breadcrumb: 'serverFmBreadcrumb',
        queue: 'serverFmQueue',
        selbar: 'serverFmSelbar',
        searchInput: 'serverFmSearchInput'
    }
});
