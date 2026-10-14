import type {
    ConformanceReportResponse,
    OnboardingResultResponse,
    RepoScaffoldResponse,
} from '@/models';

/** A 422 gate rejection, surfaced verbatim from the backend's error body. */
export interface OnboardRejection {
    detail: string;
    new_failures: string[];
    report: ConformanceReportResponse | null;
}

export interface OnboardState {
    // App form.
    appName: string;
    displayName: string;
    description: string;
    icon: string;
    exposeMcp: boolean;
    /** The app's repository under the fleet org; empty means it is named for
     * the app, which is the same string for most apps. */
    repo: string;
    /** Comma-separated released-image components (e.g. "server, client, docs");
     * empty means the single-image shape. */
    imageComponents: string;
    // Database form.
    databaseApp: string;
    // Identity form.
    identityApp: string;
    eventsApp: string;
    /** Comma-separated REF-Events domains the app owns; at least one is required. */
    eventsDomains: string;
    // Offboard form (the inverse act: prunes the namespace, frees the name once grants drop).
    offboardApp: string;
    // Reconcile form (the day-2 repair: re-render against a fresh declaration).
    reconcileApp: string;
    /** Comma-separated fresh released-image declaration; empty keeps the
     * single-image shape. */
    reconcileComponents: string;
    reconcileDescription: string;
    // Reconcile-identity form (re-render a granted realm against the install's declaration).
    reconcileIdentityApp: string;
    // Create-repo form (a repo born carrying the whole app contract).
    repoName: string;
    repoDisplayName: string;
    repoDescription: string;
    /** The created repository, its own outcome shape (no gate runs here). */
    repoResult: RepoScaffoldResponse | null;
    // Submission lifecycle (one onboarding runs at a time).
    submitting: boolean;
    /** Client-side validation or a 4xx detail; not a gate rejection. */
    error: string | null;
    result: OnboardingResultResponse | null;
    rejection: OnboardRejection | null;
}
