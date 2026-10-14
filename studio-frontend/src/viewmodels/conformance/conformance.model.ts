import type { ConformanceReportResponse, TestResultResponse } from '@/models';

/** The suite parametrizes per-app tests as `...[<app>]`; pick one app's rows. */
export const resultsForApp = (
    report: ConformanceReportResponse | null,
    app: string,
): TestResultResponse[] => report?.results.filter((r) => r.node_id.includes(`[${app}]`)) ?? [];
