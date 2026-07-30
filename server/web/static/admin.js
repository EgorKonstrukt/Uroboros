var currentProjectId = null;
var currentBuildId = null;
var currentServerId = null;
var consolePaused = false;
var consoleAutoScroll = true;
var consoleFontSizeVal = 13;
var seenLines = {};
var cmdHistory = [];
var cmdHistoryIdx = -1;
var consoleState = {};
var editProjectId = null;
var editBuildId = null;
var pdProjectId = null;
var pdMpDetailId = null;
var pdMpEditId = null;

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

function closeModal(id) { document.getElementById(id).style.display = 'none'; }

function switchTab(name) {
    clearServerPolling();
    document.getElementById('serverDetailView').style.display = 'none';
    document.getElementById('serverMiniBar').style.display = 'none';
    document.querySelectorAll('.sidebar-server-item').forEach(function (s) { s.classList.remove('active'); });
    document.querySelectorAll('.server-tab').forEach(function (t) { t.classList.remove('active'); });
    currentServerId = null;
    document.querySelectorAll('.panel').forEach(function (p) { p.classList.remove('active'); });
    document.querySelectorAll('.nav-item').forEach(function (t) { t.classList.remove('active'); });
    document.getElementById(name + 'Panel').classList.add('active');
    var navItem = document.querySelector('.nav-item[data-tab="' + name + '"]');
    if (navItem) navItem.classList.add('active');
    var titles = { projects: 'Projects', players: 'Players', config: 'Config', java: 'Java' };
    var titleEl = document.getElementById('pageTitle');
    if (titleEl) titleEl.textContent = titles[name] || name;
    var actions = document.getElementById('topActions');
    actions.innerHTML = '';
    if (name === 'projects') { loadProjects(); }
    if (name === 'players') { loadPlayers(); }
    if (name === 'config') { loadGlobalConfig(); }
    if (name === 'java') { loadJavaRuntimes(); }
}

function clearServerPolling() {
    if (serverPollTimer) { clearInterval(serverPollTimer); serverPollTimer = null; }
}

function selectServer(id) {
    clearServerPolling();
    document.querySelectorAll('.panel').forEach(function (p) { p.classList.remove('active'); });
    document.querySelectorAll('.nav-item').forEach(function (t) { t.classList.remove('active'); });
    document.querySelectorAll('.sidebar-server-item').forEach(function (s) { s.classList.remove('active'); });
    document.querySelectorAll('.server-tab').forEach(function (t) { t.classList.remove('active'); });
    document.getElementById('serversPanel').classList.add('active');
    var sidebarItem = document.querySelector('.sidebar-server-item[data-server="' + id + '"]');
    if (sidebarItem) sidebarItem.classList.add('active');
    var tab = document.querySelector('.server-tab[data-server="' + id + '"]');
    if (tab) tab.classList.add('active');
    document.getElementById('pageTitle').textContent = 'Server';
    document.getElementById('topActions').innerHTML = '';
    openServerDetail(id);
}

function renderServerNav() {
    apiFetch('/admin/instances').then(function (r) {
        if (!r) return;
        r.json().then(function (servers) {
            renderSidebarServers(servers);
            renderServerTabs(servers);
        });
    });
}

function renderSidebarServers(servers) {
    var list = document.getElementById('sidebarServerList');
    list.innerHTML = '';
    if (!servers.length) {
        list.innerHTML = '<div class="nav-item nav-placeholder">No servers</div>';
        return;
    }
    for (var i = 0; i < servers.length; i++) {
        var s = servers[i];
        var btn = document.createElement('button');
        btn.className = 'nav-item sidebar-server-item' + (currentServerId === s.id ? ' active' : '');
        btn.setAttribute('data-server', s.id);
        btn.onclick = function (id) { return function () { selectServer(id); }; }(s.id);
        var modpackTag = s.modpack_name ? '<span class="tag tag-file" style="margin-left:6px;font-size:10px">' + esc(s.modpack_name) + '</span>' : '';
        btn.innerHTML = '<span class="server-dot ' + (s.running ? 'dot-on' : 'dot-off') + '"></span>' + esc(s.name || s.id) + modpackTag;
        list.appendChild(btn);
    }
}

function renderServerTabs(servers) {
    var bar = document.getElementById('serverTabBar');
    var tabs = document.getElementById('serverTabs');
    tabs.innerHTML = '';
    if (!servers.length) {
        bar.style.display = 'none';
        return;
    }
    bar.style.display = 'flex';
    for (var i = 0; i < servers.length; i++) {
        var s = servers[i];
        var tab = document.createElement('button');
        tab.className = 'server-tab' + (currentServerId === s.id ? ' active' : '');
        tab.setAttribute('data-server', s.id);
        tab.onclick = function (id) { return function () { selectServer(id); }; }(s.id);
        tab.innerHTML = '<span class="server-dot ' + (s.running ? 'dot-on' : 'dot-off') + '"></span>' + esc(s.name || s.id);
        tabs.appendChild(tab);
    }
}

function esc(s) { var d = document.createElement('div'); d.textContent = s || ''; return d.innerHTML; }
function escAttr(s) { return (s || '').replace(/'/g, "\\'"); }

/* ===================== PROJECTS ===================== */

async function loadProjects() {
    document.getElementById('projectDetailView').style.display = 'none';
    document.getElementById('projectListView').style.display = 'block';
    var grid = document.getElementById('projectsGrid');
    grid.innerHTML = '<div style="color:#888;padding:16px">Loading...</div>';
    try {
        var r = await apiFetch('/projects');
        if (!r) return;
        var projects = await r.json();
        if (!projects.length) {
            grid.innerHTML = '<div style="color:#888;padding:32px;text-align:center">No projects yet. Click "Add Project" to create one.</div>';
            return;
        }
        var html = '';
        for (var i = 0; i < projects.length; i++) {
            var p = projects[i];
            var pc = p.primary_color || '#6c63ff';
            html += '<div class="project-card" onclick="openProjectDetail(\'' + escAttr(p.id) + '\')" style="border-left:4px solid ' + pc + '">' +
                '<div class="project-card-header">' +
                '<div class="project-card-icon" style="background:' + pc + '">' + esc((p.brand_name || p.name).charAt(0).toUpperCase()) + '</div>' +
                '<div class="project-card-info">' +
                '<div class="project-card-title">' + esc(p.name) + '</div>' +
                '<div class="project-card-id">' + esc(p.id) + '</div>' +
                '</div></div>' +
                '<div class="project-card-desc">' + esc(p.description || 'No description') + '</div>' +
                '<div class="project-card-footer"></div></div>';
        }
        grid.innerHTML = html;
    } catch (e) { grid.innerHTML = '<div style="color:#d32f2f">Failed to load: ' + esc(e.message) + '</div>'; }
}

function showAddProject() {
    document.getElementById('projId').value = '';
    document.getElementById('projName').value = '';
    document.getElementById('projDesc').value = '';
    document.getElementById('projBrand').value = '';
    document.getElementById('projWindowTitle').value = '';
    document.getElementById('projColor').value = '#6c63ff';
    document.getElementById('projAccent').value = '';
    document.getElementById('projLogo').value = '';
    document.getElementById('projBg').value = '';
    document.getElementById('addProjectModal').style.display = 'flex';
}

async function confirmAddProject() {
    var id = document.getElementById('projId').value.trim();
    var name = document.getElementById('projName').value.trim() || id;
    if (!id) { toast('Project ID is required', 'error'); return; }
    try {
        var r = await apiFetch('/projects', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                id: id, name: name,
                description: document.getElementById('projDesc').value.trim(),
                brand_name: document.getElementById('projBrand').value.trim(),
                window_title: document.getElementById('projWindowTitle').value.trim(),
                primary_color: document.getElementById('projColor').value.trim() || '#6c63ff',
                accent_color: document.getElementById('projAccent').value.trim(),
                logo_url: document.getElementById('projLogo').value.trim(),
                background_url: document.getElementById('projBg').value.trim()
            })
        });
        if (!r) return;
        var d = await r.json();
        if (d.error) { toast(d.error, 'error'); return; }
        toast('Project "' + name + '" created', 'success');
        closeModal('addProjectModal');
        loadProjects();
    } catch (e) { toast('Failed: ' + e.message, 'error'); }
}

/* ===================== PROJECT DETAIL ===================== */

async function openProjectDetail(pid) {
    pdProjectId = pid;
    document.getElementById('projectListView').style.display = 'none';
    document.getElementById('projectDetailView').style.display = 'block';
    loadProjectDetail();
}

function closeProjectDetail() {
    pdProjectId = null;
    pdMpDetailId = null;
    document.getElementById('projectDetailView').style.display = 'none';
    document.getElementById('projectListView').style.display = 'block';
}

async function loadProjectDetail() {
    if (!pdProjectId) return;
    try {
        var r = await apiFetch('/projects/' + pdProjectId);
        if (!r) return;
        var p = await r.json();
        document.getElementById('pdTitle').textContent = p.name || pdProjectId;
        var meta = '';
        if (p.description) meta += esc(p.description);
        document.getElementById('pdMeta').innerHTML = meta || '';
        loadPdLinkedServers();
        loadPdModpacks();
    } catch (e) { toast('Failed: ' + e.message, 'error'); }
}

async function loadPdLinkedServers() {
    var el = document.getElementById('pdLinkedServers');
    try {
        var r = await apiFetch('/admin/instances');
        if (!r) { el.style.display = 'none'; return; }
        var all = await r.json();
        var linked = all.filter(function(s) { return s.project_id === pdProjectId; });
        if (!linked.length) { el.style.display = 'none'; return; }
        el.style.display = 'block';
        var html = '<strong>Servers using this project:</strong> ';
        html += linked.map(function(s) {
            return '<a href="#" onclick="switchToServer(\'' + escAttr(s.id) + '\');return false">' + esc(s.name) + '</a>';
        }).join(', ');
        el.innerHTML = html;
    } catch (e) { el.style.display = 'none'; }
}

function showEditProjectFromDetail() {
    if (!pdProjectId) return;
    editProjectId = pdProjectId;
    apiFetch('/projects/' + pdProjectId).then(function(r) {
        if (!r) return;
        r.json().then(function(p) {
            document.getElementById('editProjName').value = p.name || '';
            document.getElementById('editProjDesc').value = p.description || '';
            document.getElementById('editProjBrand').value = p.brand_name || '';
            document.getElementById('editProjWindowTitle').value = p.window_title || '';
            document.getElementById('editProjColor').value = p.primary_color || '#6c63ff';
            document.getElementById('editProjAccent').value = p.accent_color || '';
            document.getElementById('editProjLogo').value = p.logo_url || '';
            document.getElementById('editProjBg').value = p.background_url || '';
            document.getElementById('editProjectModal').style.display = 'flex';
        });
    });
}

async function confirmEditProject() {
    if (!editProjectId) return;
    try {
        var r = await apiFetch('/projects/' + editProjectId, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: document.getElementById('editProjName').value.trim(),
                description: document.getElementById('editProjDesc').value.trim(),
                brand_name: document.getElementById('editProjBrand').value.trim(),
                window_title: document.getElementById('editProjWindowTitle').value.trim(),
                primary_color: document.getElementById('editProjColor').value.trim() || '#6c63ff',
                accent_color: document.getElementById('editProjAccent').value.trim(),
                logo_url: document.getElementById('editProjLogo').value.trim(),
                background_url: document.getElementById('editProjBg').value.trim()
            })
        });
        if (!r) return;
        var d = await r.json();
        if (d.error) { toast(d.error, 'error'); return; }
        toast('Project updated', 'success');
        closeModal('editProjectModal');
        editProjectId = null;
        loadProjectDetail();
    } catch (e) { toast('Failed: ' + e.message, 'error'); }
}

async function confirmDeleteProjectById() {
    if (!pdProjectId || !confirm('Delete project "' + pdProjectId + '"?')) return;
    try {
        var r = await apiFetch('/projects/' + pdProjectId, { method: 'DELETE' });
        if (!r) return;
        var d = await r.json();
        if (d.error) { toast(d.error, 'error'); return; }
        toast('Project deleted', 'info');
        closeProjectDetail();
        loadProjects();
    } catch (e) { toast('Failed: ' + e.message, 'error'); }
}

async function confirmDeleteProjectModal() {
    if (!editProjectId || !confirm('Delete project "' + editProjectId + '"?')) return;
    try {
        var r = await apiFetch('/projects/' + editProjectId, { method: 'DELETE' });
        if (!r) return;
        var d = await r.json();
        if (d.error) { toast(d.error, 'error'); return; }
        toast('Project deleted', 'info');
        closeModal('editProjectModal');
        editProjectId = null;
        if (pdProjectId) { closeProjectDetail(); }
        loadProjects();
    } catch (e) { toast('Failed: ' + e.message, 'error'); }
}

/* ===================== MODPACKS (inside project detail) ===================== */

async function loadPdModpacks() {
    var container = document.getElementById('pdMpCards');
    container.innerHTML = '<div style="color:#888;padding:16px">Loading modpacks...</div>';
    try {
        var r = await apiFetch('/admin/projects/' + pdProjectId + '/modpacks');
        if (!r) return;
        var modpacks = await r.json();
        if (!modpacks.length) {
            container.innerHTML = '<div style="color:#888;padding:16px;text-align:center">No modpacks yet. Create one above.</div>';
            return;
        }
        var html = '';
        for (var i = 0; i < modpacks.length; i++) {
            var m = modpacks[i];
            var mcInfo = m.mc_version ? 'MC ' + esc(m.mc_version) : '';
            if (m.loader) mcInfo += ' [' + esc(m.loader) + ' ' + esc(m.loader_version || '') + ']';
            html += '<div class="project-card" style="border-left:4px solid #42a5f5;cursor:pointer" onclick="openPdMpDetail(\'' + escAttr(m.id) + '\')">' +
                '<div class="project-card-header">' +
                '<div class="project-card-icon" style="background:#42a5f5">' + esc(m.name.charAt(0).toUpperCase()) + '</div>' +
                '<div class="project-card-info">' +
                '<div class="project-card-title">' + esc(m.name) + '</div>' +
                '<div class="project-card-id">v' + esc(m.version) + ' | ' + m.file_count + ' file(s) | ' + mcInfo + '</div>' +
                '</div></div>' +
                '<div class="project-card-desc">' + esc(m.description || 'No description') + '</div>' +
                '<div class="project-card-footer">' +
                '<button class="btn btn-sm btn-secondary" onclick="event.stopPropagation();openEditMp(\'' + escAttr(m.id) + '\')">Edit</button>' +
                '<button class="btn btn-sm btn-secondary" onclick="event.stopPropagation();deleteMpModpack(\'' + escAttr(m.id) + '\')">Delete</button>' +
                '</div></div>';
        }
        container.innerHTML = html;
    } catch (e) { container.innerHTML = '<div style="color:#d32f2f">Failed: ' + esc(e.message) + '</div>'; }
}

async function confirmCreateModpack() {
    if (!pdProjectId) { toast('No project selected', 'error'); return; }
    var name = document.getElementById('pdCreateName').value.trim();
    if (!name) { toast('Modpack name is required', 'error'); return; }
    var desc = document.getElementById('pdCreateDesc').value.trim();
    var ver = document.getElementById('pdCreateVer').value.trim() || '1.0';
    var mcVer = document.getElementById('pdCreateMcVer').value.trim();
    var loader = document.getElementById('pdCreateLoader').value;
    var loaderVer = document.getElementById('pdCreateLoaderVer').value.trim();
    try {
        var r = await apiFetch('/admin/projects/' + pdProjectId + '/modpacks', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: name, description: desc, version: ver, mc_version: mcVer, loader: loader, loader_version: loaderVer })
        });
        if (!r) return;
        var d = await r.json();
        if (d.error) { toast(d.error, 'error'); return; }
        toast('Modpack "' + name + '" created', 'success');
        document.getElementById('pdCreateName').value = '';
        document.getElementById('pdCreateDesc').value = '';
        document.getElementById('pdCreateVer').value = '1.0';
        document.getElementById('pdCreateMcVer').value = '';
        document.getElementById('pdCreateLoader').value = '';
        document.getElementById('pdCreateLoaderVer').value = '';
        loadPdModpacks();
    } catch (e) { toast('Failed: ' + e.message, 'error'); }
}

function openEditMp(mpid) {
    pdMpEditId = mpid;
    apiFetch('/admin/projects/' + pdProjectId + '/modpacks/' + mpid).then(function(r) {
        if (!r) return;
        r.json().then(function(m) {
            document.getElementById('editMpName').value = m.name || '';
            document.getElementById('editMpDesc').value = m.description || '';
            document.getElementById('editMpVer').value = m.version || '';
            document.getElementById('editMpMcVer').value = m.mc_version || '';
            document.getElementById('editMpLoader').value = m.loader || '';
            document.getElementById('editMpLoaderVer').value = m.loader_version || '';
            document.getElementById('editMpChangelog').value = m.changelog || '';
            document.getElementById('editModpackModal').style.display = 'flex';
        });
    });
}

async function confirmEditModpack() {
    if (!pdProjectId || !pdMpEditId) return;
    try {
        var r = await apiFetch('/admin/projects/' + pdProjectId + '/modpacks/' + pdMpEditId, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: document.getElementById('editMpName').value.trim(),
                description: document.getElementById('editMpDesc').value.trim(),
                version: document.getElementById('editMpVer').value.trim(),
                mc_version: document.getElementById('editMpMcVer').value.trim(),
                loader: document.getElementById('editMpLoader').value,
                loader_version: document.getElementById('editMpLoaderVer').value.trim(),
                changelog: document.getElementById('editMpChangelog').value.trim(),
            })
        });
        if (!r) return;
        var d = await r.json();
        if (d.error) { toast(d.error, 'error'); return; }
        toast('Modpack updated', 'success');
        closeModal('editModpackModal');
        pdMpEditId = null;
        loadPdModpacks();
    } catch (e) { toast('Failed: ' + e.message, 'error'); }
}

async function confirmDeleteModpack() {
    if (!pdProjectId || !pdMpEditId || !confirm('Delete this modpack?')) return;
    try {
        var r = await apiFetch('/admin/projects/' + pdProjectId + '/modpacks/' + pdMpEditId, { method: 'DELETE' });
        if (!r) return;
        var d = await r.json();
        if (d.error) { toast(d.error, 'error'); return; }
        toast('Modpack deleted', 'info');
        closeModal('editModpackModal');
        pdMpEditId = null;
        if (pdMpDetailId === pdMpEditId) { closeMpDetail(); }
        loadPdModpacks();
    } catch (e) { toast('Failed: ' + e.message, 'error'); }
}

async function deleteMpModpack(mpid) {
    if (!confirm('Delete this modpack and all its files?')) return;
    try {
        var r = await apiFetch('/admin/projects/' + pdProjectId + '/modpacks/' + mpid, { method: 'DELETE' });
        if (!r) return;
        var d = await r.json();
        if (d.error) { toast(d.error, 'error'); return; }
        toast('Modpack deleted', 'info');
        if (pdMpDetailId === mpid) { closeMpDetail(); }
        loadPdModpacks();
    } catch (e) { toast('Failed: ' + e.message, 'error'); }
}

function closeMpDetail() {
    document.getElementById('pdMpDetail').style.display = 'none';
    pdMpDetailId = null;
}

async function openPdMpDetail(mpid) {
    pdMpDetailId = mpid;
    document.getElementById('pdMpDetail').style.display = 'block';
    switchMpSubTab('files');
    try {
        var r = await apiFetch('/admin/projects/' + pdProjectId + '/modpacks/' + mpid);
        if (!r) return;
        var m = await r.json();
        document.getElementById('pdMpDetailTitle').textContent = m.name + ' v' + m.version;
        var metaHtml = '';
        if (m.mc_version) metaHtml += '<strong>MC:</strong> ' + esc(m.mc_version) + ' ';
        if (m.loader) metaHtml += '<strong>Loader:</strong> ' + esc(m.loader) + ' ' + esc(m.loader_version || '') + ' ';
        if (m.changelog) metaHtml += '<br><em>' + esc(m.changelog) + '</em>';
        document.getElementById('pdMpDetailMeta').innerHTML = metaHtml || 'No additional info';
        loadPdMpLinkedServers(mpid);
        loadPdMpFiles();
        loadPdMpMods();
    } catch (e) { toast('Failed: ' + e.message, 'error'); }
}

function switchMpSubTab(tab) {
    document.querySelectorAll('[data-mp-subtab]').forEach(function(el) {
        el.classList.toggle('active', el.dataset.mpSubtab === tab);
    });
    document.querySelectorAll('#pdMpDetail .server-sub-panel').forEach(function(el) {
        el.classList.toggle('active', el.id === 'pdMp' + tab.charAt(0).toUpperCase() + tab.slice(1) + 'View');
    });
}

async function loadPdMpMods() {
    var container = document.getElementById('pdMpModsList');
    if (!pdProjectId || !pdMpDetailId) return;
    container.innerHTML = '<div style="color:#888;padding:16px">Loading mods...</div>';
    try {
        var r = await apiFetch('/admin/projects/' + pdProjectId + '/modpacks/' + pdMpDetailId + '/mods');
        if (!r) return;
        var d = await r.json();
        if (d.error) { container.innerHTML = '<div class="error-msg">' + esc(d.error) + '</div>'; return; }
        if (!d.items || !d.items.length) {
            container.innerHTML = '<div style="color:#888;padding:16px;text-align:center">No mods (jar files) found.</div>';
            return;
        }
        var html = '<table><thead><tr><th>Name</th><th>Size</th><th>SHA256</th></tr></thead><tbody>';
        for (var i = 0; i < d.items.length; i++) {
            var item = d.items[i];
            var sha = item.sha256 ? item.sha256.slice(0, 12) + '...' : '-';
            html += '<tr><td>' + esc(item.name) + '</td><td>' + formatSize(item.size) + '</td><td><code>' + esc(sha) + '</code></td></tr>';
        }
        html += '</tbody></table>';
        container.innerHTML = html;
    } catch (e) { container.innerHTML = '<div class="error-msg">Failed: ' + esc(e.message) + '</div>'; }
}

var mpBrowsePath = '';

async function loadPdMpFiles(path) {
    mpBrowsePath = path || '';
    var container = document.getElementById('pdMpFileList');
    var dirDisplay = document.getElementById('pdMpDir');
    if (!pdProjectId || !pdMpDetailId) return;
    container.innerHTML = '<div style="color:#888;padding:16px">Loading files...</div>';
    try {
        var url = '/admin/projects/' + pdProjectId + '/modpacks/' + pdMpDetailId + '/files';
        if (path) url += '?path=' + encodeURIComponent(path);
        var r = await apiFetch(url);
        if (!r) return;
        var d = await r.json();
        dirDisplay.textContent = '/' + (d.path || '') + '  (' + (d.items ? d.items.length : 0) + ' items)';
        if (d.error) { container.innerHTML = '<div class="error-msg">' + esc(d.error) + '</div>'; return; }
        var html = '<table><thead><tr><th>Name</th><th>Size</th><th>Modified</th><th>Actions</th></tr></thead><tbody>';
        if (d.path) {
            var parentPath = d.path.replace(/\/?[^/]+$/, '');
            html += '<tr class="file-dir" onclick="loadPdMpFiles(\'' + escAttr(parentPath) + '\')"><td><span class="tag tag-dir">DIR</span> ..</td><td></td><td></td><td></td></tr>';
        }
        for (var i = 0; i < (d.items || []).length; i++) {
            var item = d.items[i];
            var label = item.is_dir ? '<span class="tag tag-dir">DIR</span>' : '<span class="tag tag-file">FILE</span>';
            var childPath = d.path ? d.path + '/' + item.name : item.name;
            var clickHandler = item.is_dir
                ? 'loadPdMpFiles(\'' + escAttr(childPath) + '\')'
                : 'openMpFileEditor(\'' + escAttr(childPath) + '\')';
            var sizeStr = item.is_dir ? '-' : formatSize(item.size);
            var dateStr = new Date(item.modified * 1000).toLocaleString();
            var actions = '';
            if (!item.is_dir) {
                actions += '<button class="btn btn-sm btn-secondary" onclick="event.stopPropagation();openMpFileEditor(\'' + escAttr(childPath) + '\')">Edit</button>';
                actions += '<a class="btn btn-sm btn-secondary" href="/admin/projects/' + pdProjectId + '/modpacks/' + pdMpDetailId + '/files/download?path=' + encodeURIComponent(childPath) + '" style="text-decoration:none">Download</a>';
            }
            actions += '<button class="btn btn-sm btn-secondary" onclick="event.stopPropagation();deleteMpFile(\'' + escAttr(childPath) + '\')">Delete</button>';
            html += '<tr class="' + (item.is_dir ? 'file-dir' : 'file-file') + '" onclick="' + clickHandler + '"><td>' + label + ' ' + esc(item.name) + '</td><td>' + sizeStr + '</td><td>' + dateStr + '</td><td>' + actions + '</td></tr>';
        }
        html += '</tbody></table>';
        container.innerHTML = html;
    } catch (e) { container.innerHTML = '<div class="error-msg">Failed: ' + esc(e.message) + '</div>'; }
}

async function openMpFileEditor(filePath) {
    if (!pdProjectId || !pdMpDetailId) return;
    try {
        var r = await apiFetch('/admin/projects/' + pdProjectId + '/modpacks/' + pdMpDetailId + '/files/read?path=' + encodeURIComponent(filePath));
        if (!r) return;
        var d = await r.json();
        if (d.error) { toast(d.error, 'error'); return; }
        if (!d.is_text) { toast('Binary files cannot be edited', 'error'); return; }
        var container = document.getElementById('pdMpFileList');
        container.innerHTML = '<div class="md-card" style="margin:0;padding:16px"><div class="row"><strong>Editing:</strong> <span style="font-family:monospace;color:#1976d2;flex:1">' + esc(d.path) + '</span>' +
            '<button class="btn btn-start btn-sm" onclick="saveMpFile(\'' + escAttr(filePath) + '\')">Save</button>' +
            '<button class="btn btn-secondary btn-sm" onclick="loadPdMpFiles(\'' + escAttr(mpBrowsePath) + '\')">Close</button></div>' +
            '<textarea id="mpFileEditorText" style="width:100%;height:400px;font:13px/1.6 monospace;padding:12px;border:2px solid #bdbdbd;border-radius:4px;resize:vertical;margin-top:12px" spellcheck="false">' + esc(d.content) + '</textarea></div>';
    } catch (e) { toast('Failed: ' + e.message, 'error'); }
}

async function saveMpFile(filePath) {
    if (!pdProjectId || !pdMpDetailId) return;
    var content = document.getElementById('mpFileEditorText').value;
    try {
        var r = await apiFetch('/admin/projects/' + pdProjectId + '/modpacks/' + pdMpDetailId + '/files/write', {
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

async function deleteMpFile(filePath) {
    if (!pdProjectId || !pdMpDetailId || !confirm('Delete "' + filePath + '"?')) return;
    try {
        var r = await apiFetch('/admin/projects/' + pdProjectId + '/modpacks/' + pdMpDetailId + '/files?path=' + encodeURIComponent(filePath), {
            method: 'DELETE'
        });
        if (!r) return;
        var d = await r.json();
        if (d.error) { toast(d.error, 'error'); return; }
        toast('Deleted', 'info');
        loadPdMpFiles(mpBrowsePath);
    } catch (e) { toast('Failed: ' + e.message, 'error'); }
}

async function uploadMpFile(input) {
    if (!pdProjectId || !pdMpDetailId) { toast('Select a modpack first', 'error'); return; }
    for (var fi = 0; fi < input.files.length; fi++) {
        var file = input.files[fi];
        var formData = new FormData();
        formData.append('file', file);
        if (mpBrowsePath) formData.append('path', mpBrowsePath);
        try {
            var r = await apiFetch('/admin/projects/' + pdProjectId + '/modpacks/' + pdMpDetailId + '/files/upload', {
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
    loadPdMpFiles(mpBrowsePath);
}

async function loadPdMpLinkedServers(mpid) {
    var el = document.getElementById('pdMpLinkedServers');
    try {
        var r = await apiFetch('/admin/instances');
        if (!r) { el.style.display = 'none'; return; }
        var all = await r.json();
        var linked = all.filter(function(s) { return s.modpack_id === mpid; });
        if (!linked.length) { el.style.display = 'none'; return; }
        el.style.display = 'block';
        var html = '<strong>Used by servers:</strong> ';
        html += linked.map(function(s) {
            return '<a href="#" onclick="switchToServer(\'' + escAttr(s.id) + '\');return false">' + esc(s.name) + '</a>';
        }).join(', ');
        el.innerHTML = html;
    } catch (e) { el.style.display = 'none'; }
}

async function switchToServer(sid) {
    switchTab('servers');
    setTimeout(function() { selectServer(sid); }, 100);
}

async function switchToProjectModpack(pid, mpid) {
    switchTab('projects');
    pdProjectId = pid;
    pdMpDetailId = mpid;
    document.getElementById('projectListView').style.display = 'none';
    document.getElementById('projectDetailView').style.display = 'block';
    loadProjectDetail();
    setTimeout(function() { openPdMpDetail(mpid); }, 300);
}

async function importMpArchive(input) {
    if (!pdProjectId || !pdMpDetailId) { toast('Select a modpack first', 'error'); return; }
    var file = input.files[0];
    if (!file) return;
    var statusEl = document.getElementById('pdMpImportStatus');
    statusEl.style.display = 'block';
    statusEl.innerHTML = '<div class="progress-bar"><div class="progress-fill" id="importProgressFill" style="width:0%"></div></div>' +
        '<span id="importProgressText" style="color:#888">Uploading ' + esc(file.name) + '...</span>';
    var formData = new FormData();
    formData.append('file', file);
    try {
        var r = await apiFetch('/admin/projects/' + pdProjectId + '/modpacks/' + pdMpDetailId + '/import', {
            method: 'POST',
            body: formData
        });
        if (!r) return;
        var d = await r.json();
        if (d.error) {
            document.getElementById('importProgressText').innerHTML = '<span style="color:#d32f2f">Error: ' + esc(d.error) + '</span>';
            toast('Import failed', 'error');
            input.value = '';
            return;
        }
        var taskId = d.task_id;
        // Poll for progress
        var pollUrl = '/admin/projects/' + pdProjectId + '/modpacks/' + pdMpDetailId + '/import-progress/' + taskId;
        var pollTimer = setInterval(async function() {
            try {
                var pr = await apiFetch(pollUrl);
                if (!pr) { clearInterval(pollTimer); return; }
                var ps = await pr.json();
                if (ps.error) {
                    document.getElementById('importProgressText').innerHTML = '<span style="color:#d32f2f">Error: ' + esc(ps.error) + '</span>';
                    clearInterval(pollTimer);
                    input.value = '';
                    return;
                }
                var fill = document.getElementById('importProgressFill');
                var txt = document.getElementById('importProgressText');
                txt.textContent = ps.message || ps.status;
                if (ps.total > 0) {
                    fill.style.width = Math.round(ps.current / ps.total * 100) + '%';
                } else if (ps.status === 'hashing' || ps.status === 'extracting') {
                    fill.style.width = '50%';
                }
                if (ps.status === 'done') {
                    clearInterval(pollTimer);
                    fill.style.width = '100%';
                    var result = ps.result || {};
                    var dl = result.downloaded || 0;
                    var sk = result.skipped || 0;
                    var errList = result.errors || [];
                    var html = '<span style="color:#4caf50">Import complete. Downloaded: ' + dl + ', skipped: ' + sk + '</span>';
                    if (errList.length) {
                        html += '<div style="margin-top:6px;font-size:12px;color:#e65100"><strong>' + errList.length + ' errors:</strong><br><span style="font-family:monospace;white-space:pre-wrap">' + esc(errList.slice(0, 20).join('\n')) + '</span></div>';
                    }
                    txt.innerHTML = html;
                    toast('Import complete: ' + dl + ' downloaded, ' + errList.length + ' errors', errList.length ? 'error' : 'success');
                    loadPdMpFiles();
                    input.value = '';
                } else if (ps.status === 'error') {
                    clearInterval(pollTimer);
                    txt.innerHTML = '<span style="color:#d32f2f">Import failed: ' + esc(ps.error || 'Unknown error') + '</span>';
                    toast('Import failed', 'error');
                    input.value = '';
                }
            } catch (e) {
                clearInterval(pollTimer);
                document.getElementById('importProgressText').textContent = 'Poll error: ' + e.message;
                input.value = '';
            }
        }, 500);
    } catch (e) {
        document.getElementById('importProgressText').innerHTML = '<span style="color:#d32f2f">Upload error: ' + esc(e.message) + '</span>';
        toast('Import error: ' + e.message, 'error');
        input.value = '';
    }
}

async function extractMpArchive(input) {
    if (!pdProjectId || !pdMpDetailId) { toast('Select a modpack first', 'error'); return; }
    var file = input.files[0];
    if (!file) return;
    var clear = document.getElementById('pdMpExtractClear').checked;
    if (clear && !confirm('Clear ALL existing files before extracting? This cannot be undone.')) {
        input.value = '';
        return;
    }
    var statusEl = document.getElementById('pdMpImportStatus');
    statusEl.style.display = 'block';
    statusEl.innerHTML = '<span style="color:#888">Extracting ' + esc(file.name) + '...</span>';
    var formData = new FormData();
    formData.append('file', file);
    if (clear) formData.append('clear', 'true');
    try {
        var r = await apiFetch('/admin/projects/' + pdProjectId + '/modpacks/' + pdMpDetailId + '/files/extract', {
            method: 'POST',
            body: formData
        });
        if (!r) return;
        var d = await r.json();
        if (d.error) { statusEl.innerHTML = '<span style="color:#d32f2f">Error: ' + esc(d.error) + '</span>'; toast(d.error, 'error'); }
        else {
            statusEl.innerHTML = '<span style="color:#2e7d32">Extracted ' + d.files + ' files.</span>';
            toast('Extracted ' + d.files + ' files', 'success');
            loadPdMpFiles(mpBrowsePath);
        }
    } catch (e) {
        statusEl.innerHTML = '<span style="color:#d32f2f">Error: ' + esc(e.message) + '</span>';
        toast('Extract failed: ' + e.message, 'error');
    }
    input.value = '';
}

/* ===================== ADD SERVER MODAL ===================== */

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

/* ===================== SERVERS ===================== */

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
    currentSubTab = 'console';
    document.getElementById('serverDetailView').style.display = 'block';
    document.getElementById('serverMiniBar').style.display = 'flex';
    document.getElementById('serverConsoleOutput').innerHTML = '';
    seenLines = {};
    document.querySelectorAll('.sub-nav-item').forEach(function (n) { n.classList.remove('active'); });
    document.querySelector('.sub-nav-item[data-subtab="console"]').classList.add('active');
    document.querySelectorAll('.server-sub-panel').forEach(function (p) { p.classList.remove('active'); });
    document.getElementById('serverConsoleView').classList.add('active');
    refreshServerStatus();
    pollServerOutput();
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
    if (tab === 'settings') loadServerSettings();
    if (tab === 'files') loadServerFiles('');
}

var serverPollTimer = null;

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

/* ===================== SERVER SETTINGS ===================== */

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

/* ===================== SERVER FILES ===================== */

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

/* ===================== PLAYERS ===================== */

async function loadPlayers() {
    try {
        var r = await apiFetch('/auth/admin/users');
        if (!r) return;
        var users = await r.json();
        var tbody = document.getElementById('playersBody');
        tbody.innerHTML = '';
        for (var i = 0; i < users.length; i++) {
            var u = users[i];
            var tr = document.createElement('tr');
            tr.innerHTML = '<td>' + u.id + '</td><td>' + esc(u.username) + '</td><td>' + esc(u.display_name) + '</td><td>' + esc(u.email) + '</td><td>' + (u.created_at || '').slice(0, 10) + '</td>';
            tbody.appendChild(tr);
        }
    } catch (e) {}
}

/* ===================== CONFIG ===================== */

async function loadGlobalConfig() {
    try {
        var r = await apiFetch('/admin/config/schema');
        if (!r) return;
        var fields = await r.json();
        renderConfigForm('configForm', fields, 'saveGlobalConfig(event)');
    } catch (e) { toast('Failed: ' + e.message, 'error'); }
}

async function saveGlobalConfig(event) {
    event.preventDefault();
    var data = collectFormData('configForm');
    try {
        var r = await apiFetch('/admin/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        if (!r) return;
        var d = await r.json();
        if (r.status === 400) { toast((d.errors || []).join('; ') || 'Validation failed', 'error'); }
        else { toast('Config saved (' + Object.keys(d.updated).length + ' fields)', 'success'); }
    } catch (e) { toast('Failed: ' + e.message, 'error'); }
}

function renderConfigForm(formId, fields, onSubmit) {
    var form = document.getElementById(formId);
    form.innerHTML = '';
    for (var i = 0; i < fields.length; i++) {
        var f = fields[i];
        var group = document.createElement('div');
        group.className = 'config-field';
        var label = document.createElement('label');
        label.className = 'config-label';
        label.textContent = f.label || f.key;
        group.appendChild(label);
        var desc = document.createElement('div');
        desc.className = 'config-desc';
        desc.textContent = f.description || '';
        group.appendChild(desc);
        var input;
        if (f.type === 'password') {
            input = document.createElement('input');
            input.type = 'password';
            input.placeholder = '(unchanged if empty)';
            input.dataset.type = 'str';
            input.dataset.sensitive = 'true';
            group.appendChild(input);
        } else if (f.type === 'bool') {
            input = document.createElement('input');
            input.type = 'checkbox';
            input.checked = f.value === true || f.value === 'true';
            input.dataset.type = 'bool';
            var wrap = document.createElement('div');
            wrap.className = 'config-check-wrap';
            wrap.appendChild(input);
            group.appendChild(wrap);
        } else if (f.options) {
            input = document.createElement('select');
            for (var j = 0; j < f.options.length; j++) {
                var opt = document.createElement('option');
                var o = f.options[j];
                if (typeof o === 'object' && o.value !== undefined) {
                    opt.value = o.value;
                    opt.textContent = o.label || o.value;
                    if (o.value === f.value) opt.selected = true;
                } else {
                    opt.value = o;
                    opt.textContent = o;
                    if (o === f.value) opt.selected = true;
                }
                input.appendChild(opt);
            }
            input.dataset.type = 'str';
            group.appendChild(input);
        } else {
            input = document.createElement('input');
            input.type = f.type === 'int' ? 'number' : 'text';
            input.value = f.value != null ? f.value : '';
            input.dataset.type = f.type;
            group.appendChild(input);
        }
        input.name = f.key;
        input.className = 'config-input';
        group.appendChild(input);
        form.appendChild(group);
    }
    var btnRow = document.createElement('div');
    btnRow.className = 'row';
    btnRow.style.marginTop = '16px';
    var saveBtn = document.createElement('button');
    saveBtn.type = 'submit';
    saveBtn.className = 'btn btn-start';
    saveBtn.textContent = 'Save';
    btnRow.appendChild(saveBtn);
    form.appendChild(btnRow);
}

function collectFormData(formId) {
    var form = document.getElementById(formId);
    var inputs = form.querySelectorAll('.config-input');
    var data = {};
    for (var i = 0; i < inputs.length; i++) {
        var inp = inputs[i];
        if (inp.dataset.sensitive) { if (inp.value) data[inp.name] = inp.value; }
        else if (inp.type === 'checkbox') { data[inp.name] = inp.checked; }
        else if (inp.type === 'number') { data[inp.name] = parseInt(inp.value, 10) || 0; }
        else { data[inp.name] = inp.value; }
    }
    return data;
}

/* ===================== JAVA ===================== */

async function loadJavaRuntimes() {
    try {
        var r = await apiFetch('/admin/java');
        if (!r) return;
        var runtimes = await r.json();
        var tbody = document.getElementById('javaBody');
        tbody.innerHTML = '';
        for (var i = 0; i < runtimes.length; i++) {
            var j = runtimes[i];
            var tr = document.createElement('tr');
            tr.innerHTML = '<td>' + j.major + '</td><td>' + esc(j.version) + '</td><td>' + esc(j.vendor || '') + '</td><td>' + esc(j.arch || '') + '</td><td><code>' + esc(j.path) + '</code></td>';
            tbody.appendChild(tr);
        }
    } catch (e) {}
}

async function scanJava() {
    var btn = document.querySelector('#javaPanel .btn-start');
    btn.disabled = true;
    document.getElementById('javaScanStatus').textContent = 'Scanning...';
    try {
        var r = await apiFetch('/admin/java/scan', { method: 'POST' });
        if (!r) return;
        var d = await r.json();
        if (d.error) { toast(d.error, 'error'); }
        else { toast('Found ' + d.count + ' runtimes', 'success'); }
        loadJavaRuntimes();
    } catch (e) { toast('Scan failed: ' + e.message, 'error'); }
    btn.disabled = false;
    document.getElementById('javaScanStatus').textContent = '';
}

function formatSize(bytes) {
    if (bytes >= 1073741824) return (bytes / 1073741824).toFixed(1) + ' GB';
    if (bytes >= 1048576) return (bytes / 1048576).toFixed(1) + ' MB';
    if (bytes >= 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return bytes + ' B';
}

/* ===================== INIT ===================== */

async function init() {
    var token = getToken();
    if (!token) { window.location.href = '/admin/login'; return; }
    loadProjects();
    renderServerNav();
    loadJavaRuntimes();
}

document.addEventListener('DOMContentLoaded', init);
