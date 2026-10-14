import { useEffect } from 'react';

import { useApps } from '@/viewmodels/apps';
import { useNav } from '@/viewmodels/nav';
import { Spinner } from '@/views/atoms/Spinner';
import { AppCard } from '@/views/molecules/AppCard';

export const AppsPage = () => {
    const apps = useApps((state) => state.apps);
    const loading = useApps((state) => state.loading);
    const error = useApps((state) => state.error);
    const load = useApps((state) => state.load);
    const select = useApps((state) => state.select);
    const setPaused = useApps((state) => state.setPaused);
    const pausing = useApps((state) => state.pausing);
    const setView = useNav((state) => state.setView);

    useEffect(() => {
        void load();
    }, [load]);

    const open = (name: string) => {
        void select(name);
        setView('app');
    };

    return (
        <div className="mx-auto flex max-w-5xl flex-col gap-4">
            <div>
                <h2 className="text-lg font-bold tracking-tight">App registry</h2>
                <p className="mt-0.5 text-xs text-muted-foreground">
                    Every app the platform knows, joined with its team-manifest facts.
                </p>
            </div>

            {error && <p className="text-sm text-destructive">{error}</p>}
            {loading && apps.length === 0 && <Spinner />}

            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {apps.map((app) => (
                    <AppCard
                        key={app.name}
                        app={app}
                        onOpen={open}
                        onTogglePaused={setPaused}
                        pausing={pausing.includes(app.name)}
                    />
                ))}
            </div>

            {!loading && !error && apps.length === 0 && (
                <p className="text-sm text-muted-foreground">The registry is empty.</p>
            )}
        </div>
    );
};
