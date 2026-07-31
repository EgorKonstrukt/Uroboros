/* ===================== Global config ===================== */

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
