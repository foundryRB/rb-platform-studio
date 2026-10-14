import { Button } from '@/components/ui/button';
import type { PlatformSettingResponse } from '@/models';
import { draftFor, draftProblem, isDirty, useSettings } from '@/viewmodels/settings';
import { Badge } from '@/views/atoms/Badge';
import { Spinner } from '@/views/atoms/Spinner';

const FIELD_CLASSES =
    'w-36 rounded-md border border-input bg-background/70 px-3 py-1.5 font-mono text-sm outline-none focus:ring-1 focus:ring-ring';

export interface SettingRowProps {
    setting: PlatformSettingResponse;
}

/** One curated knob: what is in force, where it lives, and the write that tunes it. */
export const SettingRow = ({ setting }: SettingRowProps) => {
    const drafts = useSettings((state) => state.drafts);
    const submitting = useSettings((state) => state.submitting);
    const setDraft = useSettings((state) => state.setDraft);
    const resetDraft = useSettings((state) => state.resetDraft);
    const submit = useSettings((state) => state.submit);

    const value = draftFor(setting, drafts);
    const dirty = isDirty(setting, drafts);
    const problem = dirty ? draftProblem(setting, drafts) : null;
    const busy = submitting === setting.key;
    const blocked = submitting !== null && !busy;
    // Distinct from `dirty`: an unpinned knob is dirty untouched (submitting it
    // pins the default), but there is nothing to reset until something is typed.
    const edited = drafts[setting.key] !== undefined;

    return (
        <div className="flex flex-col gap-2 rounded-lg border bg-card p-4">
            <div className="flex flex-wrap items-center gap-2">
                <h3 className="text-sm font-semibold">{setting.label}</h3>
                {setting.value === null ? (
                    <Badge className="text-muted-foreground">chart default</Badge>
                ) : (
                    <Badge>pinned by this install</Badge>
                )}
            </div>

            <p className="text-xs text-muted-foreground">{setting.description}</p>

            <div className="flex flex-wrap items-center gap-2">
                <input
                    className={FIELD_CLASSES}
                    value={value}
                    aria-label={setting.label}
                    disabled={busy}
                    onChange={(e) => setDraft(setting.key, e.target.value)}
                />
                <Button
                    disabled={!dirty || problem !== null || busy || blocked}
                    onClick={() => void submit(setting.key)}
                >
                    {busy ? 'Running the gates...' : 'Propose change'}
                </Button>
                {edited && !busy && (
                    <button
                        onClick={() => resetDraft(setting.key)}
                        className="text-xs text-muted-foreground underline hover:text-foreground"
                    >
                        Reset
                    </button>
                )}
                {busy && <Spinner />}
            </div>

            {problem && <p className="text-xs text-destructive">{problem}</p>}

            <p className="text-xs text-muted-foreground">
                <span className="font-mono">{setting.field}</span> in{' '}
                <span className="font-mono">{setting.source}</span> on the deploy branch
                {setting.value === null && (
                    <>
                        {' '}
                        &middot; unset here, so the chart&apos;s{' '}
                        <span className="font-mono">{setting.default}</span> is in force
                    </>
                )}
            </p>
        </div>
    );
};
