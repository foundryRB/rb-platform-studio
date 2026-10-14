import { create } from 'zustand';

import type { ConformanceReportResponse } from '@/models';
import { apiFetch } from '@/utils';

import type { ConformanceState } from './conformance.state';

interface ConformanceActions {
    run: () => Promise<void>;
}

export const useConformance = create<ConformanceState & ConformanceActions>()((set) => ({
    report: null,
    running: false,
    error: null,

    run: async () => {
        set({ running: true, error: null });
        try {
            const report = await apiFetch<ConformanceReportResponse>('/api/conformance/run', {
                method: 'POST',
            });
            set({ report });
        } catch (err) {
            set({ error: err instanceof Error ? err.message : 'Conformance run failed' });
        } finally {
            set({ running: false });
        }
    },
}));
