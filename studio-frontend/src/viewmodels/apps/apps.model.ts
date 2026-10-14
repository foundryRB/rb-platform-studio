import type { AppResponse } from '@/models';

import type { AppsState } from './apps.state';

/** The human-facing name: the manifest's display name, or the registry name bare. */
export const displayName = (app: AppResponse): string => app.manifest?.display_name ?? app.name;

/** Apps eligible for a database grant: onboarded (manifest exists) and not yet granted one. */
export const selectDatabaseCandidates = (state: AppsState): AppResponse[] =>
    state.apps.filter((app) => app.manifest !== null && !app.manifest.has_database);

/** Apps eligible for an identity (Keycloak realm) grant: onboarded and not yet granted one. */
export const selectIdentityCandidates = (state: AppsState): AppResponse[] =>
    state.apps.filter((app) => app.manifest !== null && !app.manifest.has_identity);

/** Apps whose realm can be re-rendered: onboarded and already holding one. */
export const selectIdentityHolders = (state: AppsState): AppResponse[] =>
    state.apps.filter((app) => app.manifest !== null && app.manifest.has_identity);

/** Apps eligible for an event-bus grant: onboarded and not yet granted one. */
export const selectEventsCandidates = (state: AppsState): AppResponse[] =>
    state.apps.filter((app) => app.manifest !== null && !app.manifest.has_events);

/** Apps the day-2 verbs act on: every onboarded app (manifest exists). */
export const selectOnboarded = (state: AppsState): AppResponse[] =>
    state.apps.filter((app) => app.manifest !== null);

/** Desired-state status: an app is paused when the platform has scaled it to zero. */
export const isPaused = (app: AppResponse): boolean => app.status === 'paused';

/**
 * How the app takes new versions, orthogonal to whether it runs:
 * `auto` (Image Updater promotes each release on its own), `manual` (frozen on
 * its current version), `none` (no bindings, so nothing promotes it), or
 * `unknown` (not onboarded).
 */
export const isPromotionFrozen = (app: AppResponse): boolean => app.promotion === 'manual';

/** Whether the freeze toggle applies at all: an app with no bindings has nothing to hold. */
export const canTogglePromotion = (app: AppResponse): boolean =>
    app.promotion === 'auto' || app.promotion === 'manual';
