import { create } from 'zustand';

import type { AppResponse } from '@/models';
import { apiFetch } from '@/utils';

import type { AppsState } from './apps.state';

interface AppsActions {
    load: () => Promise<void>;
    select: (name: string) => Promise<void>;
    setPaused: (name: string, paused: boolean) => Promise<void>;
    setPromotionFrozen: (name: string, frozen: boolean) => Promise<void>;
}

export const useApps = create<AppsState & AppsActions>()((set) => ({
    apps: [],
    loading: false,
    error: null,
    selected: null,
    detail: null,
    detailLoading: false,
    detailError: null,
    pausing: [],
    freezing: [],

    load: async () => {
        set({ loading: true, error: null });
        try {
            const apps = await apiFetch<AppResponse[]>('/api/apps');
            set({ apps });
        } catch (err) {
            set({ error: err instanceof Error ? err.message : 'Failed to load apps' });
        } finally {
            set({ loading: false });
        }
    },

    select: async (name) => {
        set({ selected: name, detail: null, detailLoading: true, detailError: null });
        try {
            const detail = await apiFetch<AppResponse>(`/api/apps/${encodeURIComponent(name)}`);
            set({ detail });
        } catch (err) {
            set({ detailError: err instanceof Error ? err.message : 'Failed to load app' });
        } finally {
            set({ detailLoading: false });
        }
    },

    setPaused: async (name, paused) => {
        set((state) => ({ pausing: [...state.pausing, name], error: null }));
        try {
            const action = paused ? 'pause' : 'resume';
            const updated = await apiFetch<AppResponse>(
                `/api/apps/${encodeURIComponent(name)}/${action}`,
                { method: 'POST' },
            );
            set((state) => ({
                apps: state.apps.map((app) => (app.name === name ? updated : app)),
                detail: state.detail?.name === name ? updated : state.detail,
            }));
        } catch (err) {
            set({ error: err instanceof Error ? err.message : 'Failed to change app state' });
        } finally {
            set((state) => ({ pausing: state.pausing.filter((n) => n !== name) }));
        }
    },

    setPromotionFrozen: async (name, frozen) => {
        set((state) => ({ freezing: [...state.freezing, name], error: null }));
        try {
            const action = frozen ? 'freeze' : 'resume';
            const updated = await apiFetch<AppResponse>(
                `/api/apps/${encodeURIComponent(name)}/promotion/${action}`,
                { method: 'POST' },
            );
            set((state) => ({
                apps: state.apps.map((app) => (app.name === name ? updated : app)),
                detail: state.detail?.name === name ? updated : state.detail,
            }));
        } catch (err) {
            set({ error: err instanceof Error ? err.message : 'Failed to change promotion' });
        } finally {
            set((state) => ({ freezing: state.freezing.filter((n) => n !== name) }));
        }
    },
}));
