import { Button } from '@/components/ui/button';
import { useOnboard } from '@/viewmodels/onboard';
import { AppIcon } from '@/views/atoms/AppIcon';

const FIELD_CLASSES =
    'w-full rounded-md border border-input bg-background/70 px-3 py-1.5 text-sm outline-none placeholder:text-muted-foreground/50 focus:ring-1 focus:ring-ring';

export const OnboardAppForm = () => {
    const appName = useOnboard((state) => state.appName);
    const displayName = useOnboard((state) => state.displayName);
    const description = useOnboard((state) => state.description);
    const icon = useOnboard((state) => state.icon);
    const repo = useOnboard((state) => state.repo);
    const imageComponents = useOnboard((state) => state.imageComponents);
    const exposeMcp = useOnboard((state) => state.exposeMcp);
    const submitting = useOnboard((state) => state.submitting);
    const setField = useOnboard((state) => state.setField);
    const setExposeMcp = useOnboard((state) => state.setExposeMcp);
    const submitApp = useOnboard((state) => state.submitApp);

    return (
        <div className="flex flex-col gap-4">
            <div>
                <h2 className="text-lg font-bold tracking-tight">Onboard an app</h2>
                <p className="mt-0.5 text-xs text-muted-foreground">
                    Writes the platform-side manifest on a branch, runs the conformance suite
                    against a baseline, and ships the change as a pull request. Rejected changes
                    never land.
                </p>
            </div>

            <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
                Name (lowercase DNS label; becomes the namespace)
                <input
                    className={`${FIELD_CLASSES} font-mono`}
                    value={appName}
                    onChange={(e) => setField('appName', e.target.value)}
                    placeholder="my-app"
                />
            </label>

            <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
                Display name
                <input
                    className={FIELD_CLASSES}
                    value={displayName}
                    onChange={(e) => setField('displayName', e.target.value)}
                    placeholder="My App"
                />
            </label>

            <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
                Description
                <textarea
                    className={`${FIELD_CLASSES} h-20`}
                    value={description}
                    onChange={(e) => setField('description', e.target.value)}
                    placeholder="What the app does, one sentence."
                />
            </label>

            <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
                Icon (Material Design Icons name)
                <div className="flex items-center gap-2">
                    <input
                        className={`${FIELD_CLASSES} font-mono`}
                        value={icon}
                        onChange={(e) => setField('icon', e.target.value)}
                        placeholder="mdi-application"
                    />
                    {icon && <AppIcon icon={icon} className="text-foreground" />}
                </div>
                <span className="text-[10px] font-normal text-muted-foreground/70">
                    Browse names at pictogrammers.com/library/mdi
                </span>
            </label>

            <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
                Repository (empty = named for the app)
                <input
                    className={`${FIELD_CLASSES} font-mono`}
                    value={repo}
                    onChange={(e) => setField('repo', e.target.value)}
                    placeholder={appName || 'my-app'}
                />
                <span className="text-[10px] font-normal text-muted-foreground/70">
                    The repository under the fleet org that the Application points at. The app name
                    above is the namespace, hostname, chart, and GHCR packages; name the repository
                    here when it differs.
                </span>
            </label>

            <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
                Released images (comma-separated components; empty = single image)
                <input
                    className={`${FIELD_CLASSES} font-mono`}
                    value={imageComponents}
                    onChange={(e) => setField('imageComponents', e.target.value)}
                    placeholder="server, client, docs"
                />
                <span className="text-[10px] font-normal text-muted-foreground/70">
                    One Image Updater alias per component: package &lt;name&gt;-&lt;component&gt;,
                    values &lt;name&gt;.images.&lt;component&gt;.tag. Empty binds the single package
                    &lt;name&gt; to &lt;name&gt;.image.tag.
                </span>
            </label>

            <label className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
                <input
                    type="checkbox"
                    checked={exposeMcp}
                    onChange={(e) => setExposeMcp(e.target.checked)}
                    className="h-3.5 w-3.5 accent-[hsl(var(--primary))]"
                />
                Expose an MCP endpoint for this app
            </label>

            <div>
                <Button disabled={submitting} onClick={() => void submitApp()}>
                    {submitting ? 'Running the gates...' : 'Onboard app (runs gates)'}
                </Button>
            </div>
        </div>
    );
};
