import type { ConformanceReportResponse } from '@/models';
import { cn } from '@/utils';

export interface SummaryChipsProps {
    report: ConformanceReportResponse;
}

const chip = (label: string, value: number, tone: string) => (
    <span
        className={cn(
            'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium',
            tone,
        )}
    >
        <span className="font-semibold">{value}</span> {label}
    </span>
);

export const SummaryChips = ({ report }: SummaryChipsProps) => (
    <div className="flex flex-wrap items-center gap-2">
        <span
            className={cn(
                'inline-flex rounded-full border px-2.5 py-0.5 text-xs font-semibold',
                report.ok
                    ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300'
                    : 'border-rose-500/40 bg-rose-500/10 text-rose-700 dark:text-rose-300',
            )}
        >
            {report.ok ? 'OK' : 'FAILING'}
        </span>
        {chip(
            'passed',
            report.passed,
            'border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300',
        )}
        {chip(
            'failed',
            report.failed,
            'border-rose-500/40 bg-rose-500/10 text-rose-700 dark:text-rose-300',
        )}
        {chip(
            'skipped',
            report.skipped,
            'border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-300',
        )}
        {chip(
            'errors',
            report.errors,
            'border-orange-500/40 bg-orange-500/10 text-orange-700 dark:text-orange-300',
        )}
    </div>
);
