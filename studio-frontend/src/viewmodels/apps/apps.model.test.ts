import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { AppResponse, TeamManifestResponse } from '@/models';

import { useApps } from './apps.actions';
import {
    canTogglePromotion,
    displayName,
    isPaused,
    isPromotionFrozen,
    selectDatabaseCandidates,
    selectEventsCandidates,
    selectIdentityCandidates,
    selectIdentityHolders,
} from './apps.model';

const manifest = (overrides: Partial<TeamManifestResponse> = {}): TeamManifestResponse => ({
    hostname: 'app.example.dev',
    repo_url: 'https://github.com/example/app',
    target_revision: 'main',
    display_name: 'An App',
    description: 'Does things.',
    icon: 'mdi-application',
    has_database: false,
    has_identity: false,
    has_events: false,
    paused: false,
    promotion: 'auto',
    ...overrides,
});

// `repo` is deliberately NOT the name on every row: an install whose org is
// shared prefixes its repositories while its apps keep their own names, and a
// fixture set where the two always coincide is what let that divergence go
// unnoticed everywhere it was assumed away.
const APPS: AppResponse[] = [
    {
        name: 'with-db',
        repo: 'fleet-with-db',
        mcp_url: null,
        role: 'output',
        status: 'running',
        promotion: 'auto',
        manifest: manifest({ display_name: 'With DB', has_database: true, has_identity: true }),
    },
    {
        name: 'without-db',
        repo: 'without-db',
        mcp_url: 'https://without-db.example.dev/mcp',
        role: 'output',
        status: 'paused',
        promotion: 'manual',
        manifest: manifest({
            display_name: 'Without DB',
            has_database: false,
            paused: true,
            promotion: 'manual',
        }),
    },
    {
        name: 'registry-only',
        repo: 'registry-only',
        mcp_url: null,
        role: 'output',
        status: 'unknown',
        promotion: 'unknown',
        manifest: null,
    },
];

const fetchMock = vi.fn<(...args: Parameters<typeof fetch>) => Promise<Response>>();

beforeEach(() => {
    useApps.setState({
        apps: [],
        loading: false,
        error: null,
        detail: null,
        pausing: [],
        freezing: [],
    });
    fetchMock.mockReset();
    vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
    vi.unstubAllGlobals();
});

describe('apps store join', () => {
    it('loads the registry rows joined with their manifests', async () => {
        fetchMock.mockResolvedValueOnce({
            ok: true,
            status: 200,
            json: async () => APPS,
        } as unknown as Response);

        await useApps.getState().load();

        const state = useApps.getState();
        expect(fetchMock).toHaveBeenCalledWith('/api/apps', expect.anything());
        expect(state.apps).toHaveLength(3);
        expect(displayName(state.apps[0])).toBe('With DB');
        // A registry-only row falls back to its registry name.
        expect(displayName(state.apps[2])).toBe('registry-only');
        // The database-grant form offers only onboarded apps without a database.
        expect(selectDatabaseCandidates(state).map((a) => a.name)).toEqual(['without-db']);
        // The realm-grant form offers only onboarded apps without a realm.
        expect(selectIdentityCandidates(state).map((a) => a.name)).toEqual(['without-db']);
        // And the realm re-render form the mirror image: only apps already holding one.
        expect(selectIdentityHolders(state).map((a) => a.name)).toEqual(['with-db']);
        // And the events-grant form every onboarded app not yet on the bus,
        // which is orthogonal to whether it holds the other grants.
        expect(selectEventsCandidates(state).map((a) => a.name)).toEqual([
            'with-db',
            'without-db',
        ]);
    });
});

describe('fleet status', () => {
    it('reads the desired-state status', () => {
        expect(isPaused(APPS[0])).toBe(false);
        expect(isPaused(APPS[1])).toBe(true);
    });

    it('pauses via the pause route and folds the updated app back into state', async () => {
        useApps.setState({ apps: APPS });
        fetchMock.mockResolvedValueOnce({
            ok: true,
            status: 200,
            json: async () => ({ ...APPS[0], status: 'paused' }),
        } as unknown as Response);

        await useApps.getState().setPaused('with-db', true);

        expect(fetchMock).toHaveBeenCalledWith(
            '/api/apps/with-db/pause',
            expect.objectContaining({ method: 'POST' }),
        );
        const row = useApps.getState().apps.find((a) => a.name === 'with-db');
        expect(row && isPaused(row)).toBe(true);
        expect(useApps.getState().pausing).toEqual([]);
    });

    it('resumes via the resume route when paused is false', async () => {
        useApps.setState({ apps: APPS });
        fetchMock.mockResolvedValueOnce({
            ok: true,
            status: 200,
            json: async () => ({ ...APPS[1], status: 'running' }),
        } as unknown as Response);

        await useApps.getState().setPaused('without-db', false);

        expect(fetchMock).toHaveBeenCalledWith(
            '/api/apps/without-db/resume',
            expect.objectContaining({ method: 'POST' }),
        );
    });

    it('surfaces the error and clears pausing when the pause request fails', async () => {
        useApps.setState({ apps: APPS });
        fetchMock.mockResolvedValueOnce({
            ok: false,
            status: 409,
            statusText: 'Conflict',
            json: async () => ({ detail: 'platform-studio cannot pause itself' }),
        } as unknown as Response);

        await useApps.getState().setPaused('with-db', true);

        expect(useApps.getState().error).toBe('platform-studio cannot pause itself');
        expect(useApps.getState().pausing).toEqual([]);
    });
});

describe('promotion mode', () => {
    it('reads the mode apart from the running/paused status', () => {
        // without-db is paused AND frozen; with-db runs and still promotes.
        expect(isPromotionFrozen(APPS[0])).toBe(false);
        expect(isPaused(APPS[1]) && isPromotionFrozen(APPS[1])).toBe(true);
        // A registry-only row has no promotion fact, so nothing to toggle.
        expect(canTogglePromotion(APPS[2])).toBe(false);
        expect(canTogglePromotion(APPS[0])).toBe(true);
    });

    it('freezes via the promotion route and folds the updated app back into state', async () => {
        useApps.setState({ apps: APPS });
        fetchMock.mockResolvedValueOnce({
            ok: true,
            status: 200,
            json: async () => ({ ...APPS[0], promotion: 'manual' }),
        } as unknown as Response);

        await useApps.getState().setPromotionFrozen('with-db', true);

        expect(fetchMock).toHaveBeenCalledWith(
            '/api/apps/with-db/promotion/freeze',
            expect.objectContaining({ method: 'POST' }),
        );
        const row = useApps.getState().apps.find((a) => a.name === 'with-db');
        expect(row && isPromotionFrozen(row)).toBe(true);
        // Freezing left the running/paused status alone.
        expect(row?.status).toBe('running');
        expect(useApps.getState().freezing).toEqual([]);
    });

    it('resumes promotion via the resume route when frozen is false', async () => {
        useApps.setState({ apps: APPS });
        fetchMock.mockResolvedValueOnce({
            ok: true,
            status: 200,
            json: async () => ({ ...APPS[1], promotion: 'auto' }),
        } as unknown as Response);

        await useApps.getState().setPromotionFrozen('without-db', false);

        expect(fetchMock).toHaveBeenCalledWith(
            '/api/apps/without-db/promotion/resume',
            expect.objectContaining({ method: 'POST' }),
        );
    });

    it('surfaces the error and clears freezing when the freeze is refused', async () => {
        useApps.setState({ apps: APPS });
        fetchMock.mockResolvedValueOnce({
            ok: false,
            status: 409,
            statusText: 'Conflict',
            json: async () => ({ detail: 'its Application declares no image-list' }),
        } as unknown as Response);

        await useApps.getState().setPromotionFrozen('with-db', true);

        expect(useApps.getState().error).toBe('its Application declares no image-list');
        expect(useApps.getState().freezing).toEqual([]);
    });
});
