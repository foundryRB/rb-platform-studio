import { cn } from '@/utils';

export interface PromotionBadgeProps {
    promotion: string;
    className?: string;
}

/**
 * How the app takes new versions, read off its Image Updater bindings.
 * Orthogonal to the running/paused status: an app can run and be frozen, or be
 * paused and still promoting.
 */
const PROMOTION: Record<string, { label: string; title: string; className: string }> = {
    auto: {
        label: 'auto deploy',
        title: 'Each released image promotes on its own; a push to main reaches prod with no hand.',
        className: 'border-border bg-secondary text-secondary-foreground',
    },
    manual: {
        label: 'manual deploy',
        title: 'Frozen: the app holds its current version until someone sets the tag by hand.',
        className: 'border-violet-500/40 bg-violet-500/10 text-violet-700 dark:text-violet-300',
    },
    none: {
        label: 'unbound',
        title: 'The Application declares no Image Updater bindings, so nothing promotes this app.',
        className: 'border-border bg-secondary text-muted-foreground',
    },
};

export const PromotionBadge = ({ promotion, className }: PromotionBadgeProps) => {
    const shape = PROMOTION[promotion];
    // Not onboarded (unknown): there is no promotion fact to show.
    if (!shape) return null;
    return (
        <span
            title={shape.title}
            className={cn(
                'inline-flex rounded-full border px-2 py-0.5 text-xs font-medium',
                shape.className,
                className,
            )}
        >
            {shape.label}
        </span>
    );
};
