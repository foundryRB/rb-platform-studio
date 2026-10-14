import type { ButtonHTMLAttributes } from 'react';

import { cn } from '@/utils';

export type ButtonVariant = 'default' | 'outline' | 'ghost' | 'destructive';

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
    variant?: ButtonVariant;
}

const VARIANT_CLASSES: Record<ButtonVariant, string> = {
    default: 'bg-primary text-primary-foreground hover:bg-primary/85',
    outline: 'border border-input bg-transparent hover:bg-secondary',
    ghost: 'hover:bg-secondary',
    destructive: 'bg-destructive text-destructive-foreground hover:bg-destructive/85',
};

export const Button = ({ className, variant = 'default', ...props }: ButtonProps) => (
    <button
        className={cn(
            'inline-flex items-center justify-center rounded-md px-3 py-1.5 text-sm font-medium',
            'transition-colors disabled:pointer-events-none disabled:opacity-50',
            VARIANT_CLASSES[variant],
            className,
        )}
        {...props}
    />
);
