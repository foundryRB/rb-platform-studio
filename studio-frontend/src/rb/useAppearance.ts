import { useSyncExternalStore } from 'react';

export type Appearance = 'light' | 'dark' | 'system';
declare global {
    interface Window {
        rbAppearance: {
            get(): {
                preference: Appearance;
                resolved: 'dark' | 'light';
                motion: boolean;
                reduced: boolean;
            };
            set(value: Appearance): void;
            setMotion(enabled: boolean): void;
        };
    }
}
const subscribe = (notify: () => void) => {
    document.addEventListener('rb-appearance', notify);
    return () => document.removeEventListener('rb-appearance', notify);
};
// Primitive snapshots stay referentially stable between appearance events.
export const useAppearance = () => {
    const preference = useSyncExternalStore(
        subscribe,
        () => window.rbAppearance.get().preference,
    );
    const resolved = useSyncExternalStore(
        subscribe,
        () => window.rbAppearance.get().resolved,
    );
    const motion = useSyncExternalStore(subscribe, () => window.rbAppearance.get().motion);
    const reduced = useSyncExternalStore(subscribe, () => window.rbAppearance.get().reduced);
    return {
        preference,
        resolved,
        motion,
        reduced,
        set: window.rbAppearance.set,
        setMotion: window.rbAppearance.setMotion,
    };
};
