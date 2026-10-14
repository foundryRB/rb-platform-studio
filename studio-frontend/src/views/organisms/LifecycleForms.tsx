import { useEffect } from 'react';

import { Button } from '@/components/ui/button';
import { selectIdentityHolders, selectOnboarded, useApps } from '@/viewmodels/apps';
import { useOnboard } from '@/viewmodels/onboard';

const FIELD_CLASSES =
    'w-full rounded-md border border-input bg-background/70 px-3 py-1.5 text-sm outline-none focus:ring-1 focus:ring-ring';

/** Reconcile: the day-2 repair verb - re-render teams/<app> against a fresh declaration. */
export const ReconcileAppForm = () => {
    const candidates = useApps(selectOnboarded);
    const loadApps = useApps((state) => state.load);
    const reconcileApp = useOnboard((state) => state.reconcileApp);
    const reconcileComponents = useOnboard((state) => state.reconcileComponents);
    const reconcileDescription = useOnboard((state) => state.reconcileDescription);
    const submitting = useOnboard((state) => state.submitting);
    const setField = useOnboard((state) => state.setField);
    const submitReconcile = useOnboard((state) => state.submitReconcile);

    useEffect(() => {
        void loadApps();
    }, [loadApps]);

    return (
        <div className="flex flex-col gap-4">
            <div>
                <h2 className="text-lg font-bold tracking-tight">Reconcile an app</h2>
                <p className="mt-0.5 text-xs text-muted-foreground">
                    Re-renders the app&apos;s five skeleton files from the current canonical
                    templates and a fresh released-image declaration. Grant files survive.
                    Reconcile first, then merge the app-side compose change.
                </p>
            </div>

            <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
                App
                <select
                    className={FIELD_CLASSES}
                    value={reconcileApp}
                    onChange={(e) => setField('reconcileApp', e.target.value)}
                >
                    <option value="">Pick an app...</option>
                    {candidates.map((app) => (
                        <option key={app.name} value={app.name}>
                            {app.manifest?.display_name ?? app.name} ({app.name})
                        </option>
                    ))}
                </select>
            </label>

            <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
                Released images (comma-separated; empty = single-image shape)
                <input
                    className={FIELD_CLASSES}
                    placeholder="server, client, docs"
                    value={reconcileComponents}
                    onChange={(e) => setField('reconcileComponents', e.target.value)}
                />
            </label>

            <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
                Description (empty keeps the current one)
                <input
                    className={FIELD_CLASSES}
                    value={reconcileDescription}
                    onChange={(e) => setField('reconcileDescription', e.target.value)}
                />
            </label>

            <div>
                <Button
                    disabled={submitting || reconcileApp === ''}
                    onClick={() => void submitReconcile()}
                >
                    {submitting ? 'Running the gates...' : 'Reconcile (runs gates)'}
                </Button>
            </div>
        </div>
    );
};

/** Reconcile identity: re-render a granted realm against the install's current declaration. */
export const ReconcileIdentityForm = () => {
    const candidates = useApps(selectIdentityHolders);
    const loadApps = useApps((state) => state.load);
    const reconcileIdentityApp = useOnboard((state) => state.reconcileIdentityApp);
    const submitting = useOnboard((state) => state.submitting);
    const setField = useOnboard((state) => state.setField);
    const submitReconcileIdentity = useOnboard((state) => state.submitReconcileIdentity);

    useEffect(() => {
        void loadApps();
    }, [loadApps]);

    return (
        <div className="flex flex-col gap-4">
            <div>
                <h2 className="text-lg font-bold tracking-tight">Reconcile a realm</h2>
                <p className="mt-0.5 text-xs text-muted-foreground">
                    Re-renders an app&apos;s Keycloak realm from the current template and the
                    install&apos;s current default brokers and login theme. Admitted users are
                    carried across and the app&apos;s credential is untouched; a realm already
                    current is refused, so nothing empty ships. Only apps with a realm are listed.
                </p>
            </div>

            <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
                App
                <select
                    className={FIELD_CLASSES}
                    value={reconcileIdentityApp}
                    onChange={(e) => setField('reconcileIdentityApp', e.target.value)}
                >
                    <option value="">Pick an app...</option>
                    {candidates.map((app) => (
                        <option key={app.name} value={app.name}>
                            {app.manifest?.display_name ?? app.name} ({app.name})
                        </option>
                    ))}
                </select>
            </label>

            <p className="text-xs text-muted-foreground">
                The pull request says what changed and names the callback to register for any broker
                the realm did not carry before.
            </p>

            <div>
                <Button
                    disabled={submitting || reconcileIdentityApp === ''}
                    onClick={() => void submitReconcileIdentity()}
                >
                    {submitting ? 'Running the gates...' : 'Reconcile realm (runs gates)'}
                </Button>
            </div>
        </div>
    );
};

/** Offboard: the inverse act - prunes the namespace; frees the name once its grants drop. */
export const OffboardAppForm = () => {
    const candidates = useApps(selectOnboarded);
    const loadApps = useApps((state) => state.load);
    const offboardApp = useOnboard((state) => state.offboardApp);
    const submitting = useOnboard((state) => state.submitting);
    const setField = useOnboard((state) => state.setField);
    const submitOffboard = useOnboard((state) => state.submitOffboard);

    useEffect(() => {
        void loadApps();
    }, [loadApps]);

    return (
        <div className="flex flex-col gap-4">
            <div>
                <h2 className="text-lg font-bold tracking-tight">Offboard an app</h2>
                <p className="mt-0.5 text-xs text-muted-foreground">
                    Removes the manifest entry and the whole teams folder in one gated PR, freeing
                    the hostname, and the name once any granted database and realm are dropped. Not
                    reversible (pause is). The PR merges as it opens, and the prune deletes every
                    volume the app's chart claims, its data too on a Delete reclaim policy: copy
                    those out first. A granted database or realm keeps its data; the PR enumerates
                    the disposition decision.
                </p>
            </div>

            <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
                App
                <select
                    className={FIELD_CLASSES}
                    value={offboardApp}
                    onChange={(e) => setField('offboardApp', e.target.value)}
                >
                    <option value="">Pick an app...</option>
                    {candidates.map((app) => (
                        <option key={app.name} value={app.name}>
                            {app.manifest?.display_name ?? app.name} ({app.name})
                        </option>
                    ))}
                </select>
            </label>

            <div>
                <Button
                    variant="destructive"
                    disabled={submitting || offboardApp === ''}
                    onClick={() => void submitOffboard()}
                >
                    {submitting ? 'Running the gates...' : 'Offboard (runs gates)'}
                </Button>
            </div>
        </div>
    );
};

/** Create repo: a repository born carrying the whole REF-Foundry app contract. */
export const CreateAppRepoForm = () => {
    const repoName = useOnboard((state) => state.repoName);
    const repoDisplayName = useOnboard((state) => state.repoDisplayName);
    const repoDescription = useOnboard((state) => state.repoDescription);
    const repoResult = useOnboard((state) => state.repoResult);
    const submitting = useOnboard((state) => state.submitting);
    const setField = useOnboard((state) => state.setField);
    const submitCreateRepo = useOnboard((state) => state.submitCreateRepo);

    return (
        <div className="flex flex-col gap-4">
            <div>
                <h2 className="text-lg font-bold tracking-tight">Create an app repo</h2>
                <p className="mt-0.5 text-xs text-muted-foreground">
                    Creates the org repository pre-templated with the full app contract
                    (walking skeleton): green CI from the first push, releasing the app and
                    docs images. Onboard it after the first push, declaring the returned
                    components.
                </p>
            </div>

            <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
                Name (the fleet name: repo, chart, packages, later the hostname)
                <input
                    className={FIELD_CLASSES}
                    placeholder="my-app"
                    value={repoName}
                    onChange={(e) => setField('repoName', e.target.value)}
                />
            </label>

            <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
                Display name
                <input
                    className={FIELD_CLASSES}
                    value={repoDisplayName}
                    onChange={(e) => setField('repoDisplayName', e.target.value)}
                />
            </label>

            <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
                Description
                <input
                    className={FIELD_CLASSES}
                    value={repoDescription}
                    onChange={(e) => setField('repoDescription', e.target.value)}
                />
            </label>

            <div>
                <Button
                    disabled={
                        submitting ||
                        repoName.trim() === '' ||
                        repoDisplayName.trim() === '' ||
                        repoDescription.trim() === ''
                    }
                    onClick={() => void submitCreateRepo()}
                >
                    {submitting ? 'Creating...' : 'Create templated repo'}
                </Button>
            </div>

            {repoResult && (
                <div className="rounded-md border border-input bg-background/70 p-3 text-xs">
                    <p className="font-medium">
                        Created{' '}
                        <a
                            className="underline"
                            href={repoResult.repo_url}
                            target="_blank"
                            rel="noreferrer"
                        >
                            {repoResult.repo_url}
                        </a>
                    </p>
                    <p className="mt-1 text-muted-foreground">
                        {repoResult.files.length} files on {repoResult.branch}
                        {repoResult.deploy_branch !== '' &&
                            `, ${repoResult.deploy_branch} stood up`}
                        . Onboard with image_components: [
                        {repoResult.image_components.join(', ')}].
                    </p>
                </div>
            )}
        </div>
    );
};
