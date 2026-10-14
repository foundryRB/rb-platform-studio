import { create } from 'zustand';

import type { PrInfoResponse } from '@/models';

import type { PrsState } from './prs.state';

interface PrsActions {
    load: () => Promise<void>;
}

export const usePrs = create<PrsState & PrsActions>()((set) => ({
    prs: [],
    loading: false,
    error: null,
    unavailable: false,

    load: async () => {
        set({ loading: true, error: null, unavailable: false });
        try {
            const response = await fetch('/api/prs');
            if (response.status === 404) {
                set({ unavailable: true, prs: [] });
                return;
            }
            if (!response.ok) {
                let detail = `${response.status} ${response.statusText}`;
                try {
                    const body = (await response.json()) as { detail?: string; error?: string };
                    detail = body.detail ?? body.error ?? detail;
                } catch {
                    // Non-JSON error body; keep the status text.
                }
                throw new Error(detail);
            }
            const prs = (await response.json()) as PrInfoResponse[];
            set({ prs });
        } catch (err) {
            set({ error: err instanceof Error ? err.message : 'Failed to load pull requests' });
        } finally {
            set({ loading: false });
        }
    },
}));
