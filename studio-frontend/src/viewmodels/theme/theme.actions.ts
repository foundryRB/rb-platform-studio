import { create } from 'zustand';

import type { ThemeMode, ThemeState } from './theme.state';

interface ThemeActions {
    toggle: () => void;
}

const initialMode = (): ThemeMode =>
    document.documentElement.classList.contains('light') ? 'light' : 'dark';

const apply = (mode: ThemeMode): void => {
    document.documentElement.classList.remove('dark', 'light');
    document.documentElement.classList.add(mode);
    try {
        localStorage.setItem('studio-theme', mode);
    } catch {
        // Persistence is best-effort; the session keeps the in-memory mode.
    }
};

export const useTheme = create<ThemeState & ThemeActions>()((set, get) => ({
    mode: initialMode(),

    toggle: () => {
        const mode: ThemeMode = get().mode === 'dark' ? 'light' : 'dark';
        apply(mode);
        set({ mode });
    },
}));
