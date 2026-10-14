import { useEffect } from 'react';

import { byCategory, useSettings } from '@/viewmodels/settings';
import { Spinner } from '@/views/atoms/Spinner';
import { SettingRow } from '@/views/molecules/SettingRow';
import { SettingsOutcome } from '@/views/organisms/SettingsOutcome';

export const SettingsPage = () => {
    const settings = useSettings((state) => state.settings);
    const loading = useSettings((state) => state.loading);
    const load = useSettings((state) => state.load);

    useEffect(() => {
        void load();
    }, [load]);

    return (
        <div className="mx-auto flex max-w-3xl flex-col gap-4">
            <div>
                <h2 className="text-lg font-bold tracking-tight">Platform settings</h2>
                <p className="mt-0.5 text-xs text-muted-foreground">
                    The platform-level knobs this install tunes, read from its values on the deploy
                    branch. A change runs the conformance suite and ships as a pull request the
                    platform repo&apos;s CI merges - never a direct commit, and never a chart pin
                    bump. Anything not listed here stays an engineer edit to the repo.
                </p>
            </div>

            <SettingsOutcome />

            {loading && settings.length === 0 && (
                <div className="flex items-center gap-3 text-sm text-muted-foreground">
                    <Spinner />
                    Reading the deploy branch...
                </div>
            )}

            {byCategory(settings).map(([category, knobs]) => (
                <section key={category} className="flex flex-col gap-2">
                    <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                        {category}
                    </h3>
                    {knobs.map((setting) => (
                        <SettingRow key={setting.key} setting={setting} />
                    ))}
                </section>
            ))}

            {!loading && settings.length === 0 && (
                <p className="text-sm text-muted-foreground">
                    No curated settings. The registry is fixed in the backend
                    (`domain/services/platform_settings.py`); a knob appears here once it is added
                    there and bound to a chart value.
                </p>
            )}
        </div>
    );
};
