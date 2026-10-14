import type { MouseEvent } from 'react';

import { cn } from '@/utils';
import type { AppResponse } from '@/models';
import { displayName } from '@/viewmodels/apps';
import { AppIcon } from '@/views/atoms/AppIcon';
import { Badge } from '@/views/atoms/Badge';
import { PromotionBadge } from '@/views/atoms/PromotionBadge';
import { StatusBadge } from '@/views/atoms/StatusBadge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';

export interface AppCardProps {
    app: AppResponse;
    onOpen: (name: string) => void;
    onTogglePaused: (name: string, paused: boolean) => void;
    pausing: boolean;
}

/** Links inside the card must not also trigger the card's own navigation. */
const stop = (event: MouseEvent) => {
    event.stopPropagation();
};

export const AppCard = ({ app, onOpen, onTogglePaused, pausing }: AppCardProps) => {
    const paused = app.status === 'paused';
    return (
        <Card
            role="button"
            tabIndex={0}
            aria-label={`${displayName(app)} (${app.status})`}
            onClick={() => onOpen(app.name)}
            onKeyDown={(event) => {
                if (event.key === 'Enter') {
                    onOpen(app.name);
                }
            }}
            className={cn(
                'cursor-pointer p-4 transition-colors',
                paused
                    ? 'border-amber-500/60 bg-amber-500/[0.06] hover:border-amber-500/80'
                    : 'hover:border-link/50',
            )}
        >
            {/* Content fades and desaturates when paused; the frame (amber) and the action
                footer stay outside the fade so the tile reads paused at a glance yet stays usable. */}
            <div className={cn('transition-all duration-300', paused && 'opacity-50 grayscale')}>
                <div className="flex items-start justify-between gap-2">
                    <div>
                        <h3 className="text-sm font-semibold">{displayName(app)}</h3>
                        <p className="font-mono text-xs text-muted-foreground">{app.name}</p>
                    </div>
                    {app.manifest && (
                        <AppIcon icon={app.manifest.icon} className="text-foreground/70" />
                    )}
                </div>
                {app.manifest ? (
                    <div className="mt-3 flex flex-col gap-1.5 text-xs">
                        <a
                            href={`https://${app.manifest.hostname}`}
                            target="_blank"
                            rel="noreferrer"
                            onClick={stop}
                            className="w-fit text-link hover:underline"
                        >
                            {app.manifest.hostname}
                        </a>
                        <p className="line-clamp-2 text-muted-foreground">
                            {app.manifest.description}
                        </p>
                    </div>
                ) : (
                    <p className="mt-3 text-xs text-muted-foreground">
                        Registered, no team manifest yet.
                    </p>
                )}
                {(app.mcp_url ||
                    app.manifest?.has_database ||
                    app.manifest?.has_identity ||
                    app.manifest?.has_events) && (
                    <div className="mt-3 flex flex-wrap gap-1.5">
                        {app.mcp_url && (
                            <a href={app.mcp_url} target="_blank" rel="noreferrer" onClick={stop}>
                                <Badge className="border-link/40 bg-primary/10 text-link hover:bg-primary/20">
                                    MCP
                                </Badge>
                            </a>
                        )}
                        {app.manifest?.has_database && (
                            <Badge className="border-sky-500/40 bg-sky-500/10 text-sky-700 dark:text-sky-300">
                                database
                            </Badge>
                        )}
                        {app.manifest?.has_identity && (
                            <Badge className="border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300">
                                SSO
                            </Badge>
                        )}
                        {app.manifest?.has_events && (
                            <Badge className="border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-300">
                                events
                            </Badge>
                        )}
                    </div>
                )}
            </div>
            {app.manifest && (
                <div className="mt-3 flex items-center justify-between gap-2">
                    {/* Two independent facts: whether it runs, and whether it takes
                        new versions. The promotion toggle itself lives on the detail
                        page; the tile reports the stance. */}
                    <div className="flex flex-wrap items-center gap-1.5">
                        <StatusBadge status={app.status} />
                        <PromotionBadge promotion={app.promotion} />
                    </div>
                    <Button
                        variant="outline"
                        disabled={pausing}
                        onClick={(event) => {
                            stop(event);
                            onTogglePaused(app.name, !paused);
                        }}
                        className={cn(
                            'px-2 py-0.5 text-xs',
                            paused &&
                                'border-amber-500/50 text-amber-700 hover:bg-amber-500/10 dark:text-amber-300',
                        )}
                    >
                        {pausing ? 'Working...' : paused ? 'Resume' : 'Pause'}
                    </Button>
                </div>
            )}
        </Card>
    );
};
