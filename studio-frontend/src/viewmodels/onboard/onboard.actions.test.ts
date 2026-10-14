import { afterEach, beforeEach, describe, expect, vi } from 'vitest';
import { intent } from '@psa-department-of-engineering/vitest-intent';

import type { ConformanceReportResponse, OnboardingResultResponse } from '@/models';

import { useOnboard } from './onboard.actions';

const report = (overrides: Partial<ConformanceReportResponse> = {}): ConformanceReportResponse => ({
    ok: true,
    exit_code: 0,
    passed: 12,
    failed: 0,
    skipped: 1,
    errors: 0,
    results: [
        {
            node_id: 'tests/conformance/test_apps.py::test_manifest[my-app]',
            outcome: 'passed',
            detail: '',
        },
    ],
    output: '12 passed, 1 skipped',
    ...overrides,
});

const jsonResponse = (status: number, body: unknown): Response =>
    ({
        ok: status >= 200 && status < 300,
        status,
        statusText: status === 422 ? 'Unprocessable Entity' : 'Error',
        json: async () => body,
    }) as unknown as Response;

const fetchMock = vi.fn<(...args: Parameters<typeof fetch>) => Promise<Response>>();

const fillAppForm = () => {
    const { setField } = useOnboard.getState();
    setField('appName', 'my-app');
    setField('displayName', 'My App');
    setField('description', 'Does app things.');
    setField('icon', 'mdi-rocket');
};

beforeEach(() => {
    useOnboard.getState().reset();
    fetchMock.mockReset();
    vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
    vi.unstubAllGlobals();
});

describe('onboard viewmodel', () => {
    intent(
        'INT-SPA-001',
        'a successful app onboarding populates the result, including the PR url',
        async () => {
            const result: OnboardingResultResponse = {
                app: 'my-app',
                changed_files: ['platform/teams/my-app.yaml', 'registry/apps.yaml'],
                baseline: report(),
                report: report({ passed: 14 }),
                branch: 'onboard/my-app',
                pr: {
                    number: 7,
                    title: 'Onboard my-app',
                    url: 'https://github.com/example/platform/pull/7',
                    branch: 'onboard/my-app',
                    state: 'open',
                    merged: false,
                },
            };
            fetchMock.mockResolvedValueOnce(jsonResponse(200, result));

            fillAppForm();
            await useOnboard.getState().submitApp();

            const state = useOnboard.getState();
            expect(state.result?.pr?.url).toBe('https://github.com/example/platform/pull/7');
            expect(state.result?.branch).toBe('onboard/my-app');
            expect(state.result?.changed_files).toEqual([
                'platform/teams/my-app.yaml',
                'registry/apps.yaml',
            ]);
            expect(state.rejection).toBeNull();
            expect(state.error).toBeNull();
            expect(state.submitting).toBe(false);
        },
    );

    intent('INT-SPA-001', 'the app form drives only the gated onboarding endpoint', async () => {
        fetchMock.mockResolvedValueOnce(
            jsonResponse(200, {
                app: 'my-app',
                changed_files: [],
                baseline: report(),
                report: report(),
                branch: null,
                pr: null,
            }),
        );

        fillAppForm();
        useOnboard.getState().setExposeMcp(true);
        // The component list rides as image_components, split on commas with
        // blanks dropped; empty input sends the single-image shape ([]).
        useOnboard.getState().setField('imageComponents', 'server, client, ');
        await useOnboard.getState().submitApp();

        expect(fetchMock).toHaveBeenCalledTimes(1);
        const [url, init] = fetchMock.mock.calls[0];
        expect(url).toBe('/api/onboard/app');
        expect(init?.method).toBe('POST');
        expect(JSON.parse(init?.body as string)).toEqual({
            name: 'my-app',
            display_name: 'My App',
            description: 'Does app things.',
            icon: 'mdi-rocket',
            expose_mcp: true,
            // Empty: the repository is named for the app unless the form names it.
            repo: '',
            image_components: ['server', 'client'],
        });
    });

    intent(
        'INT-SPA-001',
        'the reconcile-identity form drives only the gated realm re-render endpoint',
        async () => {
            fetchMock.mockResolvedValueOnce(
                jsonResponse(200, {
                    app: 'my-app',
                    changed_files: ['teams/my-app/config.yaml', 'teams/my-app/jobs.yaml'],
                    baseline: report(),
                    report: report(),
                    branch: 'reconcile/my-app-identity',
                    pr: null,
                }),
            );

            useOnboard.getState().setField('reconcileIdentityApp', 'my-app');
            await useOnboard.getState().submitReconcileIdentity();

            expect(fetchMock).toHaveBeenCalledTimes(1);
            const [url, init] = fetchMock.mock.calls[0];
            expect(url).toBe('/api/reconcile/identity');
            expect(init?.method).toBe('POST');
            // The declaration is the install's own, read off the branch: the form
            // names the app and nothing else.
            expect(JSON.parse(init?.body as string)).toEqual({ name: 'my-app' });
            expect(useOnboard.getState().result?.branch).toBe('reconcile/my-app-identity');
        },
    );

    intent(
        'INT-SPA-001',
        'the reconcile-identity form refuses to submit without an app',
        async () => {
            await useOnboard.getState().submitReconcileIdentity();
            expect(fetchMock).not.toHaveBeenCalled();
            expect(useOnboard.getState().error).toMatch(/whose realm/);
        },
    );

    intent(
        'INT-SPA-001',
        'the app form carries a repository named differently from the app',
        async () => {
            fetchMock.mockResolvedValueOnce(
                jsonResponse(200, {
                    app: 'csd',
                    changed_files: [],
                    baseline: report(),
                    report: report(),
                    branch: null,
                    pr: null,
                }),
            );
            const { setField, submitApp } = useOnboard.getState();
            setField('appName', 'csd');
            setField('displayName', 'CSD');
            setField('description', 'Cognitive software delivery.');
            setField('icon', 'mdi-brain');
            setField('repo', ' cognitive-software-delivery ');
            await submitApp();

            const [, init] = fetchMock.mock.calls[0];
            const body = JSON.parse(init?.body as string) as Record<string, unknown>;
            expect(body.name).toBe('csd');
            expect(body.repo).toBe('cognitive-software-delivery');
        },
    );

    intent(
        'INT-SPA-001',
        'a 422 gate rejection surfaces new_failures and the report verbatim',
        async () => {
            const gateReport = report({
                ok: false,
                exit_code: 1,
                passed: 11,
                failed: 2,
                output: 'FAILED tests/conformance/test_apps.py::test_gateway[my-app]',
            });
            fetchMock.mockResolvedValueOnce(
                jsonResponse(422, {
                    error: 'ValidationFailedError',
                    detail: 'conformance gates failed; onboarding rolled back: test_gateway[my-app]',
                    report: gateReport,
                    new_failures: [
                        'tests/conformance/test_apps.py::test_gateway[my-app]',
                        'tests/conformance/test_apps.py::test_rbac[my-app]',
                    ],
                }),
            );

            fillAppForm();
            await useOnboard.getState().submitApp();

            const state = useOnboard.getState();
            expect(state.rejection?.new_failures).toEqual([
                'tests/conformance/test_apps.py::test_gateway[my-app]',
                'tests/conformance/test_apps.py::test_rbac[my-app]',
            ]);
            expect(state.rejection?.report).toEqual(gateReport);
            expect(state.rejection?.detail).toBe(
                'conformance gates failed; onboarding rolled back: test_gateway[my-app]',
            );
            expect(state.result).toBeNull();
            expect(state.error).toBeNull();
        },
    );

    intent(
        'INT-SPA-001',
        'a name that is not a lowercase DNS label never reaches the API',
        async () => {
            const { setField, submitApp } = useOnboard.getState();
            for (const bad of ['My-App', 'my_app', '-leading', 'trailing-', '']) {
                useOnboard.getState().reset();
                setField('appName', bad);
                setField('displayName', 'My App');
                setField('description', 'Does app things.');
                setField('icon', 'mdi-rocket');
                await submitApp();
                expect(useOnboard.getState().error).not.toBeNull();
            }
            expect(fetchMock).not.toHaveBeenCalled();
        },
    );

    intent(
        'INT-SPA-001',
        'the database form drives only the gated onboarding endpoint',
        async () => {
            fetchMock.mockResolvedValueOnce(
                jsonResponse(200, {
                    app: 'my-app',
                    changed_files: ['platform/teams/my-app.yaml'],
                    baseline: report(),
                    report: report(),
                    branch: null,
                    pr: null,
                }),
            );

            useOnboard.getState().setField('databaseApp', 'my-app');
            await useOnboard.getState().submitDatabase();

            expect(fetchMock).toHaveBeenCalledTimes(1);
            const [url, init] = fetchMock.mock.calls[0];
            expect(url).toBe('/api/onboard/database');
            expect(init?.method).toBe('POST');
            expect(JSON.parse(init?.body as string)).toEqual({ name: 'my-app' });
            // A null pr is the local-run shape; the result still lands.
            expect(useOnboard.getState().result?.pr).toBeNull();
        },
    );

    intent(
        'INT-SPA-001',
        'the events form drives only the gated endpoint, and splits its domains',
        async () => {
            fetchMock.mockResolvedValueOnce(
                jsonResponse(200, {
                    app: 'my-app',
                    changed_files: [],
                    conformance: null,
                    branch: null,
                    pr: null,
                }),
            );

            useOnboard.getState().setField('eventsApp', 'my-app');
            useOnboard.getState().setField('eventsDomains', ' platform , delivery ');
            await useOnboard.getState().submitEvents();

            expect(fetchMock).toHaveBeenCalledTimes(1);
            const [url, init] = fetchMock.mock.calls[0];
            expect(url).toBe('/api/onboard/events');
            expect(init?.method).toBe('POST');
            expect(JSON.parse(init?.body as string)).toEqual({
                name: 'my-app',
                domains: ['platform', 'delivery'],
            });
        },
    );

    intent(
        'INT-SPA-001',
        'the events form refuses a grant that names no domain, before any request',
        async () => {
            useOnboard.getState().setField('eventsApp', 'my-app');
            useOnboard.getState().setField('eventsDomains', '  ,  ');
            await useOnboard.getState().submitEvents();

            // Publishing is owned per domain, so a grant scoping nothing never
            // reaches the gate and never opens an empty pull request.
            expect(fetchMock).not.toHaveBeenCalled();
            expect(useOnboard.getState().error).toContain('at least one');
        },
    );

    intent(
        'INT-SPA-001',
        'the identity form drives only the gated onboarding endpoint',
        async () => {
            fetchMock.mockResolvedValueOnce(
                jsonResponse(200, {
                    app: 'my-app',
                    changed_files: ['platform/teams/my-app.yaml'],
                    baseline: report(),
                    report: report(),
                    branch: null,
                    pr: null,
                }),
            );

            useOnboard.getState().setField('identityApp', 'my-app');
            await useOnboard.getState().submitIdentity();

            expect(fetchMock).toHaveBeenCalledTimes(1);
            const [url, init] = fetchMock.mock.calls[0];
            expect(url).toBe('/api/onboard/identity');
            expect(init?.method).toBe('POST');
            expect(JSON.parse(init?.body as string)).toEqual({ name: 'my-app' });
        },
    );

    intent(
        'INT-SPA-001',
        'a 409 conflict lands as a plain detail error, not a gate rejection',
        async () => {
            fetchMock.mockResolvedValueOnce(
                jsonResponse(409, {
                    error: 'AppAlreadyOnboardedError',
                    detail: "app 'my-app' is already onboarded",
                }),
            );

            fillAppForm();
            await useOnboard.getState().submitApp();

            const state = useOnboard.getState();
            expect(state.error).toBe("app 'my-app' is already onboarded");
            expect(state.rejection).toBeNull();
            expect(state.result).toBeNull();
        },
    );
});
