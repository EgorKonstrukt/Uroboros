/* ===================== Server Overview ===================== */

var overviewTimer = null;
var overviewSamplesById = {};
var overviewLastDataById = {};
var overviewAnimated = false;
var OVERVIEW_MAX_SAMPLES = 60;
var overviewRefreshMs = 2000;

function startOverview() {
    if (overviewTimer) clearInterval(overviewTimer);
    overviewTimer = setInterval(function () { refreshOverview(false); }, overviewRefreshMs);
    refreshOverview(false);
}

function stopOverview() {
    if (overviewTimer) { clearInterval(overviewTimer); overviewTimer = null; }
}

async function refreshOverview(manual) {
    if (!currentServerId) { stopOverview(); return; }
    if (manual) {
        document.getElementById('ovLastUpdate').textContent = 'Refreshing...';
    }
    var id = currentServerId;
    try {
        var r = await apiFetch('/admin/instances/' + id + '/overview');
        if (!r) { if (manual) document.getElementById('ovLastUpdate').textContent = 'Failed to load'; return; }
        var d = await r.json();
        if (d.error) {
            if (manual) document.getElementById('ovLastUpdate').textContent = d.error;
            return;
        }
        overviewLastDataById[id] = d;
        renderOverview(d);
        pushSample(id, d);
        renderCharts();
        if (typeof refreshServerStatus === 'function') refreshServerStatus();
        if (d.refresh_interval && d.refresh_interval * 1000 !== overviewRefreshMs && overviewTimer) {
            overviewRefreshMs = d.refresh_interval * 1000;
            clearInterval(overviewTimer);
            overviewTimer = setInterval(function () { refreshOverview(false); }, overviewRefreshMs);
        }
    } catch (e) {
        if (manual) document.getElementById('ovLastUpdate').textContent = 'Failed: ' + e.message;
    }
}

function pushSample(id, d) {
    var arr = overviewSamplesById[id] || (overviewSamplesById[id] = []);
    arr.push({
        t: Date.now(),
        mem: d.process ? d.process.memory_rss_mb : 0,
        cpu: d.process ? d.process.cpu_percent : 0,
        players: d.players ? d.players.online : 0,
        playersMax: d.players ? d.players.max : null,
    });
    if (arr.length > OVERVIEW_MAX_SAMPLES) {
        overviewSamplesById[id] = arr.slice(-OVERVIEW_MAX_SAMPLES);
    }
}

function fmtUptime(sec) {
    if (sec == null) return '-';
    var h = Math.floor(sec / 3600);
    var m = Math.floor((sec % 3600) / 60);
    var s = sec % 60;
    if (h > 0) return h + 'h ' + m + 'm';
    if (m > 0) return m + 'm ' + s + 's';
    return s + 's';
}

function fmtDate(ts) {
    if (!ts) return '-';
    return new Date(ts * 1000).toLocaleString();
}

function renderOverview(d) {
    document.getElementById('ovLastUpdate').textContent =
        'Updated ' + new Date().toLocaleTimeString() + (d.running ? ' · running' : ' · stopped') + ' · every ' + (d.refresh_interval || 2) + 's';
    var live = document.getElementById('ovLiveDot');
    live.classList.toggle('off', !d.running);
    live.textContent = d.running ? 'Live' : 'Offline';

    var p = d.process;
    var sys = d.system;
    var players = d.players;

    var tiles = [];
    tiles.push({ label: 'Status', value: d.running ? 'RUNNING' : 'STOPPED', cls: d.running ? 'running' : 'stopped', sub: d.running ? 'process active' : (d.last_error || 'no process') });
    tiles.push({ label: 'PID', value: p ? p.pid : '—', sub: p ? p.status : 'n/a' });
    tiles.push({ label: 'Uptime', value: p ? fmtUptime(p.uptime_seconds) : '—', sub: p ? 'since ' + fmtDate(p.create_time) : '' });
    tiles.push({ label: 'Players', value: players ? players.online + '/' + players.max : '—', sub: players ? 'online / max' : 'no data' });
    tiles.push({ label: 'CPU', value: p ? p.cpu_percent + '%' : '—', sub: p ? p.cpu_time_user + 's user' : '' });
    tiles.push({ label: 'Memory', value: p ? p.memory_rss_mb + ' MB' : '—', sub: p ? p.memory_percent + '% of system' : '' });
    tiles.push({ label: 'Threads', value: p ? p.num_threads : '—', sub: p && p.connections != null ? p.connections + ' conns' : '' });
    tiles.push({ label: 'Log buffer', value: d.log_lines, sub: 'lines held' });

    var html = '';
    for (var i = 0; i < tiles.length; i++) {
        var t = tiles[i];
        html += '<div class="ov-tile">' +
            '<div class="ov-tile-label">' + esc(t.label) + '</div>' +
            '<div class="ov-tile-value ' + (t.cls || '') + '">' + esc(String(t.value)) + '</div>' +
            '<div class="ov-tile-sub">' + esc(t.sub) + '</div>' +
            '</div>';
    }
    document.getElementById('overviewTiles').innerHTML = html;

    var details = '';

    details += detailCard('Process', [
        p ? ['Status', p.status] : ['Status', 'stopped'],
        p ? ['Uptime', fmtUptime(p.uptime_seconds)] : ['Uptime', '—'],
        p ? ['Started', fmtDate(p.create_time)] : ['Started', '—'],
        p ? ['CPU time', p.cpu_time_user + 's user / ' + p.cpu_time_system + 's sys'] : ['CPU time', '—'],
        p ? ['Threads', p.num_threads] : ['Threads', '—'],
        p ? ['Open files', (p.open_files == null ? 'n/a' : p.open_files)] : ['Open files', '—'],
        p ? ['Connections', (p.connections == null ? 'n/a' : p.connections)] : ['Connections', '—'],
        p ? ['User', p.username] : ['User', '—'],
        p ? ['Executable', p.executable] : ['Executable', '—'],
        p ? ['Working dir', p.cwd] : ['Working dir', '—'],
    ]);

    details += detailCard('System', [
        sys.hostname != null ? ['Hostname', sys.hostname] : ['Hostname', '—'],
        sys.platform ? ['Platform', sys.platform] : ['Platform', '—'],
        sys.kernel ? ['Kernel', sys.kernel] : ['Kernel', '—'],
        sys.boot_time ? ['Boot time', fmtDate(sys.boot_time)] : ['Boot time', '—'],
        sys.cpu_count != null ? ['CPU', sys.cpu_physical + ' physical / ' + sys.cpu_count + ' logical'] : ['CPU', '—'],
        sys.cpu_percent != null ? ['CPU load', sys.cpu_percent + '%'] : ['CPU load', '—'],
        sys.memory_total_mb != null ? ['Memory', sys.memory_used_mb + ' / ' + sys.memory_total_mb + ' MB (' + sys.memory_percent + '%)'] : ['Memory', '—'],
        sys.disk_total_gb != null ? ['Disk', sys.disk_used_gb + ' / ' + sys.disk_total_gb + ' GB'] : ['Disk', '—'],
    ]);

    details += detailCard('Configuration', [
        ['ID', d.config.id],
        ['Name', d.config.name],
        ['Server dir', d.config.server_dir],
        ['JAR', d.config.server_filename],
        ['Java', d.config.java_executable_path],
        ['Heap', d.config.min_memory + 'M – ' + d.config.max_memory + 'M'],
        ['Arguments', d.config.arguments || '(none)'],
        ['Additional flags', d.config.additional_flags || '(none)'],
        ['Version', d.config.version || '(default)'],
        ['Modpack', d.config.modpack_id || '(none)'],
        ['API URL', d.config.api_url || '(none)'],
        ['Auth plugin', d.config.auth_plugin || '(none)'],
        ['Injector', d.config.injector_filename || '(none)'],
        ['Auto-restart', d.config.auto_restart ? 'enabled' : 'disabled'],
        ['Whitelist', d.config.whitelist_enabled ? 'enabled' : 'disabled'],
    ]);

    document.getElementById('overviewDetails').innerHTML = details;

    if (!overviewAnimated) {
        overviewAnimated = true;
        var ovTiles = document.querySelectorAll('#overviewTiles .ov-tile');
        for (var oi = 0; oi < ovTiles.length; oi++) {
            ovTiles[oi].style.animation = 'fadeInUp .35s ease backwards';
            ovTiles[oi].style.animationDelay = (oi * 0.04) + 's';
        }
        var ovCards = document.querySelectorAll('#overviewDetails .ov-detail-card');
        for (var ci = 0; ci < ovCards.length; ci++) {
            ovCards[ci].style.animation = 'fadeInUp .35s ease backwards';
            ovCards[ci].style.animationDelay = (ci * 0.06) + 's';
        }
    }

    var memSub = document.getElementById('ovMemSub');
    var cpuSub = document.getElementById('ovCpuSub');
    var plSub = document.getElementById('ovPlayersSub');
    memSub.textContent = p ? 'RSS ' + p.memory_rss_mb + ' MB · VMS ' + p.memory_vms_mb + ' MB' : 'no process';
    cpuSub.textContent = p ? 'process ' + p.cpu_percent + '%' : 'no process';
    plSub.textContent = players ? players.online + ' of ' + players.max + ' slots' : 'no data';
}

function detailCard(title, rows) {
    var html = '<div class="md-card ov-detail-card"><div class="md-card-title">' + esc(title) + '</div><dl class="ov-dl">';
    for (var i = 0; i < rows.length; i++) {
        html += '<dt>' + esc(rows[i][0]) + '</dt><dd>' + esc(String(rows[i][1])) + '</dd>';
    }
    html += '</dl></div>';
    return html;
}

function cssVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || '';
}

function renderCharts() {
    var id = currentServerId;
    var samples = overviewSamplesById[id] || [];
    var last = overviewLastDataById[id] || null;
    var memData = samples.map(function (s) { return s.mem; });
    var cpuData = samples.map(function (s) { return s.cpu; });
    var plData = samples.map(function (s) { return s.players; });
    drawSvgChart(document.getElementById('ovMemChart'), memData, {
        height: 170, color: cssVar('--primary'), label: 'MB',
        fixedMax: last && last.process ? Math.max(last.process.memory_rss_mb * 1.2, last.config.max_memory) : null,
    });
    drawSvgChart(document.getElementById('ovCpuChart'), cpuData, {
        height: 170, color: cssVar('--secondary'), label: '%', fixedMax: 100,
    });
    var plMax = last && last.players ? last.players.max : null;
    drawSvgChart(document.getElementById('ovPlayersChart'), plData, {
        height: 120, color: cssVar('--success'), label: 'players',
        fixedMax: plMax && plMax > 0 ? Math.max(plMax, 5) : null,
    });
}

function drawSvgChart(svgEl, values, opts) {
    if (!svgEl) return;
    var W = 600;
    var H = opts.height || 170;
    var pad = 8;
    var axisColor = cssVar('--text-hint');
    var gridColor = cssVar('--divider') || 'rgba(0,0,0,.12)';
    if (!values || values.length < 2) {
        svgEl.innerHTML = '<text x="' + (W / 2) + '" y="' + (H / 2) + '" text-anchor="middle" fill="' + axisColor + '" font-size="13" font-family="Roboto">Collecting data...</text>';
        return;
    }
    var minV = 0;
    var maxV = opts.fixedMax || (Math.max.apply(null, values) * 1.15);
    if (!(maxV > minV)) maxV = minV + 1;
    var n = values.length;
    var x0 = pad, x1 = W - pad, y0 = pad, y1 = H - pad;
    var step = (x1 - x0) / (n - 1);
    function px(i) { return x0 + i * step; }
    function py(v) { return y1 - ((v - minV) / (maxV - minV)) * (y1 - y0); }
    var poly = [];
    for (var i = 0; i < n; i++) {
        poly.push(px(i).toFixed(1) + ',' + py(values[i]).toFixed(1));
    }
    var area = x0 + ',' + y1 + ' ' + poly.join(' ') + ' ' + px(n - 1).toFixed(1) + ',' + y1;
    var grid = '';
    for (var g = 1; g <= 4; g++) {
        var gy = y0 + (y1 - y0) * (g / 4);
        grid += '<line x1="' + x0 + '" y1="' + gy.toFixed(1) + '" x2="' + x1 + '" y2="' + gy.toFixed(1) + '" stroke="' + gridColor + '" stroke-width="1"/>';
    }
    svgEl.innerHTML =
        grid +
        '<polygon points="' + area + '" fill="' + opts.color + '" opacity="0.12"/>' +
        '<polyline points="' + poly.join(' ') + '" fill="none" stroke="' + opts.color + '" stroke-width="2" stroke-linejoin="round"/>' +
        '<text x="' + x0 + '" y="' + (y0 + 12) + '" fill="' + axisColor + '" font-size="10" font-family="Roboto">' + opts.label + '</text>';
}

if (window.__themeListeners) {
    window.__themeListeners.push(function () {
        if (currentServerId && overviewLastDataById[currentServerId]) renderCharts();
    });
}
