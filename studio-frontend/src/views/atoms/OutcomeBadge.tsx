import { cn } from '@/utils';

export interface OutcomeBadgeProps {
    outcome: string;
}

const OUTCOME_CLASSES: Record<string, string> = {
    passed: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300',
    failed: 'border-rose-500/40 bg-rose-500/10 text-rose-700 dark:text-rose-300',
    skipped: 'border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-300',
    error: 'border-orange-500/40 bg-orange-500/10 text-orange-700 dark:text-orange-300',
};

export const OutcomeBadge = ({ outcome }: OutcomeBadgeProps) => (
    <span
        className={cn(
            'inline-flex rounded-full border px-2 py-0.5 text-xs font-medium',
            OUTCOME_CLASSES[outcome] ?? 'border-border bg-secondary text-secondary-foreground',
        )}
    >
        {outcome}
    </span>
);
