/* ===================== Init ===================== */

function logout() {
    setToken(null);
    window.location.href = '/admin/login';
}

async function init() {
    var token = getToken();
    if (!token) { window.location.href = '/admin/login'; return; }
    loadProjects();
    renderServerNav();
    loadJavaRuntimes();
}

document.addEventListener('DOMContentLoaded', init);
