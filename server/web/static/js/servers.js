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
    if (tab === 'files') loadServerFiles('');
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
        document.getElementById('serverDetailTitle').textContent = d.name || currentServerId;
        var modpackLink = document.getElementById('serverDetailModpack');
        if (d.modpack_name && d.modpack_id && d.project_id) {
            modpackLink.style.display = 'inline';
            modpackLink.innerHTML = 'Modpack: <a href="#" onclick="switchToProjectModpack(\'' + escAttr(d.project_id) + '\',\'' + escAttr(d.modpack_id) + '\');return false">' + esc(d.modpack_name) + '</a> | <a href="#" onclick="installServerModpack();return false" style="color:#1976d2">Install</a>';
        } else if (d.modpack_name) {
            modpackLink.style.display = 'inline';
            modpackLink.innerHTML = 'Modpack: ' + esc(d.modpack_name) + ' | <a href="#" onclick="installServerModpack();return false" style="color:#1976d2">Install</a>';
        } else {
            modpackLink.style.display = 'none';
        }
        var badge = document.getElementById('serverDetailBadge');
        var pid = document.getElementById('serverDetailPid');
        document.getElementById('detailBtnStart').disabled = d.running;
        document.getElementById('detailBtnStop').disabled = !d.running;
        if (d.running) {
            badge.textContent = 'RUNNING';
            badge.className = 'badge badge-running';
            pid.textContent = 'PID: ' + d.pid + (d.uptime_seconds ? ' | Uptime: ' + Math.floor(d.uptime_seconds / 60) + 'm' : '') + (d.memory_mb ? ' | ' + d.memory_mb + 'MB' : '');
        } else {
            badge.textContent = 'STOPPED';
            badge.className = 'badge badge-stopped';
            pid.textContent = '';
        }
        var miniName = document.getElementById('selServerName');
        var miniBadge = document.getElementById('selServerBadge');
        miniName.textContent = d.name || currentServerId;
        if (d.running) {
            miniBadge.textContent = 'RUNNING';
            miniBadge.className = 'badge badge-running';
        } else {
            miniBadge.textContent = 'STOPPED';
            miniBadge.className = 'badge badge-stopped';
        }
    } catch (e) {}
}

async function serverAction(action) {
    if (!currentServerId) return;
    try {
        var r = await apiFetch('/admin/instances/' + currentServerId + '/' + action, { method: 'POST' });
        if (!r) return;
        var d = await r.json();
        refreshServerStatus();
        if (d.error) { toast(d.error, 'error'); }
        else if (action !== 'stop') {
            toast('Server ' + action + ' (PID: ' + (d.pid || '?') + ')', 'success');
            addServerLine('[SERVER] ' + action.toUpperCase() + ' (PID: ' + (d.pid || '?') + ')', 'system');
        } else { toast('Server stopped', 'info'); }
    } catch (e) { toast('Failed: ' + e.message, 'error'); }
}

async function installServerModpack() {
    if (!currentServerId) return;
    if (!confirm('Install modpack files into the server directory?')) return;
    var btn = document.getElementById('detailBtnInstallModpack');
    btn.disabled = true;
    btn.textContent = 'Installing...';
    try {
        var r = await apiFetch('/admin/instances/' + currentServerId + '/install-modpack', { method: 'POST' });
        if (!r) return;
        var d = await r.json();
        if (d.error) { toast(d.error, 'error'); }
        else { toast('Modpack installed: ' + d.files_copied + ' / ' + (d.file_count || d.files_copied) + ' files copied', 'success'); }
    } catch (e) { toast('Failed: ' + e.message, 'error'); }
    btn.disabled = false;
    btn.textContent = 'Install Modpack';
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

/* ===================== Server files ===================== */

var serverFilePath = '';

async function loadServerFiles(path) {
    if (!currentServerId) return;
    serverFilePath = path || '';
    var container = document.getElementById('serverFilesBrowser');
    var dirDisplay = document.getElementById('serverFilesDir');
    container.innerHTML = '<div style="color:#888;padding:16px">Loading files...</div>';
    try {
        var url = '/admin/instances/' + currentServerId + '/files?path=' + encodeURIComponent(path || '');
        var r = await apiFetch(url);
        if (!r) return;
        var d = await r.json();
        dirDisplay.textContent = d.absolute || '/';
        if (d.error) { container.innerHTML = '<div class="error-msg">' + esc(d.error) + '</div>'; return; }
        if (!d.items || !d.items.length) {
            container.innerHTML = '<div style="color:#888;padding:16px;text-align:center">Empty directory</div>';
            return;
        }
        var html = '<table><thead><tr><th>Name</th><th>Size</th><th>Modified</th><th>Actions</th></tr></thead><tbody>';
        if (d.path) {
            var parentPath = d.path.replace(/\/?[^/]+$/, '');
            html += '<tr class="file-dir" onclick="loadServerFiles(\'' + escAttr(parentPath) + '\')"><td><span class="tag tag-dir">DIR</span> ..</td><td></td><td></td><td></td></tr>';
        }
        for (var i = 0; i < d.items.length; i++) {
            var item = d.items[i];
            var label = item.is_dir ? '<span class="tag tag-dir">DIR</span>' : '<span class="tag tag-file">FILE</span>';
            var childPath = d.path ? d.path + '/' + item.name : item.name;
            var clickHandler = item.is_dir ? 'loadServerFiles(\'' + escAttr(childPath) + '\')' : 'openServerFileEditor(\'' + escAttr(childPath) + '\')';
            var sizeStr = item.is_dir ? '-' : formatSize(item.size);
            var dateStr = new Date(item.modified * 1000).toLocaleString();
            var actions = '';
            actions += '<button class="btn btn-sm btn-secondary" onclick="event.stopPropagation();downloadServerPath(\'' + escAttr(childPath) + '\')">' + (item.is_dir ? 'Download ZIP' : 'Download') + '</button>';
            if (!item.is_dir) {
                actions += '<button class="btn btn-sm btn-secondary" onclick="event.stopPropagation();openServerFileEditor(\'' + escAttr(childPath) + '\')">Edit</button>';
                actions += '<button class="btn btn-sm btn-secondary" onclick="event.stopPropagation();deleteServerFile(\'' + escAttr(childPath) + '\')">Delete</button>';
            }
            html += '<tr class="' + (item.is_dir ? 'file-dir' : 'file-file') + '" onclick="' + clickHandler + '"><td>' + label + ' ' + esc(item.name) + '</td><td>' + sizeStr + '</td><td>' + dateStr + '</td><td>' + actions + '</td></tr>';
        }
        html += '</tbody></table>';
        container.innerHTML = html;
    } catch (e) { container.innerHTML = '<div class="error-msg">Failed: ' + esc(e.message) + '</div>'; }
}

async function openServerFileEditor(filePath) {
    if (!currentServerId) return;
    try {
        var r = await apiFetch('/admin/instances/' + currentServerId + '/files/read?path=' + encodeURIComponent(filePath));
        if (!r) return;
        var d = await r.json();
        if (d.error) { toast(d.error, 'error'); return; }
        if (!d.is_text) { toast('Binary files cannot be edited', 'error'); return; }
        var container = document.getElementById('serverFilesBrowser');
        container.innerHTML = '<div class="md-card"><div class="row"><strong>Editing:</strong> <span style="font-family:monospace;color:#1976d2;flex:1">' + esc(d.path) + '</span>' +
            '<button class="btn btn-start btn-sm" onclick="saveServerFile(\'' + escAttr(filePath) + '\')">Save</button>' +
            '<button class="btn btn-secondary btn-sm" onclick="loadServerFiles(\'' + escAttr(serverFilePath) + '\')">Close</button></div>' +
            '<textarea id="serverFileEditorText" style="width:100%;height:400px;font:13px/1.6 monospace;padding:12px;border:2px solid #bdbdbd;border-radius:4px;resize:vertical;margin-top:12px" spellcheck="false">' + esc(d.content) + '</textarea></div>';
    } catch (e) { toast('Failed: ' + e.message, 'error'); }
}

async function saveServerFile(filePath) {
    if (!currentServerId) return;
    var content = document.getElementById('serverFileEditorText').value;
    try {
        var r = await apiFetch('/admin/instances/' + currentServerId + '/files/write', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: filePath, content: content })
        });
        if (!r) return;
        var d = await r.json();
        if (d.error) { toast(d.error, 'error'); return; }
        toast('File saved', 'success');
    } catch (e) { toast('Failed: ' + e.message, 'error'); }
}

async function deleteServerFile(filePath) {
    if (!currentServerId || !confirm('Delete "' + filePath + '"?')) return;
    try {
        var r = await apiFetch('/admin/instances/' + currentServerId + '/files', {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: filePath })
        });
        if (!r) return;
        var d = await r.json();
        if (d.error) { toast(d.error, 'error'); return; }
        toast('File deleted', 'info');
        loadServerFiles(serverFilePath);
    } catch (e) { toast('Failed: ' + e.message, 'error'); }
}

async function downloadServerPath(path) {
    if (!currentServerId) return;
    var fallback = path ? path.split('/').pop() : currentServerId + '-files';
    await downloadBlob('/admin/instances/' + currentServerId + '/files/download?path=' + encodeURIComponent(path || ''), fallback);
}

async function uploadServerFile(input) {
    if (!currentServerId) { toast('No server selected', 'error'); return; }
    for (var fi = 0; fi < input.files.length; fi++) {
        var file = input.files[fi];
        var formData = new FormData();
        formData.append('file', file);
        formData.append('path', serverFilePath);
        try {
            var r = await apiFetch('/admin/instances/' + currentServerId + '/files/upload', {
                method: 'POST',
                body: formData
            });
            if (!r) return;
            var d = await r.json();
            if (d.error) { toast(d.error, 'error'); }
            else { toast('Uploaded: ' + file.name, 'success'); }
        } catch (e) { toast('Upload failed: ' + e.message, 'error'); }
    }
    input.value = '';
    loadServerFiles(serverFilePath);
}
