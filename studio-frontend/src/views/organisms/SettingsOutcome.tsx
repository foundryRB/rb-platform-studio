import { useSettings } from '@/viewmodels/settings';
import { GateComparison } from '@/views/molecules/GateComparison';
import { RawOutput } from '@/views/molecules/RawOutput';

/** The write lifecycle: a plain error, a gate rejection, or the pull request that landed. */
export const SettingsOutcome = () => {
    const error = useSettings((state) => state.error);
    const result = useSettings((state) => state.result);
    const rejection = useSettings((state) => state.rejection);

    return (
        <div className="flex flex-col gap-3">
            {error && (
                <div className="rounded-lg border border-rose-500/40 bg-rose-500/10 p-3 text-sm text-rose-900 dark:text-rose-200">
                    {error}
                </div>
            )}

            {rejection && (
                <div className="flex flex-col gap-3 rounded-lg border border-rose-500/40 bg-rose-500/10 p-4">
                    <div>
                        <p className="text-sm font-semibold text-rose-900 dark:text-rose-200">
                            The gates rejected this change; it was rolled back.
                        </p>
                        <p className="mt-1 text-xs text-rose-900/80 dark:text-rose-200/80">
                            {rejection.detail}
                        </p>
                    </div>
                    <div>
                        <p className="text-xs font-semibold uppercase tracking-wider text-rose-900/80 dark:text-rose-200/80">
                            New failures
                        </p>
                        <ul className="mt-1 flex flex-col gap-0.5">
                            {rejection.new_failures.map((failure) => (
                                <li
                                    key={failure}
                                    className="font-mono text-xs text-rose-900 dark:text-rose-200"
                                >
                                    {failure}
                                </li>
                            ))}
                        </ul>
                    </div>
                    {rejection.report && (
                        <RawOutput output={rejection.report.output} label="Conformance output" />
                    )}
                </div>
            )}

            {result && (
                <div className="flex flex-col gap-4 rounded-lg border border-emerald-500/40 bg-emerald-500/10 p-4">
                    <div>
                        <p className="text-sm font-semibold text-emerald-900 dark:text-emerald-200">
                            The change passed the gates.
                        </p>
                        <p className="mt-1 text-xs text-emerald-900/80 dark:text-emerald-200/80">
                            {result.pr ? (
                                <>
                                    Shipped as{' '}
                                    <a
                                        href={result.pr.url}
                                        target="_blank"
                                        rel="noreferrer"
                                        className="font-medium underline"
                                    >
                                        PR #{result.pr.number}: {result.pr.title}
                                    </a>
                                    . The value above still reads as the branch has it today. It
                                    takes effect after the platform repo&apos;s CI merges this PR
                                    and ArgoCD syncs, provided the installed chart supports the
                                    setting.
                                    {result.app === 'arc.max-runners' && (
                                        <>
                                            {' '}
                                            For the runner ceiling, first pin a platform chart
                                            release that reads arc.maxRunners.
                                        </>
                                    )}{' '}
                                    This PR does not move the chart pin.
                                </>
                            ) : (
                                <>
                                    Left in the working tree - local run. Commit it to the deploy
                                    branch yourself.
                                </>
                            )}
                        </p>
                    </div>

                    <div>
                        <p className="text-xs font-semibold uppercase tracking-wider text-emerald-900/80 dark:text-emerald-200/80">
                            Changed files
                        </p>
                        <ul className="mt-1 flex flex-col gap-0.5">
                            {result.changed_files.map((file) => (
                                <li
                                    key={file}
                                    className="font-mono text-xs text-emerald-900 dark:text-emerald-200"
                                >
                                    {file}
                                </li>
                            ))}
                        </ul>
                    </div>

                    <div>
                        <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-emerald-900/80 dark:text-emerald-200/80">
                            Gates: baseline vs branch
                        </p>
                        <GateComparison baseline={result.baseline} report={result.report} />
                    </div>
                </div>
            )}
        </div>
    );
};
