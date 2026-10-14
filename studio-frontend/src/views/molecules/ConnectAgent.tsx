import { useEffect, useState } from 'react';

import { Button } from '@/components/ui/button';
import { apiFetch } from '@/utils';

/**
 * The MCP door, self-advertised: the copyable connect one-liner for this
 * instance, and the onboard-app prompt that carries the team-side runbook
 * (the client-executes idiom, ADR-006).
 *
 * The one-liner carries the site's HTTP Basic credential, fetched from
 * /api/agent-credential when the panel mounts (this component renders only once
 * the connect panel opens, never on a bare page load). That endpoint sits behind
 * the same gate as this SPA (oauth2-proxy under scope=mcp, Basic under
 * scope=all), so an already-authenticated human gets a paste-ready command; if
 * it is unavailable the one-liner falls back to a placeholder.
 */
export const ConnectAgent = () => {
    const [copied, setCopied] = useState<string | null>(null);
    const [credential, setCredential] = useState<string | null>(null);
    const [credFailed, setCredFailed] = useState(false);

    useEffect(() => {
        let cancelled = false;
        apiFetch<{ credential: string }>('/api/agent-credential')
            .then((r) => {
                if (!cancelled) setCredential(r.credential);
            })
            .catch(() => {
                if (!cancelled) setCredFailed(true);
            });
        return () => {
            cancelled = true;
        };
    }, []);

    const basic = credential ?? '<credentials>';
    const oneLiner = `claude mcp add --scope user --transport http platform-studio ${window.location.origin}/mcp --header "Authorization: Basic ${basic}"`;
    const ask = '/mcp__platform-studio__onboard-app <app>';

    const copy = (label: string, text: string) => {
        void navigator.clipboard.writeText(text).then(() => {
            setCopied(label);
            window.setTimeout(() => setCopied(null), 2000);
        });
    };

    return (
        <div className="flex flex-col gap-2">
            <p className="text-xs text-muted-foreground">
                Connect your agent once; it gets every studio tool (registry reads, conformance
                runs, PR-gated onboardings):
            </p>
            <pre className="overflow-x-auto whitespace-pre rounded-md border border-border bg-background/80 p-2 font-mono text-[10px] leading-relaxed text-muted-foreground">
                {oneLiner}
            </pre>
            <Button
                variant="outline"
                className="h-6 w-full px-2 text-xs"
                onClick={() => copy('command', oneLiner)}
            >
                {copied === 'command' ? 'Copied' : 'Copy connect command'}
            </Button>
            <p className="text-xs text-muted-foreground">
                then the onboarding runbook (platform side plus everything your own repo owns) is
                one prompt away:
            </p>
            <pre className="overflow-x-auto whitespace-pre-wrap rounded-md border border-border bg-background/80 p-2 font-mono text-[10px] leading-relaxed text-muted-foreground">
                {ask}
            </pre>
            <Button
                variant="outline"
                className="h-6 w-full px-2 text-xs"
                onClick={() => copy('ask', ask)}
            >
                {copied === 'ask' ? 'Copied' : 'Copy the prompt'}
            </Button>
            <p className="text-[10px] text-muted-foreground/70">
                {credFailed
                    ? "Credential unavailable right now; replace <credentials> with this site's base64 HTTP Basic pair (user:password)."
                    : "The command carries this site's HTTP Basic credential, already filled in (base64 of user:password)."}
            </p>
        </div>
    );
};
