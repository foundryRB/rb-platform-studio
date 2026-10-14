export interface RawOutputProps {
    output: string;
    label?: string;
}

export const RawOutput = ({ output, label = 'Raw output' }: RawOutputProps) => (
    <details className="rounded-lg border bg-card">
        <summary className="cursor-pointer select-none px-3 py-2 text-xs font-medium text-muted-foreground hover:text-foreground">
            {label}
        </summary>
        <pre className="max-h-80 overflow-auto whitespace-pre-wrap border-t px-3 py-2 font-mono text-[11px]">
            {output}
        </pre>
    </details>
);
