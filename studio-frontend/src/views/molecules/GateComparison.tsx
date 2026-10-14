import type { ConformanceReportResponse } from '@/models';
import { cn } from '@/utils';

export interface GateComparisonProps {
    baseline: ConformanceReportResponse;
    report: ConformanceReportResponse;
}

const ROWS: { label: string; key: 'passed' | 'failed' | 'skipped' }[] = [
    { label: 'Passed', key: 'passed' },
    { label: 'Failed', key: 'failed' },
    { label: 'Skipped', key: 'skipped' },
];

/** Baseline (before the change) vs branch (after) gate counts, side by side. */
export const GateComparison = ({ baseline, report }: GateComparisonProps) => (
    <table className="w-full max-w-sm border-collapse text-sm">
        <thead>
            <tr className="border-b text-left text-xs uppercase tracking-wider text-muted-foreground">
                <th className="px-2 py-1.5 font-medium">Gate</th>
                <th className="px-2 py-1.5 font-medium">Baseline</th>
                <th className="px-2 py-1.5 font-medium">Branch</th>
            </tr>
        </thead>
        <tbody>
            {ROWS.map(({ label, key }) => (
                <tr key={key} className="border-b border-border/60">
                    <td className="px-2 py-1.5 text-muted-foreground">{label}</td>
                    <td className="px-2 py-1.5 font-mono">{baseline[key]}</td>
                    <td
                        className={cn(
                            'px-2 py-1.5 font-mono',
                            key === 'failed' &&
                                report.failed > baseline.failed &&
                                'font-semibold text-destructive',
                        )}
                    >
                        {report[key]}
                    </td>
                </tr>
            ))}
        </tbody>
    </table>
);
