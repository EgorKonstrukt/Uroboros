/* ===================== Advanced file manager ===================== */

function FileManager(cfg) {
    this.cfg = cfg;
    this.mv = cfg.managerVar || 'fm';
    this.path = '';
    this.absolute = '';
    this.items = [];
    this.selected = {};
    this.filter = '';
    this.sortKey = 'name';
    this.sortDir = 1;
    this.queue = [];
    this.uploading = false;
    this.editing = null;
    this.lastIndex = -1;
    this._clickTimer = null;
    this.init();
}

FileManager.prototype.init = function () {
    var self = this;
    var el = document.getElementById(this.cfg.ids.browser);
    if (!el) return;
    el.addEventListener('dragover', function (e) {
        e.preventDefault();
        e.stopPropagation();
        el.classList.add('fm-dragover');
    });
    el.addEventListener('dragleave', function (e) {
        e.preventDefault();
        el.classList.remove('fm-dragover');
    });
    el.addEventListener('drop', function (e) {
        e.preventDefault();
        e.stopPropagation();
        el.classList.remove('fm-dragover');
        self.handleDrop(e.dataTransfer ? e.dataTransfer.items : null);
    });
};

FileManager.prototype.j = function (method, args) {
    return this.mv + '.' + method + '(' + (args || '') + ')';
};

FileManager.prototype.setBusy = function (b) {
    document.getElementById(this.cfg.ids.browser).innerHTML = b ? '<div class="fm-status">Loading...</div>' : '';
};

FileManager.prototype.load = function (path) {
    var self = this;
    this.setBusy(true);
    this.path = path || '';
    this.selected = {};
    this.editing = null;
    apiFetch(this.cfg.listUrl(this.path)).then(function (r) {
        if (!r) return;
        r.json().then(function (d) {
            self.setBusy(false);
            if (d.error) {
                document.getElementById(self.cfg.ids.browser).innerHTML = '<div class="error-msg">' + esc(d.error) + '</div>';
                self.renderBreadcrumb();
                return;
            }
            self.absolute = d.absolute || '';
            self.items = d.items || [];
            self.filter = '';
            var si = document.getElementById(self.cfg.ids.searchInput);
            if (si) si.value = '';
            self.render();
        });
    }).catch(function (e) {
        self.setBusy(false);
        document.getElementById(self.cfg.ids.browser).innerHTML = '<div class="error-msg">Failed: ' + esc(e.message) + '</div>';
    });
};

FileManager.prototype.refresh = function () { this.load(this.path); };

FileManager.prototype.navigateTo = function (path) { this.load(path); };

FileManager.prototype.navigateUp = function () {
    if (!this.path) return;
    var parent = this.path.replace(/\/?[^/]+$/, '');
    this.load(parent);
};

FileManager.prototype.render = function () {
    this.renderBreadcrumb();
    this.renderSelectionBar();
    this.renderTable();
};

FileManager.prototype.renderBreadcrumb = function () {
    var el = document.getElementById(this.cfg.ids.breadcrumb);
    var dirEl = document.getElementById(this.cfg.ids.dir);
    if (dirEl) dirEl.textContent = this.absolute || '/';
    var segs = this.path ? this.path.split('/') : [];
    var html = '<button class="fm-crumb" title="/" onclick="' + this.j('navigateTo', "''") + '">/</button>';
    var acc = '';
    for (var i = 0; i < segs.length; i++) {
        acc = acc ? acc + '/' + segs[i] : segs[i];
        html += '<span class="fm-crumb-sep">/</span><button class="fm-crumb" onclick="' + this.j('navigateTo', "'" + escAttr(acc) + "'") + '">' + esc(segs[i]) + '</button>';
    }
    el.innerHTML = html;
};

FileManager.prototype.selectedCount = function () {
    return Object.keys(this.selected).filter(function (k) { return this.selected[k]; }, this).length;
};

FileManager.prototype.selectedPaths = function () {
    var out = [];
    for (var i = 0; i < this.items.length; i++) {
        var name = this.items[i].name;
        if (this.selected[name]) out.push(this.path ? this.path + '/' + name : name);
    }
    return out;
};

FileManager.prototype.renderSelectionBar = function () {
    var el = document.getElementById(this.cfg.ids.selbar);
    var n = this.selectedCount();
    if (!n) {
        el.style.display = 'none';
        el.innerHTML = '';
        return;
    }
    el.style.display = 'flex';
    el.innerHTML = '<span class="fm-sel-count">' + n + ' selected</span>' +
        '<button class="btn btn-sm btn-secondary" onclick="' + this.j('selectAll') + '">All</button>' +
        '<button class="btn btn-sm btn-secondary" onclick="' + this.j('invertSelect') + '">Invert</button>' +
        '<button class="btn btn-sm btn-secondary" onclick="' + this.j('clearSelect') + '">Clear</button>' +
        '<span class="fm-sel-sep"></span>' +
        '<button class="btn btn-sm btn-stop" onclick="' + this.j('deleteSelection') + '">Delete</button>' +
        '<button class="btn btn-sm btn-start" onclick="' + this.j('downloadSelection') + '">Download ZIP</button>' +
        '<button class="btn btn-sm btn-secondary" onclick="' + this.j('moveSelection') + '">Move to...</button>' +
        '<button class="btn btn-sm btn-secondary" onclick="' + this.j('copySelection') + '">Copy to...</button>' +
        (n === 1 ? '<button class="btn btn-sm btn-secondary" onclick="' + this.j('renameSelection') + '">Rename</button>' : '');
};

FileManager.prototype.visibleItems = function () {
    var items = this.items.slice();
    if (this.filter) {
        var f = this.filter.toLowerCase();
        items = items.filter(function (it) { return it.name.toLowerCase().indexOf(f) !== -1; });
    }
    var key = this.sortKey;
    var dir = this.sortDir;
    items.sort(function (a, b) {
        if (a.is_dir !== b.is_dir) return a.is_dir ? -1 : 1;
        var av = a[key];
        var bv = b[key];
        if (key === 'size' || key === 'modified') {
            if (av === bv) return 0;
            return (av - bv) * dir;
        }
        return String(av).localeCompare(String(bv)) * dir;
    });
    return items;
};

FileManager.prototype.sortArrow = function (key) {
    if (this.sortKey !== key) return '';
    return this.sortDir === 1 ? ' ▲' : ' ▼';
};

FileManager.prototype.setSort = function (key) {
    if (this.sortKey === key) this.sortDir *= -1;
    else { this.sortKey = key; this.sortDir = 1; }
    this.renderTable();
};

FileManager.prototype.extTag = function (name) {
    var m = /\.([a-zA-Z0-9]+)$/.exec(name);
    if (!m) return 'FILE';
    var ext = m[1].toUpperCase();
    if (ext.length > 6) ext = ext.slice(0, 6);
    return ext;
};

FileManager.prototype.renderTable = function () {
    var container = document.getElementById(this.cfg.ids.browser);
    var items = this.visibleItems();
    if (!items.length) {
        container.innerHTML = '<div class="fm-status">Empty directory</div>';
        return;
    }
    var allId = this.cfg.ids.browser + '_all';
    var html = '<table><thead><tr>' +
        '<th class="fm-col-check"><input type="checkbox" id="' + allId + '" onchange="' + this.j('toggleAll', 'this.checked') + '"></th>' +
        '<th class="fm-col-name" onclick="' + this.j('setSort', "'name'") + '">Name' + this.sortArrow('name') + '</th>' +
        '<th onclick="' + this.j('setSort', "'size'") + '">Size' + this.sortArrow('size') + '</th>' +
        '<th onclick="' + this.j('setSort', "'modified'") + '">Modified' + this.sortArrow('modified') + '</th>' +
        '<th class="fm-col-actions">Actions</th></tr></thead><tbody>';
    if (this.path) {
        html += '<tr class="fm-row fm-row-parent" onclick="' + this.j('navigateUp') + '" title="Go to parent directory">' +
            '<td class="fm-col-check"></td>' +
            '<td class="fm-col-name"><span class="fm-item-name"><span class="tag tag-dir">DIR</span> ..</span></td>' +
            '<td>-</td><td>-</td><td class="fm-col-actions"></td></tr>';
    }
    for (var i = 0; i < items.length; i++) {
        html += this.rowHtml(items[i], i);
    }
    html += '</tbody></table>';
    container.innerHTML = html;
    var all = document.getElementById(allId);
    if (all) all.checked = items.length > 0 && this.selectedCount() === items.length;
};

FileManager.prototype.rowHtml = function (item, index) {
    var name = item.name;
    var full = this.path ? this.path + '/' + name : name;
    var isDir = item.is_dir;
    var checked = this.selected[name] ? 'checked' : '';
    var cls = this.selected[name] ? ' fm-row-selected' : '';
    var label = isDir ? '<span class="tag tag-dir">DIR</span>' : '<span class="tag tag-file">' + this.extTag(name) + '</span>';
    var sizeStr = isDir ? '-' : formatSize(item.size);
    var dateStr = new Date(item.modified * 1000).toLocaleString();
    var rowClick = isDir ? this.j('navigateTo', "'" + escAttr(full) + "'") : this.j('onRowClick', 'this, ' + index + ', event');
    var dblJs = isDir ? '' : this.j('onRowDblClick', index);
    var actions = '';
    actions += '<button class="btn btn-sm btn-secondary" onclick="event.stopPropagation();' + this.j('downloadItem', "'" + escAttr(full) + "'") + '">Download</button>';
    if (!isDir) actions += '<button class="btn btn-sm btn-secondary" onclick="event.stopPropagation();' + this.j('openEditor', "'" + escAttr(full) + "'") + '">Edit</button>';
    actions += '<button class="btn btn-sm btn-secondary" onclick="event.stopPropagation();' + this.j('renameItem', "'" + escAttr(full) + "'") + '">Rename</button>';
    actions += '<button class="btn btn-sm btn-stop" onclick="event.stopPropagation();' + this.j('deleteItem', "'" + escAttr(full) + "'") + '">Delete</button>';
    return '<tr class="fm-row' + cls + '" ondblclick="' + (dblJs ? 'event.stopPropagation();' + dblJs : '') + '" onclick="' + rowClick + '">' +
        '<td class="fm-col-check" onclick="event.stopPropagation()"><input type="checkbox" ' + checked + ' onchange="' + this.j('onCheckbox', "'" + escAttr(name) + "', this.checked, " + index) + '"></td>' +
        '<td class="fm-col-name"><span class="fm-item-name">' + label + ' ' + esc(name) + '</span></td>' +
        '<td>' + sizeStr + '</td><td>' + dateStr + '</td>' +
        '<td class="fm-col-actions">' + actions + '</td></tr>';
};

FileManager.prototype.onRowClick = function (tr, index, ev) {
    var self = this;
    if (this._clickTimer) { clearTimeout(this._clickTimer); this._clickTimer = null; }
    this._clickTimer = setTimeout(function () {
        var items = self.visibleItems();
        if (index < 0 || index >= items.length) return;
        self.toggleSelect(items[index].name, index, ev || {});
    }, 220);
};

FileManager.prototype.onRowDblClick = function (index) {
    if (this._clickTimer) { clearTimeout(this._clickTimer); this._clickTimer = null; }
    var items = this.visibleItems();
    if (index < 0 || index >= items.length) return;
    var item = items[index];
    var full = this.path ? this.path + '/' + item.name : item.name;
    if (item.is_dir) this.navigateTo(full);
    else this.openEditor(full);
};

FileManager.prototype.toggleSelect = function (name, index, ev) {
    if (ev.shiftKey && this.lastIndex >= 0 && this.lastIndex !== index) {
        var items = this.visibleItems();
        var a = Math.min(this.lastIndex, index);
        var b = Math.max(this.lastIndex, index);
        for (var i = a; i <= b; i++) this.selected[items[i].name] = true;
    } else {
        if (this.selected[name]) delete this.selected[name];
        else this.selected[name] = true;
    }
    this.lastIndex = index;
    this.render();
};

FileManager.prototype.onCheckbox = function (name, checked, index) {
    if (this._clickTimer) { clearTimeout(this._clickTimer); this._clickTimer = null; }
    if (checked) this.selected[name] = true;
    else delete this.selected[name];
    this.lastIndex = index;
    this.render();
};

FileManager.prototype.selectAll = function () {
    var items = this.visibleItems();
    for (var i = 0; i < items.length; i++) this.selected[items[i].name] = true;
    this.render();
};

FileManager.prototype.toggleAll = function (checked) {
    var items = this.visibleItems();
    for (var i = 0; i < items.length; i++) {
        if (checked) this.selected[items[i].name] = true;
        else delete this.selected[items[i].name];
    }
    this.render();
};

FileManager.prototype.invertSelect = function () {
    var items = this.visibleItems();
    for (var i = 0; i < items.length; i++) {
        var n = items[i].name;
        if (this.selected[n]) delete this.selected[n];
        else this.selected[n] = true;
    }
    this.render();
};

FileManager.prototype.clearSelect = function () {
    this.selected = {};
    this.render();
};

FileManager.prototype.filterChanged = function () {
    this.filter = document.getElementById(this.cfg.ids.searchInput).value.trim();
    this.renderTable();
};

FileManager.prototype.downloadItem = function (path) {
    var fallback = path ? path.split('/').pop() : 'files';
    downloadBlob(this.cfg.downloadUrl(path), fallback);
};

FileManager.prototype.downloadCurrent = function () {
    var fallback = this.path ? this.path.split('/').pop() : 'files';
    downloadBlob(this.cfg.downloadUrl(this.path), fallback);
};

FileManager.prototype.downloadSelection = function () {
    var paths = this.selectedPaths();
    if (!paths.length) return;
    var self = this;
    apiFetch(this.cfg.actionUrl('zip'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ paths: paths })
    }).then(function (r) {
        if (!r) return;
        if (!r.ok) {
            r.json().then(function (d) { toast(d.error || 'Zip failed', 'error'); }).catch(function () {});
            return;
        }
        r.blob().then(function (b) {
            var a = document.createElement('a');
            a.href = URL.createObjectURL(b);
            a.download = 'selection.zip';
            document.body.appendChild(a);
            a.click();
            setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
        });
    }).catch(function (e) { toast('Failed: ' + e.message, 'error'); });
};

FileManager.prototype.batchAction = function (action, paths, verb, extra) {
    var self = this;
    var method = ({ delete: 'DELETE', move: 'POST', copy: 'POST', rename: 'POST', mkdir: 'POST' })[action] || 'POST';
    var url = action === 'delete' && this.cfg.deleteUrl ? this.cfg.deleteUrl() : this.cfg.actionUrl(action);
    var body = { paths: paths };
    if (extra) for (var k in extra) body[k] = extra[k];
    apiFetch(url, {
        method: method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
    }).then(function (r) {
        if (!r) return;
        r.json().then(function (d) {
            if (d.error) { toast(d.error, 'error'); return; }
            var ok = d.count != null ? d.count : (d.deleted != null ? d.deleted : paths.length);
            if (d.errors && d.errors.length) {
                var reasons = {};
                d.errors.forEach(function (e) {
                    var msg = e.error || 'unknown error';
                    reasons[msg] = (reasons[msg] || 0) + 1;
                });
                var detail = Object.keys(reasons).map(function (k) { return k + ' (x' + reasons[k] + ')'; }).join('; ');
                toast(ok + ' ' + verb + ', ' + d.errors.length + ' failed: ' + detail, 'error', 8000);
            }
            else toast(ok + ' item(s) ' + verb, 'success');
            self.load(self.path);
        }).catch(function () { toast(action + ' failed', 'error'); });
    }).catch(function (e) { toast('Failed: ' + e.message, 'error'); });
};

FileManager.prototype.deleteItem = function (path) {
    if (!confirm('Delete "' + path + '"?')) return;
    this.batchAction('delete', [path], 'deleted');
};

FileManager.prototype.deleteSelection = function () {
    var paths = this.selectedPaths();
    if (!paths.length) return;
    if (!confirm('Delete ' + paths.length + ' selected item(s)?\n' + paths.join('\n'))) return;
    this.batchAction('delete', paths, 'deleted');
};

FileManager.prototype.renameItem = function (path) {
    var self = this;
    var name = path.split('/').pop();
    fmPromptOpen('Rename', 'New name for "' + name + '"', name, function (val) {
        var nv = (val || '').trim();
        if (!nv || nv === name) return;
        self.batchAction('rename', [path], 'renamed', { new_name: nv });
    });
};

FileManager.prototype.renameSelection = function () {
    var paths = this.selectedPaths();
    if (paths.length === 1) this.renameItem(paths[0]);
};

FileManager.prototype.moveSelection = function () { this.moveOrCopy('move'); };
FileManager.prototype.copySelection = function () { this.moveOrCopy('copy'); };

FileManager.prototype.moveOrCopy = function (action) {
    var paths = this.selectedPaths();
    if (!paths.length) return;
    var self = this;
    fmPromptOpen(action === 'move' ? 'Move to' : 'Copy to', 'Destination folder (relative to current root)', '', function (val) {
        var dest = (val || '').trim();
        if (!dest) return;
        self.batchAction(action, paths, action === 'move' ? 'moved' : 'copied', { destination: dest });
    });
};

FileManager.prototype.mkdirPrompt = function () {
    var self = this;
    fmPromptOpen('New Folder', 'Folder name', '', function (val) {
        var name = (val || '').trim();
        if (!name) return;
        self.batchAction('mkdir', [], 'created', { path: self.path, name: name });
    });
};

FileManager.prototype.openEditor = function (filePath) {
    var self = this;
    apiFetch(this.cfg.readUrl(filePath)).then(function (r) {
        if (!r) return;
        r.json().then(function (d) {
            if (d.error) { toast(d.error, 'error'); return; }
            if (!d.is_text) { toast('Binary files cannot be edited', 'error'); return; }
            self.editing = filePath;
            var container = document.getElementById(self.cfg.ids.browser);
            container.innerHTML = '<div class="md-card"><div class="row"><strong>Editing:</strong> <span style="font-family:monospace;color:#1976d2;flex:1">' + esc(d.path) + '</span>' +
                '<button class="btn btn-start btn-sm" onclick="' + self.j('saveEditor') + '">Save</button>' +
                '<button class="btn btn-secondary btn-sm" onclick="' + self.j('closeEditor') + '">Close</button></div>' +
                '<textarea id="' + self.cfg.editorTextId + '" style="width:100%;height:400px;font:13px/1.6 monospace;padding:12px;border:2px solid #bdbdbd;border-radius:4px;resize:vertical;margin-top:12px" spellcheck="false">' + esc(d.content) + '</textarea></div>';
        });
    }).catch(function (e) { toast('Failed: ' + e.message, 'error'); });
};

FileManager.prototype.saveEditor = function () {
    if (!this.editing) return;
    var content = document.getElementById(this.cfg.editorTextId).value;
    var self = this;
    apiFetch(this.cfg.writeUrl(), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: this.editing, content: content })
    }).then(function (r) {
        if (!r) return;
        r.json().then(function (d) {
            if (d.error) { toast(d.error, 'error'); return; }
            toast('File saved', 'success');
        });
    }).catch(function (e) { toast('Failed: ' + e.message, 'error'); });
};

FileManager.prototype.closeEditor = function () {
    this.editing = null;
    this.load(this.path);
};

FileManager.prototype.uploadEntries = async function (entries) {
    var self = this;
    var done = 0;
    var errs = [];
    for (var start = 0; start < entries.length; start += 100) {
        var chunk = entries.slice(start, start + 100);
        var fd = new FormData();
        if (this.path) fd.append('path', this.path);
        for (var j = 0; j < chunk.length; j++) {
            fd.append('file', chunk[j].file, chunk[j].file.name);
            fd.append('relpath', chunk[j].rel);
        }
        try {
            var r = await apiFetch(this.cfg.uploadBatchUrl(), { method: 'POST', body: fd });
            if (!r) return;
            var d = await r.json();
            done += d.uploaded || 0;
            if (d.errors) errs = errs.concat(d.errors);
        } catch (e) {
            errs.push({ error: e.message });
        }
    }
    self.showUploadResult(done, errs);
    this.load(this.path);
};

FileManager.prototype.showUploadResult = function (done, errs) {
    if (errs.length) {
        var reasons = {};
        errs.forEach(function (e) {
            var msg = e.error || 'unknown error';
            reasons[msg] = (reasons[msg] || 0) + 1;
        });
        var detail = Object.keys(reasons).map(function (k) { return k + ' (x' + reasons[k] + ')'; }).join('; ');
        toast('Uploaded: ' + done + ', failed: ' + errs.length + ': ' + detail, 'error', 8000);
    } else if (done) toast('Uploaded: ' + done + ' file(s)', 'success');
};

FileManager.prototype.onFilesPicked = function (input) {
    var files = Array.prototype.slice.call(input.files || []);
    input.value = '';
    if (!files.length) return;
    var entries = files.map(function (f) { return { file: f, rel: f.name }; });
    this.uploadEntries(entries);
};

FileManager.prototype.onDirPicked = function (input) {
    var files = Array.prototype.slice.call(input.files || []);
    input.value = '';
    if (!files.length) return;
    var byRoot = {};
    files.forEach(function (f) {
        var rel = (f.webkitRelativePath || f.name).replace(/\\/g, '/');
        var root = rel.split('/')[0];
        if (!byRoot[root]) byRoot[root] = [];
        byRoot[root].push({ file: f, rel: rel });
    });
    var self = this;
    var roots = Object.keys(byRoot);
    roots.forEach(function (root) {
        self.queue.push({ root: root, entries: byRoot[root] });
    });
    this.renderQueue();
    toast('Added ' + roots.length + ' folder(s) to upload queue (' + files.length + ' files)', 'info');
};

FileManager.prototype.renderQueue = function () {
    var el = document.getElementById(this.cfg.ids.queue);
    if (!this.queue.length) {
        el.style.display = 'none';
        el.innerHTML = '';
        return;
    }
    el.style.display = 'block';
    var self = this;
    var total = 0;
    this.queue.forEach(function (q) { total += q.entries.length; });
    var html = '<div class="fm-queue-head"><strong>Upload queue</strong> <span class="fm-queue-total">' + this.queue.length + ' folder(s) · ' + total + ' files</span>' +
        '<span style="flex:1"></span>' +
        '<button class="btn btn-sm btn-secondary" onclick="' + this.j('clearQueue') + '"' + (this.uploading ? ' disabled' : '') + '>Clear</button>' +
        '<button class="btn btn-sm btn-start" onclick="' + this.j('startUpload') + '"' + (this.uploading ? ' disabled' : '') + '>Upload All</button></div>';
    this.queue.forEach(function (q, qi) {
        var prog = '';
        if (q.progress != null && !q.done) {
            var pct = Math.round(q.progress / q.entries.length * 100);
            prog = '<div class="progress-bar" style="margin:4px 0 0;width:120px"><div class="progress-fill" style="width:' + pct + '%"></div></div>';
        }
        html += '<div class="fm-queue-item">' +
            '<span class="fm-queue-name">' + esc(q.root) + '</span>' +
            '<span class="fm-queue-count">' + q.entries.length + ' files</span>' +
            (q.done ? '<span class="fm-queue-done">done</span>' : '') +
            '<span style="flex:1"></span>' + prog +
            '<button class="btn btn-sm btn-secondary" onclick="' + self.j('removeQueueItem', qi) + '"' + (self.uploading ? ' disabled' : '') + '>Remove</button>' +
            '</div>';
    });
    el.innerHTML = html;
};

FileManager.prototype.startUpload = async function () {
    if (this.uploading || !this.queue.length) return;
    this.uploading = true;
    this.renderQueue();
    var total = 0;
    var errs = [];
    for (var qi = 0; qi < this.queue.length; qi++) {
        var q = this.queue[qi];
        q.progress = 0;
        for (var start = 0; start < q.entries.length; start += 100) {
            var chunk = q.entries.slice(start, start + 100);
            var fd = new FormData();
            if (this.path) fd.append('path', this.path);
            for (var j = 0; j < chunk.length; j++) {
                fd.append('file', chunk[j].file, chunk[j].file.name);
                fd.append('relpath', chunk[j].rel);
            }
            try {
                var r = await apiFetch(this.cfg.uploadBatchUrl(), { method: 'POST', body: fd });
                if (!r) { errs.push({ error: 'no response' }); }
                else {
                    var d = await r.json();
                    total += d.uploaded || 0;
                    if (d.errors) errs = errs.concat(d.errors);
                }
            } catch (e) {
                errs.push({ error: e.message });
            }
            q.progress = start + chunk.length;
            this.renderQueue();
        }
        q.done = true;
        this.renderQueue();
    }
    this.uploading = false;
    this.showUploadResult(total, errs);
    this.queue = [];
    this.renderQueue();
    this.load(this.path);
};

FileManager.prototype.clearQueue = function () {
    if (this.uploading) return;
    this.queue = [];
    this.renderQueue();
};

FileManager.prototype.removeQueueItem = function (i) {
    if (this.uploading) return;
    this.queue.splice(i, 1);
    this.renderQueue();
};

FileManager.prototype.handleDrop = function (items) {
    var self = this;
    if (!items || !items.length) return;
    var entries = [];
    for (var i = 0; i < items.length; i++) {
        var it = items[i];
        if (it.webkitGetAsEntry) {
            var en = it.webkitGetAsEntry();
            if (en) entries.push(en);
        } else if (it.getAsFile) {
            var f = it.getAsFile();
            if (f) entries.push({ isFile: true, file: f });
        }
    }
    if (!entries.length) return;
    Promise.all(entries.map(function (en) {
        if (en.isFile) {
            return Promise.resolve([{ rel: en.file ? en.file.name : en.name, file: en.file || en }]);
        }
        return walkDirEntry(en);
    })).then(function (groups) {
        var added = 0;
        groups.forEach(function (list) {
            if (!list || !list.length) return;
            var root = (list[0].rel || 'file').split('/')[0];
            self.queue.push({ root: root, entries: list });
            added += list.length;
        });
        if (added) {
            self.renderQueue();
            toast(added + ' file(s) dropped — press "Upload All" to upload', 'info');
        }
    });
};

function walkDirEntry(entry) {
    return new Promise(function (resolve) {
        if (entry.isFile) {
            entry.file(function (f) {
                resolve([{ rel: f.name, file: f }]);
            }, function () { resolve([]); });
        } else if (entry.isDirectory) {
            var out = [];
            var reader = entry.createReader();
            var readBatch = function () {
                reader.readEntries(function (batch) {
                    if (!batch.length) {
                        resolve(out.map(function (x) { return { rel: entry.name + '/' + x.rel, file: x.file }; }));
                        return;
                    }
                    Promise.all(batch.map(walkDirEntry)).then(function (lists) {
                        lists.forEach(function (l) { out = out.concat(l); });
                        readBatch();
                    });
                }, function () { resolve([]); });
            };
            readBatch();
        } else {
            resolve([]);
        }
    });
}

/* ===================== Generic prompt modal ===================== */

var _fmPromptCb = null;

function fmPromptOpen(title, label, value, cb) {
    document.getElementById('fmPromptTitle').textContent = title || 'Enter value';
    document.getElementById('fmPromptLabel').textContent = label || 'Value';
    var input = document.getElementById('fmPromptInput');
    input.value = value || '';
    _fmPromptCb = cb;
    openModal('fmPromptModal');
    setTimeout(function () { input.focus(); input.select(); }, 60);
}

function fmPromptConfirm() {
    var cb = _fmPromptCb;
    _fmPromptCb = null;
    var v = document.getElementById('fmPromptInput').value;
    closeModal('fmPromptModal');
    if (cb) cb(v);
}

function fmPromptCancel() {
    _fmPromptCb = null;
    closeModal('fmPromptModal');
}

document.addEventListener('DOMContentLoaded', function () {
    var inp = document.getElementById('fmPromptInput');
    if (inp) {
        inp.addEventListener('keydown', function (e) {
            if (e.key === 'Enter') fmPromptConfirm();
            if (e.key === 'Escape') fmPromptCancel();
        });
    }
});
