import type { ConformanceReportResponse } from '@/models';

export interface ConformanceState {
    /** The last run's report; shared by the conformance page and app detail. */
    report: ConformanceReportResponse | null;
    running: boolean;
    error: string | null;
}
