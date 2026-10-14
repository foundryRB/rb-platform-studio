import { useEffect } from 'react';

import { usePrs } from '@/viewmodels/prs';
import { Badge } from '@/views/atoms/Badge';
import { Spinner } from '@/views/atoms/Spinner';

export const PrsPage = () => {
    const prs = usePrs((state) => state.prs);
    const loading = usePrs((state) => state.loading);
    const error = usePrs((state) => state.error);
    const unavailable = usePrs((state) => state.unavailable);
    const load = usePrs((state) => state.load);

    useEffect(() => {
        void load();
    }, [load]);

    return (
        <div className="mx-auto flex max-w-3xl flex-col gap-4">
            <div>
                <h2 className="text-lg font-bold tracking-tight">Open pull requests</h2>
                <p className="mt-0.5 text-xs text-muted-foreground">
                    Every gate-passing change awaiting its automated merge — onboards,
                    offboards, reconciles, and settings writes. The branch names which.
                </p>
            </div>

            {loading && <Spinner />}
            {error && <p className="text-sm text-destructive">{error}</p>}

            {unavailable && (
                <p className="rounded-lg border bg-card p-4 text-sm text-muted-foreground">
                    PR surface not available in the local run — this composition works against the
                    working tree, so changes land there instead of as pull requests.
                </p>
            )}

            {!unavailable && !loading && !error && prs.length === 0 && (
                <p className="text-sm text-muted-foreground">No open pull requests.</p>
            )}

            {prs.length > 0 && (
                <table className="w-full border-collapse text-sm">
                    <thead>
                        <tr className="border-b text-left text-xs uppercase tracking-wider text-muted-foreground">
                            <th className="w-16 px-2 py-1.5 font-medium">#</th>
                            <th className="px-2 py-1.5 font-medium">Title</th>
                            <th className="px-2 py-1.5 font-medium">Branch</th>
                            <th className="w-24 px-2 py-1.5 font-medium">State</th>
                        </tr>
                    </thead>
                    <tbody>
                        {prs.map((pr) => (
                            <tr key={pr.number} className="border-b border-border/60">
                                <td className="px-2 py-1.5 font-mono text-xs">{pr.number}</td>
                                <td className="px-2 py-1.5">
                                    <a
                                        href={pr.url}
                                        target="_blank"
                                        rel="noreferrer"
                                        className="text-link hover:underline"
                                    >
                                        {pr.title}
                                    </a>
                                </td>
                                <td className="px-2 py-1.5 font-mono text-xs">{pr.branch}</td>
                                <td className="px-2 py-1.5">
                                    <Badge>{pr.state}</Badge>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            )}
        </div>
    );
};
