import { Button } from '@/components/ui/button';
import { canTogglePromotion, displayName, isPromotionFrozen, useApps } from '@/viewmodels/apps';
import { resultsForApp, useConformance } from '@/viewmodels/conformance';
import { useNav } from '@/viewmodels/nav';
import { AppIcon } from '@/views/atoms/AppIcon';
import { Badge } from '@/views/atoms/Badge';
import { PromotionBadge } from '@/views/atoms/PromotionBadge';
import { Spinner } from '@/views/atoms/Spinner';
import { StatusBadge } from '@/views/atoms/StatusBadge';
import { ResultsTable } from '@/views/molecules/ResultsTable';

const Fact = ({ label, children }: { label: string; children: React.ReactNode }) => (
    <div className="flex flex-col gap-0.5">
        <dt className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
            {label}
        </dt>
        <dd className="text-sm">{children}</dd>
    </div>
);

export const AppDetailPage = () => {
    const selected = useApps((state) => state.selected);
    const detail = useApps((state) => state.detail);
    const detailLoading = useApps((state) => state.detailLoading);
    const detailError = useApps((state) => state.detailError);
    const setPaused = useApps((state) => state.setPaused);
    const pausing = useApps((state) => state.pausing);
    const setPromotionFrozen = useApps((state) => state.setPromotionFrozen);
    const freezing = useApps((state) => state.freezing);
    const actionError = useApps((state) => state.error);
    const setView = useNav((state) => state.setView);
    const report = useConformance((state) => state.report);
    const running = useConformance((state) => state.running);
    const runError = useConformance((state) => state.error);
    const run = useConformance((state) => state.run);

    const rows = selected !== null ? resultsForApp(report, selected) : [];

    return (
        <div className="mx-auto flex max-w-3xl flex-col gap-4">
            <div className="flex items-center gap-3">
                <Button variant="outline" onClick={() => setView('apps')}>
                    Back
                </Button>
                <h2 className="text-lg font-bold tracking-tight">
                    {detail ? displayName(detail) : (selected ?? 'App')}
                </h2>
                {detail && (
                    <span className="font-mono text-xs text-muted-foreground">{detail.name}</span>
                )}
                {detail?.manifest && (
                    <div className="ml-auto flex flex-wrap items-center justify-end gap-2">
                        <StatusBadge status={detail.status} />
                        <Button
                            variant="outline"
                            disabled={pausing.includes(detail.name)}
                            onClick={() => void setPaused(detail.name, detail.status !== 'paused')}
                        >
                            {pausing.includes(detail.name)
                                ? 'Working...'
                                : detail.status === 'paused'
                                  ? 'Resume'
                                  : 'Pause'}
                        </Button>
                        <PromotionBadge promotion={detail.promotion} />
                        {canTogglePromotion(detail) && (
                            <Button
                                variant="outline"
                                disabled={freezing.includes(detail.name)}
                                onClick={() =>
                                    void setPromotionFrozen(detail.name, !isPromotionFrozen(detail))
                                }
                            >
                                {freezing.includes(detail.name)
                                    ? 'Working...'
                                    : isPromotionFrozen(detail)
                                      ? 'Resume promotion'
                                      : 'Freeze promotion'}
                            </Button>
                        )}
                    </div>
                )}
            </div>

            {detailError && <p className="text-sm text-destructive">{detailError}</p>}
            {actionError && <p className="text-sm text-destructive">{actionError}</p>}
            {detailLoading && <Spinner />}

            {detail && detail.manifest && (
                <dl className="grid grid-cols-1 gap-3 rounded-lg border bg-card p-4 sm:grid-cols-2">
                    <Fact label="Hostname">
                        <a
                            href={`https://${detail.manifest.hostname}`}
                            target="_blank"
                            rel="noreferrer"
                            className="text-link hover:underline"
                        >
                            {detail.manifest.hostname}
                        </a>
                    </Fact>
                    <Fact label="Repository">
                        <a
                            href={detail.manifest.repo_url}
                            target="_blank"
                            rel="noreferrer"
                            className="break-all text-link hover:underline"
                        >
                            {detail.manifest.repo_url}
                        </a>
                    </Fact>
                    <Fact label="Target revision">
                        <span className="font-mono">{detail.manifest.target_revision}</span>
                    </Fact>
                    <Fact label="Promotion">
                        <span className="flex flex-col gap-1">
                            <PromotionBadge promotion={detail.promotion} className="w-fit" />
                            <span className="text-xs text-muted-foreground">
                                {detail.promotion === 'manual'
                                    ? `Held on its current version: set the image tag in ${detail.manifest.target_revision}'s prod/values.yaml to ship a new one.`
                                    : detail.promotion === 'none'
                                      ? 'No Image Updater bindings, so no release reaches this app on its own.'
                                      : 'Each release promotes on its own into the deploy branch.'}
                            </span>
                        </span>
                    </Fact>
                    <Fact label="Database">
                        {detail.manifest.has_database ? (
                            <Badge className="border-sky-500/40 bg-sky-500/10 text-sky-700 dark:text-sky-300">
                                database
                            </Badge>
                        ) : (
                            <span className="text-muted-foreground">none</span>
                        )}
                    </Fact>
                    <Fact label="Events">
                        {detail.manifest.has_events ? (
                            <Badge className="border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-300">
                                events
                            </Badge>
                        ) : (
                            <span className="text-muted-foreground">none</span>
                        )}
                    </Fact>
                    {detail.mcp_url && (
                        <Fact label="MCP">
                            <a
                                href={detail.mcp_url}
                                target="_blank"
                                rel="noreferrer"
                                className="break-all text-link hover:underline"
                            >
                                {detail.mcp_url}
                            </a>
                        </Fact>
                    )}
                    <Fact label="Icon">
                        <span className="flex items-center gap-2">
                            <AppIcon
                                icon={detail.manifest.icon}
                                className="h-5 w-5 text-foreground"
                            />
                            <span className="font-mono text-xs text-muted-foreground">
                                {detail.manifest.icon}
                            </span>
                        </span>
                    </Fact>
                    <div className="sm:col-span-2">
                        <Fact label="Description">{detail.manifest.description}</Fact>
                    </div>
                </dl>
            )}

            {detail && !detail.manifest && (
                <p className="rounded-lg border bg-card p-4 text-sm text-muted-foreground">
                    This app is registered but carries no team manifest yet.
                </p>
            )}

            <div className="flex items-center gap-3">
                <h3 className="text-sm font-semibold">Conformance</h3>
                <Button variant="outline" disabled={running} onClick={() => void run()}>
                    {running ? 'Running...' : 'Run conformance'}
                </Button>
                {running && <Spinner />}
            </div>
            {runError && <p className="text-sm text-destructive">{runError}</p>}

            {report === null && !running && (
                <p className="text-sm text-muted-foreground">
                    No conformance run yet this session. Run one to see this app's rows.
                </p>
            )}
            {report !== null && rows.length === 0 && (
                <p className="text-sm text-muted-foreground">
                    The last run has no per-app rows for {selected}.
                </p>
            )}
            {rows.length > 0 && <ResultsTable results={rows} />}
        </div>
    );
};
