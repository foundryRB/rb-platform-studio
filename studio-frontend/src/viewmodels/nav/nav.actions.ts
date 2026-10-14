import { create } from 'zustand';

import type { NavState, StudioView } from './nav.state';

interface NavActions {
    setView: (view: StudioView) => void;
}

export const useNav = create<NavState & NavActions>()((set) => ({
    view: 'apps',

    setView: (view) => {
        set({ view });
    },
}));
