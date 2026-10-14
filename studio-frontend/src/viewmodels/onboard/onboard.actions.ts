import { create } from 'zustand';

import type { OnboardingResultResponse, RepoScaffoldResponse } from '@/models';

import { appNameProblem } from './onboard.model';
import type { OnboardRejection, OnboardState } from './onboard.state';

type TextField =
    | 'appName'
    | 'displayName'
    | 'description'
    | 'icon'
    | 'repo'
    | 'imageComponents'
    | 'databaseApp'
    | 'identityApp'
    | 'eventsApp'
    | 'eventsDomains'
    | 'offboardApp'
    | 'reconcileApp'
    | 'reconcileComponents'
    | 'reconcileDescription'
    | 'reconcileIdentityApp'
    | 'repoName'
    | 'repoDisplayName'
    | 'repoDescription';

interface OnboardActions {
    setField: (field: TextField, value: string) => void;
    setExposeMcp: (exposeMcp: boolean) => void;
    reset: () => void;
    submitApp: () => Promise<void>;
    submitDatabase: () => Promise<void>;
    submitIdentity: () => Promise<void>;
    submitEvents: () => Promise<void>;
    submitOffboard: () => Promise<void>;
    submitReconcile: () => Promise<void>;
    submitReconcileIdentity: () => Promise<void>;
    submitCreateRepo: () => Promise<void>;
}

const INITIAL: OnboardState = {
    appName: '',
    displayName: '',
    description: '',
    icon: 'mdi-application',
    exposeMcp: false,
    repo: '',
    imageComponents: '',
    databaseApp: '',
    identityApp: '',
    eventsApp: '',
    eventsDomains: '',
    offboardApp: '',
    reconcileApp: '',
    reconcileComponents: '',
    reconcileDescription: '',
    reconcileIdentityApp: '',
    repoName: '',
    repoDisplayName: '',
    repoDescription: '',
    repoResult: null,
    submitting: false,
    error: null,
    result: null,
    rejection: null,
};

/** POST one gated onboarding endpoint and fold the outcome into the store. */
const submitGated = async (
    url: string,
    payload: object,
    set: (partial: Partial<OnboardState>) => void,
): Promise<void> => {
    set({ submitting: true, error: null, result: null, rejection: null });
    try {
        const response = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        if (response.ok) {
            set({ result: (await response.json()) as OnboardingResultResponse });
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
        set({ error: err instanceof Error ? err.message : 'Onboarding request failed' });
    } finally {
        set({ submitting: false });
    }
};

export const useOnboard = create<OnboardState & OnboardActions>()((set, get) => ({
    ...INITIAL,

    setField: (field, value) => {
        set({ [field]: value } as Partial<OnboardState>);
    },

    setExposeMcp: (exposeMcp) => {
        set({ exposeMcp });
    },

    reset: () => {
        set(INITIAL);
    },

    submitApp: async () => {
        const { appName, displayName, description, icon, exposeMcp, repo, imageComponents } = get();
        const name = appName.trim();
        const problem = appNameProblem(name);
        if (problem !== null) {
            set({ error: problem, result: null, rejection: null });
            return;
        }
        await submitGated(
            '/api/onboard/app',
            {
                name,
                display_name: displayName.trim(),
                description: description.trim(),
                icon: icon.trim(),
                expose_mcp: exposeMcp,
                repo: repo.trim(),
                image_components: imageComponents
                    .split(',')
                    .map((component) => component.trim())
                    .filter((component) => component !== ''),
            },
            set,
        );
    },

    submitDatabase: async () => {
        const name = get().databaseApp;
        if (name === '') {
            set({ error: 'Pick the app the database belongs to.', result: null, rejection: null });
            return;
        }
        await submitGated('/api/onboard/database', { name }, set);
    },

    submitIdentity: async () => {
        const name = get().identityApp;
        if (name === '') {
            set({ error: 'Pick the app the realm belongs to.', result: null, rejection: null });
            return;
        }
        await submitGated('/api/onboard/identity', { name }, set);
    },

    submitEvents: async () => {
        const name = get().eventsApp;
        if (name === '') {
            set({ error: 'Pick the app the grant belongs to.', result: null, rejection: null });
            return;
        }
        // Publishing is owned per domain, so the grant names at least one and the
        // form refuses before it reaches the gated endpoint.
        const domains = get()
            .eventsDomains.split(',')
            .map((domain) => domain.trim())
            .filter((domain) => domain !== '');
        if (domains.length === 0) {
            set({
                error: 'Name at least one REF-Events domain this app publishes under.',
                result: null,
                rejection: null,
            });
            return;
        }
        await submitGated('/api/onboard/events', { name, domains }, set);
    },

    submitOffboard: async () => {
        const name = get().offboardApp;
        if (name === '') {
            set({ error: 'Pick the app to offboard.', result: null, rejection: null });
            return;
        }
        await submitGated('/api/offboard/app', { name }, set);
    },

    submitReconcile: async () => {
        const { reconcileApp, reconcileComponents, reconcileDescription } = get();
        if (reconcileApp === '') {
            set({ error: 'Pick the app to reconcile.', result: null, rejection: null });
            return;
        }
        await submitGated(
            '/api/reconcile/app',
            {
                name: reconcileApp,
                image_components: reconcileComponents
                    .split(',')
                    .map((component) => component.trim())
                    .filter((component) => component !== ''),
                description: reconcileDescription.trim(),
            },
            set,
        );
    },

    submitReconcileIdentity: async () => {
        const name = get().reconcileIdentityApp;
        if (name === '') {
            set({ error: 'Pick the app whose realm to reconcile.', result: null, rejection: null });
            return;
        }
        await submitGated('/api/reconcile/identity', { name }, set);
    },

    submitCreateRepo: async () => {
        const { repoName, repoDisplayName, repoDescription } = get();
        const name = repoName.trim();
        const problem = appNameProblem(name);
        if (problem !== null) {
            set({ error: problem, repoResult: null });
            return;
        }
        set({ submitting: true, error: null, repoResult: null });
        try {
            const response = await fetch('/api/repos/app', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    name,
                    display_name: repoDisplayName.trim(),
                    description: repoDescription.trim(),
                }),
            });
            if (response.ok) {
                set({ repoResult: (await response.json()) as RepoScaffoldResponse });
                return;
            }
            let detail = `${response.status} ${response.statusText}`;
            try {
                const body = (await response.json()) as { detail?: string };
                detail = body.detail ?? detail;
            } catch {
                // Non-JSON error body; keep the status text.
            }
            set({ error: detail });
        } catch (err) {
            set({ error: err instanceof Error ? err.message : 'Repo creation failed' });
        } finally {
            set({ submitting: false });
        }
    },
}));
