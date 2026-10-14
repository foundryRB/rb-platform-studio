import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

vi.mock('@/utils', async (importOriginal) => ({
    ...(await importOriginal<typeof import('@/utils')>()),
    apiFetch: vi.fn(),
}));

import { apiFetch } from '@/utils';
import { ConnectAgent } from '@/views/molecules/ConnectAgent';

// base64('ops:s3cret')
const CRED = 'b3BzOnMzY3JldA==';

describe('ConnectAgent', () => {
    beforeEach(() => {
        vi.mocked(apiFetch).mockReset();
        vi.mocked(apiFetch).mockResolvedValue({ credential: CRED });
    });

    afterEach(() => {
        vi.restoreAllMocks();
    });

    it('fetches and fills the real credential into the one-liner on mount', async () => {
        render(<ConnectAgent />);

        const line = await screen.findByText(
            /claude mcp add --scope user --transport http platform-studio/,
        );
        expect(line.textContent).toContain(`${window.location.origin}/mcp`);

        await waitFor(() => {
            expect(screen.getByText(/claude mcp add/).textContent).toContain(
                `Authorization: Basic ${CRED}`,
            );
        });
        expect(screen.getByText(/claude mcp add/).textContent).not.toContain('<credentials>');
        expect(apiFetch).toHaveBeenCalledWith('/api/agent-credential');
    });

    it('falls back to the placeholder when the credential is unavailable', async () => {
        vi.mocked(apiFetch).mockRejectedValue(new Error('503'));
        render(<ConnectAgent />);

        await waitFor(() => {
            expect(screen.getByText(/claude mcp add/).textContent).toContain('<credentials>');
        });
    });

    it('offers a copy button for the connect command', async () => {
        render(<ConnectAgent />);
        await waitFor(() => {
            expect(screen.getByText('Copy connect command')).toBeInTheDocument();
        });
    });
});
