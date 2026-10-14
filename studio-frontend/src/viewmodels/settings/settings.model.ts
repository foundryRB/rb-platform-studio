import type { PlatformSettingResponse } from '@/models';

/** What the operator has typed for a knob, defaulting to what is in force. */
export const draftFor = (
    setting: PlatformSettingResponse,
    drafts: Record<string, string>,
): string => drafts[setting.key] ?? setting.effective;

/** Whether the draft would actually change what the branch pins. */
export const isDirty = (
    setting: PlatformSettingResponse,
    drafts: Record<string, string>,
): boolean => draftFor(setting, drafts).trim() !== (setting.value ?? '');

/** A positive count and one unit - the shape the backend's duration knobs admit.
 * Mirrored here only to disable the button before a round-trip; the domain is
 * still the authority and answers 400 for anything this misses. */
const DURATION = /^[1-9]\d*(ms|s|m|h|d|w|y)$/;
const COUNT = /^(0|[1-9][0-9]*)$/;

export const draftProblem = (
    setting: PlatformSettingResponse,
    drafts: Record<string, string>,
): string | null => {
    const value = draftFor(setting, drafts).trim();
    if (value === '') return 'Enter a value.';
    if (setting.unit === 'duration' && !DURATION.test(value)) {
        return "Use a count and a unit, like '720h' or '30d'.";
    }
    if (setting.unit === 'count' && !COUNT.test(value)) {
        return 'Use a non-negative whole number.';
    }
    return null;
};

/** Knobs grouped by category, categories in first-seen order. */
export const byCategory = (
    settings: PlatformSettingResponse[],
): [string, PlatformSettingResponse[]][] => {
    const groups = new Map<string, PlatformSettingResponse[]>();
    for (const setting of settings) {
        const group = groups.get(setting.category);
        if (group) group.push(setting);
        else groups.set(setting.category, [setting]);
    }
    return [...groups.entries()];
};
