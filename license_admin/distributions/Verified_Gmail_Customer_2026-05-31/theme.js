/* theme.js — must load in <head> before any render to prevent FOUC */
(function () {
    try {
        var t = localStorage.getItem('pos_theme');
        if (!t) {
            t = 'dark';
            localStorage.setItem('pos_theme', 'dark'); // persist default so every page agrees
        }
        if (t === 'dark') {
            document.documentElement.setAttribute('data-theme', 'dark');
            document.documentElement.classList.add('dark');
        }
    } catch (e) {}
}());
