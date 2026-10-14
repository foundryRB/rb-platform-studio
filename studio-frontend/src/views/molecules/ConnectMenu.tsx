import { useEffect, useState } from 'react';

import { usePrs } from '@/viewmodels/prs';
import { ConnectAgent } from '@/views/molecules/ConnectAgent';

/**
 * Header entry point for the MCP door: visible on the deployed studio so the
 * connect one-liner is one click away, not buried in the docs. The PR surface
 * doubles as the deployed signal (the local composition 404s it).
 */
export const ConnectMenu = () => {
    const unavailable = usePrs((state) => state.unavailable);
    const load = usePrs((state) => state.load);
    const [open, setOpen] = useState(false);

    useEffect(() => {
        void load();
    }, [load]);

    if (unavailable) return null;

    return (
        <div className="relative">
            <button
                onClick={() => setOpen((value) => !value)}
                title="Connect an MCP agent to this studio"
                className="rounded-md border border-link/60 px-2 py-1 text-xs font-medium text-foreground hover:bg-secondary"
            >
                {open ? 'Close' : 'Connect agent'}
            </button>
            {open && (
                <div className="absolute right-0 top-9 z-20 w-96 rounded-lg border bg-card p-3 shadow-lg">
                    <p className="mb-2 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground/70">
                        MCP
                    </p>
                    <ConnectAgent />
                </div>
            )}
        </div>
    );
};
