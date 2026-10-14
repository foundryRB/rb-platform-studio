import { cn } from '@/utils';

export interface StatusBadgeProps {
    status: string;
}

const STATUS_CLASSES: Record<string, string> = {
    running: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300',
    paused: 'border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-300',
    unknown: 'border-border bg-secondary text-secondary-foreground',
};

/** The app's desired-state fleet status: running, paused, or (not onboarded) unknown. */
export const StatusBadge = ({ status }: StatusBadgeProps) => (
    <span
        className={cn(
            'inline-flex rounded-full border px-2 py-0.5 text-xs font-medium',
            STATUS_CLASSES[status] ?? STATUS_CLASSES.unknown,
        )}
    >
        {status}
    </span>
);
