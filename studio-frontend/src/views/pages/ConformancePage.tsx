import { Button } from '@/components/ui/button';
import { useConformance } from '@/viewmodels/conformance';
import { Spinner } from '@/views/atoms/Spinner';
import { RawOutput } from '@/views/molecules/RawOutput';
import { ResultsTable } from '@/views/molecules/ResultsTable';
import { SummaryChips } from '@/views/molecules/SummaryChips';

export const ConformancePage = () => {
    const report = useConformance((state) => state.report);
    const running = useConformance((state) => state.running);
    const error = useConformance((state) => state.error);
    const run = useConformance((state) => state.run);

    return (
        <div className="mx-auto flex max-w-3xl flex-col gap-4">
            <div>
                <h2 className="text-lg font-bold tracking-tight">Conformance</h2>
                <p className="mt-0.5 text-xs text-muted-foreground">
                    Runs the platform's conformance suite against the live checkout and reports
                    per-test outcomes.
                </p>
            </div>

            <div className="flex items-center gap-3">
                <Button disabled={running} onClick={() => void run()}>
                    {running ? 'Running...' : 'Run conformance'}
                </Button>
                {running && <Spinner />}
            </div>

            {error && <p className="text-sm text-destructive">{error}</p>}

            {report && (
                <>
                    <SummaryChips report={report} />
                    <ResultsTable results={report.results} />
                    <RawOutput output={report.output} />
                </>
            )}

            {!report && !running && !error && (
                <p className="text-sm text-muted-foreground">No run yet this session.</p>
            )}
        </div>
    );
};
