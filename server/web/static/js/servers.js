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
var consoleWrap = false;
var consoleRefreshMs = 2000;
var consoleCursor = 0;
var cmdHistory = [];
var cmdHistoryIdx = -1;
var currentSubTab = 'console';

var ANSI_COLORS = {
    30: '#6e6e6e', 31: '#e05c5c', 32: '#52a852', 33: '#c9971f',
    34: '#4f8edb', 35: '#b06bbf', 36: '#3fa5a5', 37: '#d4d4d4',
    90: '#9a9a9a', 91: '#ff7575', 92: '#85cf85', 93: '#eecb57',
    94: '#8ec1f0', 95: '#dd9fe8', 96: '#7fd0d0', 97: '#f2f2f2'
};
var MC_COLORS = {
    '0': '#000000', '1': '#0000aa', '2': '#00aa00', '3': '#00aaaa',
    '4': '#aa0000', '5': '#aa00aa', '6': '#ffaa00', '7': '#aaaaaa',
    '8': '#555555', '9': '#5555ff', 'a': '#55ff55', 'b': '#55ffff',
    'c': '#ff5555', 'd': '#ff55ff', 'e': '#ffff55', 'f': '#ffffff'
};

function colorizeConsole(text) {
    var out = '';
    var fg = null, bold = false, italic = false, underline = false;
    var buf = '';
    function style() {
        var s = '';
        if (fg) s += 'color:' + fg + ';';
        if (bold) s += 'font-weight:700;';
        if (italic) s += 'font-style:italic;';
        if (underline) s += 'text-decoration:underline;';
        return s;
    }
    function flush() {
        if (!buf) return;
        var st = style();
        out += st ? '<span style="' + st + '">' + esc(buf) + '</span>' : esc(buf);
        buf = '';
    }
    var i = 0, n = text.length;
    while (i < n) {
        var ch = text[i];
        if (ch === '\u001b' && text[i + 1] === '[') {
            var j = text.indexOf('m', i + 2);
            if (j === -1) { buf += ch; i++; continue; }
            flush();
            var codes = text.slice(i + 2, j).split(';');
            for (var k = 0; k < codes.length; k++) {
                var c = parseInt(codes[k], 10);
                if (isNaN(c)) continue;
                if (c === 0) { fg = null; bold = italic = underline = false; }
                else if (c === 1) bold = true;
                else if (c === 3) italic = true;
                else if (c === 4) underline = true;
                else if (c === 22) bold = false;
                else if (c === 23) italic = false;
                else if (c === 24) underline = false;
                else if (ANSI_COLORS[c]) fg = ANSI_COLORS[c];
            }
            i = j + 1;
            continue;
        }
        if (ch === '\u00a7' && i + 1 < n) {
            var code = text[i + 1].toLowerCase();
            flush();
            if (MC_COLORS[code]) { fg = MC_COLORS[code]; bold = italic = underline = false; }
            else if (code === 'l') bold = true;
            else if (code === 'o') italic = true;
            else if (code === 'n') underline = true;
            else if (code === 'r') { fg = null; bold = italic = underline = false; }
            i += 2;
            continue;
        }
        buf += ch;
        i++;
    }
    flush();
    return out;
}

function consoleLevelOf(text) {
    var upper = text.toUpperCase();
    if (/^\[SERVER\]/.test(text)) return 'system';
    if (/FATAL|CRITICAL/.test(upper)) return 'fatal';
    if (/ERROR|EXCEPTION|FAILED|UNEXPECTED/.test(upper)) return 'error';
    if (/WARN|WARNING/.test(upper)) return 'warn';
    if (/DONE/.test(upper)) return 'done';
    if (/DEBUG|TRACE/.test(upper)) return 'debug';
    if (/^\d/.test(text)) return 'server';
    return 'info';
}

function consoleLevelShown(level) {
    var f = document.getElementById('consoleFilter').value;
    if (f === 'all') return true;
    if (f === 'no-debug') return level !== 'debug';
    if (f === 'warn') return level === 'warn' || level === 'error' || level === 'fatal' || level === 'crash';
    if (f === 'error') return level === 'error' || level === 'fatal' || level === 'crash';
    return true;
}

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
    consoleCursor = 0;
    applyConsoleVisibility();
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
        pollServerOutput();
    } else {
        if (serverPollTimer) { clearInterval(serverPollTimer); serverPollTimer = null; }
    }
    if (tab === 'overview') { startOverview(); }
    else { stopOverview(); }
    if (tab === 'settings') loadServerSettings();
    if (tab === 'files') serverFM.load('');
}

function pollServerOutput() {
    scheduleServerPoll();
    refreshServerOutput();
}

function scheduleServerPoll() {
    if (serverPollTimer) clearInterval(serverPollTimer);
    serverPollTimer = setInterval(function () {
        refreshServerStatus();
        refreshServerOutput();
    }, consoleRefreshMs);
}

function syncConsoleRefresh(ms) {
    if (!ms || ms === consoleRefreshMs) return;
    consoleRefreshMs = ms;
    var sel = document.getElementById('consoleRefreshRate');
    if (sel && sel.querySelector('option[value="' + ms + '"]')) sel.value = String(ms);
    scheduleServerPoll();
}

function onConsoleRefreshChange() {
    var ms = parseInt(document.getElementById('consoleRefreshRate').value, 10) || 2000;
    apiFetch('/admin/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ console_refresh_ms: ms })
    }).then(function (r) {
        if (!r) return null;
        return r.json();
    }).then(function (d) {
        if (!d) return;
        if (d.error) { toast('Failed to save refresh rate', 'error'); return; }
        consoleRefreshMs = ms;
        scheduleServerPoll();
        toast('Console refresh: ' + ms + ' ms', 'success');
    }).catch(function () {});
}

function setConsoleRunning(running) {
    var dot = document.getElementById('consoleStatusDot');
    var text = document.getElementById('consoleStatusText');
    if (!dot || !text) return;
    dot.className = 'dot ' + (running ? 'dot-on' : 'dot-off');
    text.textContent = running ? 'Running' : 'Offline';
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
        var r = await apiFetch('/admin/instances/' + currentServerId + '/output?start=' + consoleCursor);
        if (!r) return;
        var d = await r.json();
        if (d.error || !d.lines) return;
        syncConsoleRefresh(d.refresh_ms);
        setConsoleRunning(d.running);
        document.getElementById('consoleUpdated').textContent = 'Updated ' + new Date().toLocaleTimeString();
        if (d.reset) {
            clearServerConsole();
            var r2 = await apiFetch('/admin/instances/' + currentServerId + '/output?start=0');
            if (r2) {
                var d2 = await r2.json();
                if (d2 && d2.lines) {
                    for (var i = 0; i < d2.lines.length; i++) addServerLine(d2.lines[i]);
                }
                consoleCursor = d2 ? d2.cursor : 0;
            }
        } else {
            for (var j = 0; j < d.lines.length; j++) addServerLine(d.lines[j]);
            consoleCursor = d.cursor;
        }
    } catch (e) {}
}

function addServerLine(text, clsOverride) {
    var el = document.getElementById('serverConsoleOutput');
    text = String(text).replace(/\r/g, '');
    var cls = clsOverride || consoleLevelOf(text);
    var ts = '';
    var content = text;
    var tsMatch = text.match(/^\[?(\d{2}:\d{2}:\d{2})\]/);
    if (tsMatch) {
        ts = tsMatch[1];
        content = text.replace(/^\[\d{2}:\d{2}:\d{2}\]\s*/, '');
    }
    var term = (document.getElementById('consoleSearchInput').value || '').toLowerCase().trim();
    var pass = consoleLevelShown(cls) && (!term || text.toLowerCase().indexOf(term) !== -1);
    var lineHtml = '<div class="line ' + cls + '" data-level="' + cls + '"' + (pass ? '' : ' style="display:none"') + '>' +
        (ts ? '<span class="timestamp">[' + esc(ts) + ']</span>' : '') + colorizeConsole(content) + '</div>';
    el.insertAdjacentHTML('beforeend', lineHtml);
    var lines = el.querySelectorAll('.line');
    if (lines.length > 2000) {
        var excess = lines.length - 2000;
        for (var i = 0; i < excess; i++) {
            var first = el.querySelector('.line');
            if (first) el.removeChild(first);
        }
    }
    if (pass && consoleAutoScroll) { el.scrollTop = el.scrollHeight; }
    updateConsoleStats();
    updateSearchCount();
}

function updateConsoleStats() {
    var el = document.getElementById('serverConsoleOutput');
    var lines = el.querySelectorAll('.line');
    var shown = 0;
    for (var i = 0; i < lines.length; i++) {
        if (lines[i].style.display !== 'none') shown++;
    }
    document.getElementById('consoleStats').textContent = 'Lines: ' + lines.length + ' \u00b7 Shown: ' + shown;
}

function updateSearchCount() {
    var term = (document.getElementById('consoleSearchInput').value || '').trim();
    var el = document.getElementById('serverConsoleOutput');
    var lines = el.querySelectorAll('.line');
    if (!term) {
        document.getElementById('consoleSearchCount').textContent = '';
        return;
    }
    var shown = 0;
    for (var i = 0; i < lines.length; i++) {
        if (lines[i].style.display !== 'none') shown++;
    }
    document.getElementById('consoleSearchCount').textContent = shown + '/' + lines.length;
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

function toggleConsoleWrap() {
    consoleWrap = !consoleWrap;
    var el = document.getElementById('serverConsoleOutput');
    el.classList.toggle('no-wrap', consoleWrap);
    var btn = document.getElementById('consoleWrapBtn');
    btn.classList.toggle('active', consoleWrap);
}

function consoleFontSize(delta) {
    consoleFontSizeVal = Math.max(9, Math.min(24, consoleFontSizeVal + delta));
    document.getElementById('serverConsoleOutput').style.fontSize = consoleFontSizeVal + 'px';
}

function clearServerConsole() {
    document.getElementById('serverConsoleOutput').innerHTML = '';
    consoleCursor = 0;
    updateConsoleStats();
    updateSearchCount();
}

function searchServerConsole() {
    applyConsoleVisibility();
}

function applyConsoleVisibility() {
    var term = (document.getElementById('consoleSearchInput').value || '').toLowerCase().trim();
    var el = document.getElementById('serverConsoleOutput');
    var lines = el.querySelectorAll('.line');
    var shown = 0;
    for (var i = 0; i < lines.length; i++) {
        var ln = lines[i];
        var pass = consoleLevelShown(ln.getAttribute('data-level') || 'info') &&
            (!term || ln.textContent.toLowerCase().indexOf(term) !== -1);
        ln.style.display = pass ? '' : 'none';
        if (pass) shown++;
    }
    document.getElementById('consoleSearchCount').textContent = term ? shown + '/' + lines.length : '';
    document.getElementById('consoleStats').textContent = 'Lines: ' + lines.length + ' \u00b7 Shown: ' + shown;
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
