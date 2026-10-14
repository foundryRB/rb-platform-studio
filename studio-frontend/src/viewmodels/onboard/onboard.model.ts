/** Kubernetes namespaces, hostnames, and registry keys all demand this shape. */
const DNS_LABEL = /^[a-z]([a-z0-9-]*[a-z0-9])?$/;

/** Validate an app name client-side: a lowercase DNS label, max 63 chars. */
export const appNameProblem = (name: string): string | null => {
    if (name.length === 0) {
        return 'Name is required.';
    }
    if (name.length > 63) {
        return 'Name must be at most 63 characters.';
    }
    if (!DNS_LABEL.test(name)) {
        return 'Name must be a lowercase DNS label: a-z, 0-9, and inner hyphens only.';
    }
    return null;
};
