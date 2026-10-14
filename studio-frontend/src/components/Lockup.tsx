/**
 * The RB lockup as live text: the RB tile, a hairline, "Software Engineering" over the
 * tracked mono "RB". Self-contained (inline SVG, inline styles, no Tailwind), so it drops into
 * any React shell; live text stays crisp at header sizes.
 *
 * Faces: system font stacks, and "JetBrains Mono" 600 for the mono line
 * (ship public/fonts/JetBrainsMono-600.woff2 with an @font-face).
 *
 *   <Lockup mode="dark" />            the stage: light tile and words
 *   <Lockup mode="light" />           paper: ink tile and words
 *   <Lockup mode="dark" height={36} />   the tile's height in px (default 40); everything scales
 *   <Lockup mode="dark" name="Foundry Console" />  the shell's own name after the words
 */
import type { CSSProperties } from 'react';

export type LockupProps = {
  mode?: 'dark' | 'light';
  height?: number;
  name?: string;
  className?: string;
  style?: CSSProperties;
};

export function Lockup({ mode = 'dark', height = 40, name, className, style }: LockupProps) {
  const s = height / 50; // the reference tile is 50px
  const dark = mode === 'dark';
  const txt = dark ? '#f2f4f8' : '#0d0d0d';
  const mut = dark ? '#6c7480' : '#7e7e7e';
  const line = dark ? 'rgba(255,255,255,.10)' : 'rgba(0,0,0,.12)';
  const sans = '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif';
  const mono = '"JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace';
  return (
    <span
      className={className}
      role="img"
      aria-label={name ? `${name}, Software Engineering, RB` : 'Software Engineering, RB'}
      style={{ display: 'inline-flex', alignItems: 'center', lineHeight: 1, ...style }}
    >
      <svg viewBox="0 0 120 120" width={height} height={height} aria-hidden="true" style={{ flex: 'none', color: txt }}>
        <rect x="6" y="6" width="108" height="108" rx="18" fill="none" stroke="currentColor" strokeWidth="8" />
        <text x="60" y="77" textAnchor="middle" fontFamily="system-ui,-apple-system,Segoe UI,sans-serif" fontSize="48" fontWeight="800" fill="currentColor">RB</text>
      </svg>
      <span
        style={{
          display: 'flex', flexDirection: 'column', justifyContent: 'center',
          minHeight: 38 * s, marginLeft: 12 * s, paddingLeft: 12 * s, borderLeft: `1px solid ${line}`,
        }}
      >
        <b style={{ fontFamily: sans, fontSize: 14.5 * s, fontWeight: 700, letterSpacing: 1 * s, lineHeight: 1.2, color: txt, whiteSpace: 'nowrap' }}>
          Software Engineering
        </b>
        <i style={{ marginTop: 4 * s, fontFamily: mono, fontStyle: 'normal', fontSize: 11 * s, fontWeight: 600, letterSpacing: 2.6 * s, lineHeight: 1.2, textTransform: 'uppercase', color: mut, whiteSpace: 'nowrap' }}>
          RB
        </i>
      </span>
      {name ? (
        <span style={{ marginLeft: 14 * s, paddingLeft: 14 * s, borderLeft: `1px solid ${line}`, fontFamily: sans, fontSize: 15 * s, fontWeight: 400, color: dark ? '#a8b0bd' : '#4a4d4e', whiteSpace: 'nowrap' }}>
          {name}
        </span>
      ) : null}
    </span>
  );
}

export default Lockup;
