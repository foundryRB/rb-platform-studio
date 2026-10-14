/* Run before first paint. Preferences are local to each application origin. */
(() => {
    const root = document.documentElement;
    root.dataset.vfShell = 'true';
    const system = matchMedia('(prefers-color-scheme: dark)');
    const reduced = matchMedia('(prefers-reduced-motion: reduce)');
    const read = (key, fallback) => {
        try {
            return localStorage.getItem(key) || fallback;
        } catch {
            return fallback;
        }
    };
    const legacyKey = document.currentScript?.dataset.legacyTheme;
    const legacy = legacyKey ? read(legacyKey, 'system') : 'system';
    let preference = read('rb.appearance', legacy);
    if (!['light', 'dark', 'system'].includes(preference)) preference = 'system';
    let motion = read('rb.motion', 'on') !== 'off';
    function apply() {
        const resolved = preference === 'system' ? (system.matches ? 'dark' : 'light') : preference;
        root.dataset.theme = resolved;
        root.dataset.appearance = preference;
        root.classList.toggle('dark', resolved === 'dark');
        root.classList.toggle('light', resolved === 'light');
        root.dataset.motion = motion && !reduced.matches ? 'on' : 'off';
        root.dataset.hidden = String(document.hidden);
        root.style.colorScheme = resolved;
        document.dispatchEvent(new Event('rb-appearance'));
    }
    window.rbAppearance = {
        get: () => ({ preference, resolved: root.dataset.theme, motion, reduced: reduced.matches }),
        set: (next) => {
            if (['light', 'dark', 'system'].includes(next)) preference = next;
            try {
                localStorage.setItem('rb.appearance', preference);
            } catch {
                /* Private browsing. */
            }
            apply();
        },
        setMotion: (enabled) => {
            motion = Boolean(enabled);
            try {
                localStorage.setItem('rb.motion', motion ? 'on' : 'off');
            } catch {
                /* Private browsing. */
            }
            apply();
        },
    };
    system.addEventListener('change', apply);
    reduced.addEventListener('change', apply);
    document.addEventListener('visibilitychange', apply);
    window.addEventListener('storage', (event) => {
        if (event.key === 'rb.appearance' || event.key === null) {
            const saved = read('rb.appearance', 'system');
            preference = ['dark', 'light', 'system'].includes(saved) ? saved : 'system';
        }
        if (event.key === 'rb.motion' || event.key === null)
            motion = read('rb.motion', 'on') !== 'off';
        apply();
    });
    apply();
})();
