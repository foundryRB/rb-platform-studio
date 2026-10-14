import { useEffect } from 'react';

import { Button } from '@/components/ui/button';
import { selectEventsCandidates, useApps } from '@/viewmodels/apps';
import { useOnboard } from '@/viewmodels/onboard';

const FIELD_CLASSES =
    'w-full rounded-md border border-input bg-background/70 px-3 py-1.5 text-sm outline-none focus:ring-1 focus:ring-ring';

export const OnboardEventsForm = () => {
    const candidates = useApps(selectEventsCandidates);
    const loadApps = useApps((state) => state.load);
    const eventsApp = useOnboard((state) => state.eventsApp);
    const eventsDomains = useOnboard((state) => state.eventsDomains);
    const submitting = useOnboard((state) => state.submitting);
    const setField = useOnboard((state) => state.setField);
    const submitEvents = useOnboard((state) => state.submitEvents);

    useEffect(() => {
        void loadApps();
    }, [loadApps]);

    return (
        <div className="flex flex-col gap-4">
            <div>
                <h2 className="text-lg font-bold tracking-tight">Grant bus access</h2>
                <p className="mt-0.5 text-xs text-muted-foreground">
                    Gives an onboarded app a signed credential for the shared event bus. Only
                    apps not already on it are listed.
                </p>
            </div>

            <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
                App
                <select
                    className={FIELD_CLASSES}
                    value={eventsApp}
                    onChange={(e) => setField('eventsApp', e.target.value)}
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
                Domains it publishes under
                <input
                    className={FIELD_CLASSES}
                    value={eventsDomains}
                    placeholder="platform, delivery"
                    onChange={(e) => setField('eventsDomains', e.target.value)}
                />
            </label>

            {candidates.length === 0 && (
                <p className="text-xs text-muted-foreground">
                    Every onboarded app is already on the bus.
                </p>
            )}

            <p className="text-xs text-muted-foreground">
                The grant scopes what the app may <strong>say</strong>: it can publish only
                under the domains named here, and one domain has exactly one owner. Reading
                stays open across the whole event space.
            </p>

            <div>
                <Button
                    disabled={submitting || eventsApp === '' || eventsDomains.trim() === ''}
                    onClick={() => void submitEvents()}
                >
                    {submitting ? 'Running the gates...' : 'Grant bus access (runs gates)'}
                </Button>
            </div>
        </div>
    );
};
