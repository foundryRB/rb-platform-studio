import { cn } from '@/utils';

export interface SpinnerProps {
    className?: string;
}

export const Spinner = ({ className }: SpinnerProps) => (
    <div
        role="status"
        aria-label="loading"
        className={cn(
            'size-4 animate-spin rounded-full border-2 border-muted border-t-foreground',
            className,
        )}
    />
);
