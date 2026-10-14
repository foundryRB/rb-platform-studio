import { cn } from '@/utils';

export interface AppIconProps {
    /** The gethomepage-style icon id, e.g. "mdi-source-branch-check". */
    icon: string;
    className?: string;
}

const MDI_PREFIX = 'mdi-';
// The same Material Design Icons the install's home page tiles resolve `mdi-<name>`
// against. A static SVG fetch publishes nothing: the icon id is not a secret.
const MDI_CDN = 'https://cdn.jsdelivr.net/npm/@mdi/svg@latest/svg';

/**
 * Render a Material Design Icon from its `mdi-<name>` id. The SVG is applied as
 * a CSS mask so the glyph inherits `currentColor` and follows the light/dark
 * theme; the raw id stays as the hover title for discoverability. A non-mdi id
 * falls back to its text, so an unknown value still shows something.
 */
export const AppIcon = ({ icon, className }: AppIconProps) => {
    if (!icon.startsWith(MDI_PREFIX)) {
        return <span className="font-mono text-[10px] text-muted-foreground">{icon}</span>;
    }
    const url = `${MDI_CDN}/${icon.slice(MDI_PREFIX.length)}.svg`;
    const mask = {
        maskImage: `url("${url}")`,
        WebkitMaskImage: `url("${url}")`,
        maskRepeat: 'no-repeat',
        WebkitMaskRepeat: 'no-repeat',
        maskPosition: 'center',
        WebkitMaskPosition: 'center',
        maskSize: 'contain',
        WebkitMaskSize: 'contain',
    };
    return (
        <span
            role="img"
            aria-label={icon}
            title={icon}
            className={cn('inline-block h-6 w-6 shrink-0 bg-current', className)}
            style={mask}
        />
    );
};
