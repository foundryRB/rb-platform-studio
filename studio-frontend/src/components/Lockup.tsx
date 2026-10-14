/**
 * The Vodafone Portugal Digital lockup as live text: the speechmark tile, a hairline, "Digital
 * Engineering" over the tracked mono "Vodafone Portugal", the Portuguese flag. Self-contained
 * (inline SVG, inline styles, no Tailwind), so it drops into any React shell; the outlined SVG
 * it replaces went soft at header sizes because 11px paths get no hinting.
 *
 * Faces: "Vodafone" (public/fonts, shipped by the identity pass) and "JetBrains Mono" 600
 * (ship public/fonts/JetBrainsMono-600.woff2 with an @font-face beside the brand face's).
 *
 *   <Lockup mode="dark" />            the stage: white disc, mark open, light words
 *   <Lockup mode="light" />           paper: red disc, white mark, ink words
 *   <Lockup mode="dark" height={36} />   the tile's height in px (default 40); everything scales
 *   <Lockup mode="dark" name="Foundry Console" />  the shell's own name after the flag
 */
import type { CSSProperties } from 'react';

const DISC = 'M113.415 33.2927C107.561 21.2195 97.6829 11.7073 85.2439 5.85366C74.2683 8.04878 65.8536 18.2927 65.8536 29.6341C65.8536 30 65.8536 30.3659 65.8536 30.7317C84.1463 35.122 92.561 46.0976 92.561 61.4634C92.561 76.8293 80.4878 93.2927 60.3658 93.2927C43.9024 93.2927 26.7073 79.3902 26.7073 56.7073C26.7073 41.7073 34.7561 27.439 45 19.0244C54.878 10.6098 68.7805 5.4878 81.2195 5.4878C82.6829 5.4878 84.5122 5.4878 85.6097 5.85366C77.9268 2.19512 69.1463 0 60 0C46.0975 0 33.2927 4.7561 23.0488 12.8049C9.14634 23.7805 0 40.6098 0 60C0 92.9268 26.7073 120 60 120C93.2927 120 120 93.2927 120 60C119.634 50.122 117.439 41.3415 113.415 33.2927Z';
const MARK = 'M85.6097 5.4878C84.5121 5.12195 83.0487 5.12195 81.2195 5.12195C68.7805 5.12195 54.878 10.6098 45 18.6585C34.7561 27.0732 26.7073 41.7073 26.7073 56.3414C26.7073 79.0244 43.9024 92.9268 60.3658 92.9268C80.8536 92.9268 92.5609 76.0975 92.5609 61.0975C92.5609 45.7317 84.1463 34.7561 65.8536 30.3658C65.8536 30 65.8536 29.6341 65.8536 29.2683C65.8536 17.9268 74.6341 8.04878 85.6097 5.4878Z';

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
  const sans = '"Vodafone", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif';
  const mono = '"JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace';
  return (
    <span
      className={className}
      role="img"
      aria-label={name ? `${name}, Digital Engineering, Vodafone Portugal` : 'Digital Engineering, Vodafone Portugal'}
      style={{ display: 'inline-flex', alignItems: 'center', lineHeight: 1, ...style }}
    >
      <svg viewBox="0 0 120 120" width={height} height={height} aria-hidden="true" style={{ flex: 'none' }}>
        <path d={DISC} fill={dark ? '#ffffff' : '#e60000'} />
        <path d={MARK} fill={dark ? '#0b0d12' : '#ffffff'} />
      </svg>
      <span
        style={{
          display: 'flex', flexDirection: 'column', justifyContent: 'center',
          minHeight: 38 * s, marginLeft: 12 * s, paddingLeft: 12 * s, borderLeft: `1px solid ${line}`,
        }}
      >
        <b style={{ fontFamily: sans, fontSize: 14.5 * s, fontWeight: 700, letterSpacing: 1 * s, lineHeight: 1.2, color: txt, whiteSpace: 'nowrap' }}>
          Digital Engineering
        </b>
        <i style={{ marginTop: 4 * s, fontFamily: mono, fontStyle: 'normal', fontSize: 11 * s, fontWeight: 600, letterSpacing: 2.6 * s, lineHeight: 1.2, textTransform: 'uppercase', color: mut, whiteSpace: 'nowrap' }}>
          Vodafone Portugal
        </i>
      </span>
      <svg viewBox="0 0 28 19" width={28 * s} height={19 * s} aria-hidden="true" style={{ flex: 'none', marginLeft: 12 * s }}>
      <defs><clipPath id="vfd-flag-clip"><rect x="0" y="0" width="28" height="19" rx="3"/></clipPath></defs>
      <g clipPath="url(#vfd-flag-clip)"><rect width="11.8" height="19" fill="#036A3A"/><rect x="11.8" width="16.2" height="19" fill="#DA020E"/></g>
      <g transform="translate(11.8,9.5)"><circle r="5.7" fill="#ffe14d" fillOpacity="0.18" stroke="#ffcf1f" strokeWidth="0.9"/><ellipse rx="5.7" ry="2.39" fill="none" stroke="#ffcf1f" strokeWidth="0.7"/><ellipse rx="2.39" ry="5.7" fill="none" stroke="#ffcf1f" strokeWidth="0.7"/><rect x="-2.3" y="-3.1" width="4.6" height="5.6" rx="0.6" fill="#DA020E" stroke="#fff" strokeWidth="0.6"/><rect x="-1.3" y="-2" width="2.6" height="3.2" rx="0.4" fill="#fff"/></g>
      </svg>
      {name ? (
        <span style={{ marginLeft: 14 * s, paddingLeft: 14 * s, borderLeft: `1px solid ${line}`, fontFamily: sans, fontSize: 15 * s, fontWeight: 400, color: dark ? '#a8b0bd' : '#4a4d4e', whiteSpace: 'nowrap' }}>
          {name}
        </span>
      ) : null}
    </span>
  );
}

export default Lockup;
