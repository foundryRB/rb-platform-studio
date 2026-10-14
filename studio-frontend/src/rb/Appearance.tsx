import { useAppearance, type Appearance as AppearancePreference } from './useAppearance';

export const Appearance = () => {
    const appearance = useAppearance();
    return (
        <div className="rb-appearance">
            <label>
                <span className="sr-only">Appearance</span>
                <select
                    aria-label="Appearance"
                    value={appearance.preference}
                    onChange={(e) => appearance.set(e.target.value as AppearancePreference)}
                >
                    <option value="light">Light</option>
                    <option value="dark">Dark</option>
                    <option value="system">System</option>
                </select>
            </label>
        </div>
    );
};
