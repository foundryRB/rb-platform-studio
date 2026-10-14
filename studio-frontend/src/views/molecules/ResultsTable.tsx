import type { TestResultResponse } from '@/models';
import { OutcomeBadge } from '@/views/atoms/OutcomeBadge';

export interface ResultsTableProps {
    results: TestResultResponse[];
}

export const ResultsTable = ({ results }: ResultsTableProps) => (
    <table className="w-full border-collapse text-sm">
        <thead>
            <tr className="border-b text-left text-xs uppercase tracking-wider text-muted-foreground">
                <th className="px-2 py-1.5 font-medium">Test</th>
                <th className="w-24 px-2 py-1.5 font-medium">Outcome</th>
            </tr>
        </thead>
        <tbody>
            {results.map((result) => (
                <tr key={result.node_id} className="border-b border-border/60">
                    <td className="px-2 py-1.5 font-mono text-xs">{result.node_id}</td>
                    <td className="px-2 py-1.5">
                        <OutcomeBadge outcome={result.outcome} />
                    </td>
                </tr>
            ))}
        </tbody>
    </table>
);
