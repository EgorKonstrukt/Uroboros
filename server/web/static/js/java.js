/* ===================== Java runtimes ===================== */

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
