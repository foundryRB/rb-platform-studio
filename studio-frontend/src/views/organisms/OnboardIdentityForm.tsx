import { useEffect } from 'react';

import { Button } from '@/components/ui/button';
import { selectIdentityCandidates, useApps } from '@/viewmodels/apps';
import { useOnboard } from '@/viewmodels/onboard';

const FIELD_CLASSES =
    'w-full rounded-md border border-input bg-background/70 px-3 py-1.5 text-sm outline-none focus:ring-1 focus:ring-ring';

export const OnboardIdentityForm = () => {
    const candidates = useApps(selectIdentityCandidates);
    const loadApps = useApps((state) => state.load);
    const identityApp = useOnboard((state) => state.identityApp);
    const submitting = useOnboard((state) => state.submitting);
    const setField = useOnboard((state) => state.setField);
    const submitIdentity = useOnboard((state) => state.submitIdentity);

    useEffect(() => {
        void loadApps();
    }, [loadApps]);

    return (
        <div className="flex flex-col gap-4">
            <div>
                <h2 className="text-lg font-bold tracking-tight">Grant a realm</h2>
                <p className="mt-0.5 text-xs text-muted-foreground">
                    Gives an onboarded app its own Keycloak realm with the identity providers
                    declared by this install. Only apps without one are listed.
                </p>
            </div>

            <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
                App
                <select
                    className={FIELD_CLASSES}
                    value={identityApp}
                    onChange={(e) => setField('identityApp', e.target.value)}
                >
                    <option value="">Pick an app...</option>
                    {candidates.map((app) => (
                        <option key={app.name} value={app.name}>
                            {app.manifest?.display_name ?? app.name} ({app.name})
                        </option>
                    ))}
                </select>
            </label>

            {candidates.length === 0 && (
                <p className="text-xs text-muted-foreground">
                    Every onboarded app already has a realm.
                </p>
            )}

            <p className="text-xs text-muted-foreground">
                The pull request lists each declared provider&rsquo;s callback URL to register
                in its upstream OAuth application.
            </p>

            <div>
                <Button
                    disabled={submitting || identityApp === ''}
                    onClick={() => void submitIdentity()}
                >
                    {submitting ? 'Running the gates...' : 'Grant realm (runs gates)'}
                </Button>
            </div>
        </div>
    );
};
