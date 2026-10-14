import { Spinner } from '@/views/atoms/Spinner';
import { GateComparison } from '@/views/molecules/GateComparison';
import { RawOutput } from '@/views/molecules/RawOutput';
import { useOnboard } from '@/viewmodels/onboard';

/** The submission lifecycle: pending state, success, gate rejection, or plain error. */
export const OnboardOutcome = () => {
    const submitting = useOnboard((state) => state.submitting);
    const error = useOnboard((state) => state.error);
    const result = useOnboard((state) => state.result);
    const rejection = useOnboard((state) => state.rejection);

    if (submitting) {
        return (
            <div className="flex items-center gap-3 rounded-lg border bg-card p-4 text-sm text-muted-foreground">
                <Spinner />
                Running the conformance suite twice (baseline, then the change) — this can take a
                minute.
            </div>
        );
    }

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
                            The gates rejected this onboarding; it was rolled back.
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
                            Onboarding for {result.app} passed the gates.
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
                                    </a>{' '}
                                    on branch <span className="font-mono">{result.branch}</span>.
                                </>
                            ) : (
                                <>Left in the working tree - local run.</>
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
