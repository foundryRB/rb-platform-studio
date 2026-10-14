import { type ClassValue, clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

/** Merge Tailwind class names, resolving conflicts. */
export function cn(...inputs: ClassValue[]): string {
    return twMerge(clsx(inputs));
}

/** Fetch JSON from the API, throwing an Error with the server-provided detail on failure. */
export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await fetch(path, {
        headers: { 'Content-Type': 'application/json' },
        ...init,
    });
    if (!response.ok) {
        let detail = `${response.status} ${response.statusText}`;
        try {
            const body = (await response.json()) as { detail?: string; error?: string };
            detail = body.detail ?? body.error ?? detail;
        } catch {
            // Non-JSON error body; keep the status text.
        }
        throw new Error(detail);
    }
    return (await response.json()) as T;
}
