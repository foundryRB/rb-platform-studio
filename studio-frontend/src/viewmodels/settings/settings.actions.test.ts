import { afterEach, beforeEach, describe, expect, vi } from 'vitest';
import { intent } from '@psa-department-of-engineering/vitest-intent';

import type {
    ConformanceReportResponse,
    OnboardingResultResponse,
    PlatformSettingResponse,
} from '@/models';

import { useSettings } from './settings.actions';
import { draftFor, draftProblem, isDirty } from './settings.model';

const report = (overrides: Partial<ConformanceReportResponse> = {}): ConformanceReportResponse => ({
    ok: true,
    exit_code: 0,
    passed: 12,
    failed: 0,
    skipped: 0,
    errors: 0,
    results: [],
    output: '12 passed',
    ...overrides,
});

const knob = (overrides: Partial<PlatformSettingResponse> = {}): PlatformSettingResponse => ({
    key: 'observability.log-retention',
    label: 'Log retention',
    category: 'observability',
    unit: 'duration',
    value: null,
    default: '720h',
    effective: '720h',
    source: 'values.yaml',
    field: 'observability.logRetention',
    description: 'How long Loki keeps ingested logs.',
    ...overrides,
});

const result = (): OnboardingResultResponse => ({
    app: 'observability.log-retention',
    changed_files: ['values.yaml'],
    baseline: report(),
    report: report(),
    branch: 'settings/observability-log-retention',
    pr: {
        number: 7,
        title: 'chore(settings): log retention -> 168h',
        url: 'https://github.com/example/platform/pull/7',
        branch: 'settings/observability-log-retention',
        state: 'open',
        merged: false,
    },
});

const jsonResponse = (status: number, body: unknown): Response =>
    ({
        ok: status >= 200 && status < 300,
        status,
        statusText: status === 422 ? 'Unprocessable Entity' : 'Error',
        json: async () => body,
    }) as unknown as Response;

const fetchMock = vi.fn<(...args: Parameters<typeof fetch>) => Promise<Response>>();

beforeEach(() => {
    useSettings.setState({
        settings: [],
        loading: false,
        drafts: {},
        submitting: null,
        error: null,
        result: null,
        rejection: null,
    });
    fetchMock.mockReset();
    vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
    vi.unstubAllGlobals();
});

describe('settings viewmodel', () => {
    it('accepts zero and whole runner counts while rejecting fractions', () => {
        const runners = knob({
            key: 'arc.max-runners',
            unit: 'count',
            default: '8',
            effective: '8',
            field: 'arc.maxRunners',
        });
        expect(draftProblem(runners, { [runners.key]: '0' })).toBeNull();
        expect(draftProblem(runners, { [runners.key]: '2' })).toBeNull();
        expect(draftProblem(runners, { [runners.key]: '1.5' })).not.toBeNull();
    });

    intent(
        'INT-SETTINGS-002',
        'the pane reads the curated knobs off the deploy branch',
        async () => {
            fetchMock.mockResolvedValueOnce(jsonResponse(200, [knob()]));

            await useSettings.getState().load();

            const [url] = fetchMock.mock.calls[0];
            expect(url).toBe('/api/settings');
            expect(useSettings.getState().settings).toHaveLength(1);
            expect(useSettings.getState().error).toBeNull();
        },
    );

    intent(
        'INT-SETTINGS-002',
        'an unpinned knob renders the chart default as what is in force, not as a pinned value',
        () => {
            const unpinned = knob();
            // Nothing typed yet: the field shows what the component runs with...
            expect(draftFor(unpinned, {})).toBe('720h');
            // ...but that is not something this install pins, so submitting it
            // IS a change (it survives a chart whose default later moves).
            expect(isDirty(unpinned, {})).toBe(true);

            const pinned = knob({ value: '720h', effective: '720h' });
            expect(isDirty(pinned, {})).toBe(false);
            expect(isDirty(pinned, { 'observability.log-retention': '168h' })).toBe(true);
        },
    );

    intent('INT-SETTINGS-002', 'submitting drives only the gated settings endpoint', async () => {
        fetchMock
            .mockResolvedValueOnce(jsonResponse(200, [knob({ value: '720h' })]))
            .mockResolvedValueOnce(jsonResponse(200, result()))
            .mockResolvedValueOnce(jsonResponse(200, [knob({ value: '720h' })]));

        await useSettings.getState().load();
        useSettings.getState().setDraft('observability.log-retention', '168h');
        await useSettings.getState().submit('observability.log-retention');

        const [url, init] = fetchMock.mock.calls[1];
        expect(url).toBe('/api/settings/observability.log-retention');
        expect(init?.method).toBe('PUT');
        expect(JSON.parse(init?.body as string)).toEqual({ value: '168h' });

        const state = useSettings.getState();
        expect(state.result?.pr?.number).toBe(7);
        expect(state.rejection).toBeNull();
        expect(state.submitting).toBeNull();
        // The write is a pull request, not an applied change: the pane re-reads
        // and still shows the branch as it stands, which is the honest value.
        expect(state.settings[0].value).toBe('720h');
    });

    intent('INT-SETTINGS-002', 'a malformed duration never reaches the API', async () => {
        fetchMock.mockResolvedValueOnce(jsonResponse(200, [knob({ value: '720h' })]));
        await useSettings.getState().load();
        fetchMock.mockReset();

        for (const bad of ['', '720', 'forever', '0h', '-1h']) {
            useSettings.getState().setDraft('observability.log-retention', bad);
            await useSettings.getState().submit('observability.log-retention');
            expect(useSettings.getState().error).not.toBeNull();
        }
        expect(fetchMock).not.toHaveBeenCalled();
    });

    intent(
        'INT-SETTINGS-002',
        'a 422 gate rejection surfaces new_failures and the report verbatim',
        async () => {
            const gateReport = report({ ok: false, exit_code: 1, failed: 2, output: 'FAILED ...' });
            fetchMock
                .mockResolvedValueOnce(jsonResponse(200, [knob({ value: '720h' })]))
                .mockResolvedValueOnce(
                    jsonResponse(422, {
                        error: 'ValidationFailedError',
                        detail: 'conformance gates failed; change rolled back',
                        report: gateReport,
                        new_failures: ['tests/conformance/test_config.py::test_values'],
                    }),
                );

            await useSettings.getState().load();
            useSettings.getState().setDraft('observability.log-retention', '168h');
            await useSettings.getState().submit('observability.log-retention');

            const state = useSettings.getState();
            expect(state.rejection?.new_failures).toEqual([
                'tests/conformance/test_config.py::test_values',
            ]);
            expect(state.rejection?.report).toEqual(gateReport);
            expect(state.result).toBeNull();
            expect(state.error).toBeNull();
        },
    );

    intent('INT-SETTINGS-002', 'a 409 no-op lands as a plain detail error', async () => {
        fetchMock
            .mockResolvedValueOnce(jsonResponse(200, [knob({ value: '720h' })]))
            .mockResolvedValueOnce(
                jsonResponse(409, {
                    error: 'AlreadyExistsError',
                    detail: 'platform setting value already exists: ... is already set to 168h',
                }),
            );

        await useSettings.getState().load();
        useSettings.getState().setDraft('observability.log-retention', '168h');
        await useSettings.getState().submit('observability.log-retention');

        const state = useSettings.getState();
        expect(state.error).toContain('already set to 168h');
        expect(state.rejection).toBeNull();
        expect(state.result).toBeNull();
    });
});
