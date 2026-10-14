import type { AppResponse } from '@/models';

export interface AppsState {
    apps: AppResponse[];
    loading: boolean;
    error: string | null;
    /** Registry name of the app the detail page shows. */
    selected: string | null;
    detail: AppResponse | null;
    detailLoading: boolean;
    detailError: string | null;
    /** Registry names with a pause/resume request in flight. */
    pausing: string[];
    /** Registry names with a freeze/resume-promotion request in flight. */
    freezing: string[];
}
