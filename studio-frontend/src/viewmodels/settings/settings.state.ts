import type { OnboardingResultResponse, PlatformSettingResponse } from '@/models';

import type { OnboardRejection } from '@/viewmodels/onboard';

export interface SettingsState {
    /** The curated knobs as the deploy branch has them; empty until loaded. */
    settings: PlatformSettingResponse[];
    loading: boolean;
    /** Per-knob draft value, keyed by setting key. Absent means untouched. */
    drafts: Record<string, string>;
    /** The knob currently being written; only one gated change runs at a time. */
    submitting: string | null;
    /** A read failure, or a 4xx from a write (not a gate rejection). */
    error: string | null;
    /** The gated change that landed, once a write passed. */
    result: OnboardingResultResponse | null;
    /** A 422 gate rejection: the change was rolled back byte-identical. */
    rejection: OnboardRejection | null;
}
