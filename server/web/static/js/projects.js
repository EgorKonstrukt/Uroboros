/* ===================== Projects ===================== */

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

/* ===================== Project detail ===================== */

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

/* ===================== Modpacks (inside project detail) ===================== */

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
                actions += '<button class="btn btn-sm btn-secondary" onclick="event.stopPropagation();downloadMpPath(\'' + escAttr(childPath) + '\')">Download</button>';
            } else {
                actions += '<button class="btn btn-sm btn-secondary" onclick="event.stopPropagation();downloadMpPath(\'' + escAttr(childPath) + '\')">Download ZIP</button>';
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

async function downloadMpPath(path) {
    if (!pdProjectId || !pdMpDetailId) return;
    var fallback = path ? path.split('/').pop() : pdMpDetailId + '-files';
    await downloadBlob('/admin/projects/' + pdProjectId + '/modpacks/' + pdMpDetailId + '/files/download?path=' + encodeURIComponent(path || ''), fallback);
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
