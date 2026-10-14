import { useEffect, useState } from 'react';

/** Ambient PSA contours and embers, separate from the working surface. */
export const AmbientField = () => {
    const [hidden, setHidden] = useState(document.hidden);
    useEffect(() => {
        const update = () => setHidden(document.hidden);
        document.addEventListener('visibilitychange', update);
        return () => document.removeEventListener('visibilitychange', update);
    }, []);
    return (
        <div className="app-atmosphere" aria-hidden="true" data-paused={hidden}>
            {['left', 'right'].map((side) => (
                <svg key={side} className={side} viewBox="0 0 400 1000" preserveAspectRatio="none">
                    {[0, 38, 72, 105, 143, 188, 240].map((x) => (
                        <path
                            key={x}
                            d={`M ${x} -100 C ${260 + x} 170 ${-190 + x} 320 ${15 + x} 570 S ${220 + x} 910 ${-10 + x} 1120`}
                        />
                    ))}
                </svg>
            ))}
            {Array.from({ length: 16 }, (_, i) => (
                <i key={i} />
            ))}
        </div>
    );
};
