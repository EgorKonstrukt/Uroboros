/* ===================== Players ===================== */

var playerActionId = null;
var banServerOptions = [];
var allUsers = [];
var skinActionId = null;

async function loadPlayers() {
    document.getElementById('playersStatus').textContent = 'Loading...';
    try {
        var r = await apiFetch('/admin/users');
        if (!r) return;
        allUsers = await r.json();
        document.getElementById('playersStatus').textContent = allUsers.length + ' players';
        renderPlayers();
    } catch (e) {
        document.getElementById('playersStatus').textContent = 'Failed to load';
        toast('Failed: ' + e.message, 'error');
    }
}

function playerMatches(u, q) {
    if (!q) return true;
    var hay = (u.id + ' ' + (u.display_name || '') + ' ' + (u.username || '') + ' ' +
        (u.email || '') + ' ' + (u.last_ip || '') + ' ' + (u.uuid || '')).toLowerCase();
    return hay.indexOf(q) !== -1;
}

function renderPlayers() {
    var q = (document.getElementById('playersSearch').value || '').trim().toLowerCase();
    var users = allUsers.filter(function (u) { return playerMatches(u, q); });
    document.getElementById('playersStatus').textContent = allUsers.length + ' players' +
        (q && users.length !== allUsers.length ? ' (' + users.length + ' shown)' : '');
    var tbody = document.getElementById('playersBody');
    tbody.innerHTML = '';
    for (var i = 0; i < users.length; i++) {
        var u = users[i];
        var tr = document.createElement('tr');
        var bansHtml = '';
        if (u.bans && u.bans.length) {
            for (var j = 0; j < u.bans.length; j++) {
                var b = u.bans[j];
                var when = b.permanent ? 'Forever' : ('until ' + (b.expires_at || '').replace('T', ' ').slice(0, 16));
                var where = b.instance_name || b.instance_id || 'All servers';
                var viaNote = '';
                if (!b.owner && b.via && b.via.length) viaNote = ' via ' + b.via.join(', ');
                var unbanBtn = b.owner
                    ? '<button class="ban-chip-x" title="Unban this" onclick="unbanPlayer(' + u.id + ',' + b.id + ')">✕</button>'
                    : '';
                bansHtml += '<div class="ban-chip"><span class="ban-chip-title">' + esc(where) + ' — ' + esc(when) + '</span>' +
                    (b.reason ? '<span class="ban-chip-reason">' + esc(b.reason) + '</span>' : '') +
                    (viaNote ? '<span class="ban-chip-reason">' + esc(viaNote) + '</span>' : '') +
                    unbanBtn + '</div>';
            }
        } else {
            bansHtml = '<span class="status-text">—</span>';
        }
        var statusHtml = '';
        if (u.online) {
            statusHtml = '<span class="status-online">Online</span>';
            if (u.current_server_name || u.current_server) {
                statusHtml += '<div class="status-sub">' + esc(u.current_server_name || u.current_server) + '</div>';
            }
        } else {
            statusHtml = '<span class="status-text">Offline</span>';
            if (u.last_seen) {
                statusHtml += '<div class="status-sub">last: ' + esc(String(u.last_seen).replace('T', ' ').slice(0, 16)) + '</div>';
            }
        }
        var ipCell = esc(u.last_ip || '—');
        if (u.ip_history && u.ip_history.length > 1) {
            ipCell += ' <span class="status-sub">(' + u.ip_history.length + ')</span>';
        }
        var actions =
            '<button class="btn btn-secondary btn-sm" onclick="openEditNickModal(' + u.id + ',\'' + escAttr(u.display_name) + '\')">Nick</button>' +
            '<button class="btn btn-secondary btn-sm" onclick="openEmailModal(' + u.id + ',\'' + escAttr(u.email || '') + '\')">Email</button>' +
            '<button class="btn btn-secondary btn-sm" onclick="openPassModal(' + u.id + ')">Pass</button>' +
            '<button class="btn btn-secondary btn-sm" onclick="openIpsModal(' + u.id + ',\'' + escAttr(u.display_name) + '\')">IPs</button>' +
            '<button class="btn btn-secondary btn-sm" onclick="openSkinModal(' + u.id + ',\'' + escAttr(u.display_name) + '\',' + (u.has_skin ? '1' : '0') + ')">Skin</button>' +
            '<button class="btn btn-stop btn-sm" onclick="openBanModal(' + u.id + ',\'' + escAttr(u.display_name) + '\')">Ban</button>' +
            (u.bans && u.bans.length ? '<button class="btn btn-start btn-sm" onclick="unbanPlayer(' + u.id + ')">Unban</button>' : '') +
            '<button class="btn btn-stop btn-sm" onclick="deletePlayer(' + u.id + ',\'' + escAttr(u.display_name) + '\')">Del</button>';
        tr.innerHTML = '<td>' + u.id + '</td>' +
            '<td><strong>' + esc(u.display_name) + '</strong></td>' +
            '<td>' + esc(u.username) + '</td>' +
            '<td>' + esc(u.email || '') + '</td>' +
            '<td>' + ipCell + '</td>' +
            '<td>' + statusHtml + '</td>' +
            '<td>' + (u.created_at || '').slice(0, 10) + '</td>' +
            '<td>' + bansHtml + '</td>' +
            '<td class="players-actions">' + actions + '</td>';
        tbody.appendChild(tr);
    }
    if (!users.length) {
        document.getElementById('playersStatus').textContent = allUsers.length ? 'No matches' : 'No players yet';
    }
}

function openIpsModal(userId, nick) {
    var u = null;
    for (var i = 0; i < allUsers.length; i++) {
        if (allUsers[i].id === userId) { u = allUsers[i]; break; }
    }
    if (!u) { toast('User not found', 'error'); return; }
    document.getElementById('ipHistoryTitle').textContent = 'IP Addresses: ' + (nick || userId);
    var tbody = document.getElementById('ipHistoryBody');
    tbody.innerHTML = '';
    var rows = u.ip_history || [];
    if (u.last_ip) {
        var found = rows.some(function (e) { return e.ip === u.last_ip; });
        if (!found) rows = [{ ip: u.last_ip, last_seen: '' }].concat(rows);
    }
    if (!rows.length) {
        tbody.innerHTML = '<tr><td colspan="2" class="status-text">No IPs recorded</td></tr>';
    } else {
        for (var j = 0; j < rows.length; j++) {
            var ts = rows[j].last_seen ? String(rows[j].last_seen).replace('T', ' ').slice(0, 16) : '';
            var cur = rows[j].ip === u.last_ip ? ' <span class="status-online" style="font-size:10px">current</span>' : '';
            var tr = document.createElement('tr');
            tr.innerHTML = '<td><code>' + esc(rows[j].ip) + '</code>' + cur + '</td><td>' + esc(ts) + '</td>';
            tbody.appendChild(tr);
        }
    }
    openModal('ipHistoryModal');
}

function openEmailModal(userId, currentEmail) {
    playerActionId = userId;
    document.getElementById('emailInput').value = currentEmail || '';
    openModal('emailModal');
}

async function confirmEmailChange() {
    if (!playerActionId) return;
    var email = document.getElementById('emailInput').value.trim();
    if (!email) { toast('Email is required', 'error'); return; }
    try {
        var r = await apiFetch('/admin/users/' + playerActionId + '/email', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email: email })
        });
        if (!r) return;
        var d = await r.json();
        if (d.error) { toast(d.error, 'error'); return; }
        toast('Email changed', 'success');
        closeModal('emailModal');
        loadPlayers();
    } catch (e) { toast('Failed: ' + e.message, 'error'); }
}

function openSkinModal(userId, nick, hasSkin) {
    skinActionId = userId;
    document.getElementById('skinModalTitle').textContent = 'Change Skin: ' + (nick || userId);
    document.getElementById('skinFileInput').value = '';
    document.getElementById('skinModelSelect').value = 'classic';
    document.getElementById('skinRemoveBtn').style.display = hasSkin ? 'inline-block' : 'none';
    var img = document.getElementById('skinPreview');
    var u = null;
    for (var i = 0; i < allUsers.length; i++) {
        if (allUsers[i].id === userId) { u = allUsers[i]; break; }
    }
    if (u && u.has_skin) {
        img.src = '/auth/skin/' + u.uuid;
        img.style.visibility = 'visible';
        document.getElementById('skinModelSelect').value = u.skin_model || 'classic';
    } else {
        img.removeAttribute('src');
        img.style.visibility = 'hidden';
    }
    openModal('skinModal');
}

async function confirmUploadSkin() {
    if (!skinActionId) return;
    var input = document.getElementById('skinFileInput');
    if (!input.files || !input.files.length) {
        toast('Select a skin file first', 'error');
        return;
    }
    var file = input.files[0];
    if (file.size > 10 * 1024 * 1024) { toast('Skin file too large (max 10 MB)', 'error'); return; }
    var formData = new FormData();
    formData.append('file', file);
    formData.append('model', document.getElementById('skinModelSelect').value);
    try {
        var r = await apiFetch('/admin/users/' + skinActionId + '/skin', {
            method: 'POST',
            body: formData
        });
        if (!r) return;
        var d = await r.json();
        if (d.error) { toast(d.error, 'error'); return; }
        toast('Skin uploaded', 'success');
        closeModal('skinModal');
        loadPlayers();
    } catch (e) { toast('Failed: ' + e.message, 'error'); }
}

async function confirmRemoveSkin() {
    if (!skinActionId) return;
    if (!confirm('Remove this player\'s skin?')) return;
    try {
        var r = await apiFetch('/admin/users/' + skinActionId + '/skin', { method: 'DELETE' });
        if (!r) return;
        var d = await r.json();
        if (d.error) { toast(d.error, 'error'); return; }
        toast('Skin removed', 'success');
        closeModal('skinModal');
        loadPlayers();
    } catch (e) { toast('Failed: ' + e.message, 'error'); }
}

function openEditNickModal(userId, currentNick) {
    playerActionId = userId;
    document.getElementById('editNickInput').value = currentNick || '';
    openModal('editNickModal');
}

async function confirmEditNick() {
    if (!playerActionId) return;
    var nick = document.getElementById('editNickInput').value.trim();
    if (!nick) { toast('Nickname is required', 'error'); return; }
    try {
        var r = await apiFetch('/admin/users/' + playerActionId + '/nickname', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ display_name: nick })
        });
        if (!r) return;
        var d = await r.json();
        if (d.error) { toast(d.error, 'error'); return; }
        toast('Nickname changed', 'success');
        closeModal('editNickModal');
        loadPlayers();
    } catch (e) { toast('Failed: ' + e.message, 'error'); }
}

function openPassModal(userId) {
    playerActionId = userId;
    document.getElementById('passInput').value = '';
    openModal('passModal');
}

async function confirmPassChange() {
    if (!playerActionId) return;
    var pass = document.getElementById('passInput').value;
    if (!pass) { toast('Password is required', 'error'); return; }
    if (pass.length < 8) { toast('Min 8 characters', 'error'); return; }
    try {
        var r = await apiFetch('/admin/users/' + playerActionId + '/password', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ password: pass })
        });
        if (!r) return;
        var d = await r.json();
        if (d.error) { toast(d.error, 'error'); return; }
        toast('Password changed', 'success');
        closeModal('passModal');
    } catch (e) { toast('Failed: ' + e.message, 'error'); }
}

async function loadBanServerOptions() {
    if (banServerOptions.length) return;
    try {
        var r = await apiFetch('/admin/instances');
        if (!r) return;
        var servers = await r.json();
        banServerOptions = servers.map(function (s) { return { id: s.id, name: s.name || s.id }; });
    } catch (e) {}
}

function onBanAllChange() {
    var checked = document.getElementById('banAllCheck').checked;
    var inputs = document.querySelectorAll('#banServersList input[type=checkbox]');
    for (var i = 0; i < inputs.length; i++) {
        inputs[i].disabled = checked;
        if (checked) inputs[i].checked = false;
    }
}

async function openBanModal(userId, nick) {
    playerActionId = userId;
    document.getElementById('banModalTitle').textContent = 'Ban Player: ' + (nick || userId);
    document.getElementById('banReasonInput').value = '';
    document.getElementById('banDurationSelect').value = '0';
    document.getElementById('banCustomDuration').style.display = 'none';
    document.getElementById('banAllCheck').checked = false;
    var list = document.getElementById('banServersList');
    list.innerHTML = '';
    await loadBanServerOptions();
    for (var i = 0; i < banServerOptions.length; i++) {
        var s = banServerOptions[i];
        var label = document.createElement('label');
        label.className = 'ban-srv-item';
        var cb = document.createElement('input');
        cb.type = 'checkbox';
        cb.value = s.id;
        label.appendChild(cb);
        label.appendChild(document.createTextNode(' ' + s.name + ' (' + s.id + ')'));
        list.appendChild(label);
    }
    onBanAllChange();
    openModal('banModal');
}

function getSelectedBanServers() {
    if (document.getElementById('banAllCheck').checked) return null;
    var ids = [];
    var inputs = document.querySelectorAll('#banServersList input[type=checkbox]:checked');
    for (var i = 0; i < inputs.length; i++) ids.push(inputs[i].value);
    return ids;
}

function onBanDurationChange() {
    document.getElementById('banCustomDuration').style.display =
        document.getElementById('banDurationSelect').value === '__custom' ? 'block' : 'none';
}

function getBanDurationSeconds() {
    var preset = document.getElementById('banDurationSelect').value;
    if (preset === '__custom') {
        var val = parseInt(document.getElementById('banDurationValue').value, 10) || 0;
        var unit = parseInt(document.getElementById('banDurationUnit').value, 10) || 3600;
        return val * unit;
    }
    return parseInt(preset, 10) || 0;
}

async function confirmBan() {
    if (!playerActionId) return;
    var serverIds = getSelectedBanServers();
    if (serverIds !== null && !serverIds.length) {
        toast('Select at least one server or "All servers"', 'error');
        return;
    }
    var body = {
        instance_ids: serverIds || [],
        duration: getBanDurationSeconds(),
        reason: document.getElementById('banReasonInput').value.trim()
    };
    try {
        var r = await apiFetch('/admin/users/' + playerActionId + '/ban', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });
        if (!r) return;
        var d = await r.json();
        if (d.error) { toast(d.error, 'error'); return; }
        toast('Player banned', 'success');
        closeModal('banModal');
        loadPlayers();
    } catch (e) { toast('Failed: ' + e.message, 'error'); }
}

async function unbanPlayer(userId, banId) {
    var body = {};
    if (banId) { body.ban_id = banId; }
    try {
        var r = await apiFetch('/admin/users/' + userId + '/unban', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });
        if (!r) return;
        var d = await r.json();
        if (d.error) { toast(d.error, 'error'); return; }
        toast('Unbanned', 'success');
        loadPlayers();
    } catch (e) { toast('Failed: ' + e.message, 'error'); }
}

async function deletePlayer(userId, nick) {
    if (!confirm('Delete account "' + (nick || userId) + '" permanently?')) return;
    try {
        var r = await apiFetch('/admin/users/' + userId, { method: 'DELETE' });
        if (!r) return;
        var d = await r.json();
        if (d.error) { toast(d.error, 'error'); return; }
        toast('Account deleted', 'success');
        loadPlayers();
    } catch (e) { toast('Failed: ' + e.message, 'error'); }
}
