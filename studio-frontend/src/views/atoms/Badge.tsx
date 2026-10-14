import type { ReactNode } from 'react';

import { cn } from '@/utils';

export interface BadgeProps {
    children: ReactNode;
    className?: string;
}

export const Badge = ({ children, className }: BadgeProps) => (
    <span
        className={cn(
            'inline-flex items-center gap-1 rounded-full border border-border bg-secondary px-2 py-0.5',
            'text-xs font-medium text-secondary-foreground',
            className,
        )}
    >
        {children}
    </span>
);
