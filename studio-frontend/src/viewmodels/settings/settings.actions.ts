import { create } from 'zustand';

import type { OnboardingResultResponse, PlatformSettingResponse } from '@/models';
import { apiFetch } from '@/utils';
import type { OnboardRejection } from '@/viewmodels/onboard';

import { draftProblem } from './settings.model';
import type { SettingsState } from './settings.state';

interface SettingsActions {
    load: () => Promise<void>;
    setDraft: (key: string, value: string) => void;
    resetDraft: (key: string) => void;
    submit: (key: string) => Promise<void>;
}

const INITIAL: SettingsState = {
    settings: [],
    loading: false,
    drafts: {},
    submitting: null,
    error: null,
    result: null,
    rejection: null,
};

export const useSettings = create<SettingsState & SettingsActions>()((set, get) => ({
    ...INITIAL,

    load: async () => {
        set({ loading: true, error: null });
        try {
            const settings = await apiFetch<PlatformSettingResponse[]>('/api/settings');
            set({ settings });
        } catch (err) {
            set({ error: err instanceof Error ? err.message : 'Could not read platform settings' });
        } finally {
            set({ loading: false });
        }
    },

    setDraft: (key, value) => {
        set({ drafts: { ...get().drafts, [key]: value } });
    },

    resetDraft: (key) => {
        const drafts = { ...get().drafts };
        delete drafts[key];
        set({ drafts });
    },

    submit: async (key) => {
        const { settings, drafts } = get();
        const setting = settings.find((candidate) => candidate.key === key);
        if (!setting) return;
        const problem = draftProblem(setting, drafts);
        if (problem !== null) {
            set({ error: problem, result: null, rejection: null });
            return;
        }
        const value = (drafts[key] ?? setting.effective).trim();

        set({ submitting: key, error: null, result: null, rejection: null });
        try {
            const response = await fetch(`/api/settings/${encodeURIComponent(key)}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ value }),
            });
            if (response.ok) {
                set({ result: (await response.json()) as OnboardingResultResponse });
                // The write is a pull request, not an applied change: re-reading
                // shows the branch as it still stands until CI merges it, which
                // is the honest thing to render.
                await get().load();
                return;
            }
            let body: Partial<OnboardRejection> & { error?: string } = {};
            try {
                body = (await response.json()) as Partial<OnboardRejection> & { error?: string };
            } catch {
                // Non-JSON error body; fall through to the status text.
            }
            const detail = body.detail ?? `${response.status} ${response.statusText}`;
            if (response.status === 422 && body.new_failures) {
                set({
                    rejection: {
                        detail,
                        new_failures: body.new_failures,
                        report: body.report ?? null,
                    },
                });
                return;
            }
            set({ error: detail });
        } catch (err) {
            set({ error: err instanceof Error ? err.message : 'The settings write failed' });
        } finally {
            set({ submitting: null });
        }
    },
}));
