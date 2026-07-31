/* ===================== Config form rendering ===================== */

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
        if (f.description) {
            var desc = document.createElement('div');
            desc.className = 'config-desc';
            desc.textContent = f.description;
            group.appendChild(desc);
        }
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
            var sw = document.createElement('label');
            sw.className = 'config-switch';
            sw.appendChild(input);
            var track = document.createElement('span');
            track.className = 'config-switch-track';
            var thumb = document.createElement('span');
            thumb.className = 'config-switch-thumb';
            track.appendChild(thumb);
            sw.appendChild(track);
            group.appendChild(sw);
            group.classList.add('config-field-switch');
        } else if (f.options) {
            input = document.createElement('select');
            var hasMatch = false;
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
                if (opt.value === f.value) hasMatch = true;
                input.appendChild(opt);
            }
            input.dataset.type = 'str';
            group.appendChild(input);
            if (f.key === 'java_executable_path') {
                var customOpt = document.createElement('option');
                customOpt.value = '__custom';
                customOpt.textContent = 'Custom path...';
                input.appendChild(customOpt);
                var customWrap = document.createElement('div');
                customWrap.style.display = 'none';
                customWrap.style.marginTop = '6px';
                var customInput = document.createElement('input');
                customInput.type = 'text';
                customInput.placeholder = 'e.g. C:\\Program Files\\Java\\jdk-17\\bin\\java.exe';
                customInput.className = 'config-input';
                customInput.dataset.type = 'str';
                customInput.dataset.customFor = f.key;
                customWrap.appendChild(customInput);
                group.appendChild(customWrap);
                var useCustom = f.value && f.value !== 'java' && !hasMatch;
                if (useCustom) {
                    input.value = '__custom';
                    customWrap.style.display = 'block';
                    customInput.value = f.value;
                }
                (function (sel, wrap) {
                    sel.addEventListener('change', function () {
                        wrap.style.display = this.value === '__custom' ? 'block' : 'none';
                    });
                })(input, customWrap);
            }
        } else {
            input = document.createElement('input');
            input.type = f.type === 'int' ? 'number' : 'text';
            input.value = f.value != null ? f.value : '';
            input.dataset.type = f.type;
            group.appendChild(input);
        }
        input.name = f.key;
        input.className = 'config-input';
        if (f.type !== 'bool') group.appendChild(input);
        form.appendChild(group);
    }
    var btnRow = document.createElement('div');
    btnRow.className = 'row config-actions';
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
    var customs = {};
    for (var i = 0; i < inputs.length; i++) {
        var inp = inputs[i];
        if (inp.dataset.sensitive) { if (inp.value) data[inp.name] = inp.value; }
        else if (inp.type === 'checkbox') { data[inp.name] = inp.checked; }
        else if (inp.type === 'number') { data[inp.name] = parseInt(inp.value, 10) || 0; }
        else if (inp.dataset.customFor) { customs[inp.dataset.customFor] = inp.value; }
        else { data[inp.name] = inp.value; }
    }
    for (var key in customs) {
        if (customs.hasOwnProperty(key) && data[key] === '__custom') {
            data[key] = customs[key];
        }
    }
    return data;
}
