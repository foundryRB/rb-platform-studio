import type { PrInfoResponse } from '@/models';

export interface PrsState {
    prs: PrInfoResponse[];
    loading: boolean;
    error: string | null;
    /** True when the route 404s: the local composition has no PR surface. */
    unavailable: boolean;
}
