import type { ReactNode } from 'react';

import { Lockup } from '@/components/Lockup';
import { useNav, type StudioView } from '@/viewmodels/nav';
import { useAppearance } from '../../vodafone/useAppearance';
import { Appearance } from '../../vodafone/Appearance';
import { AmbientField } from '@/views/atoms/AmbientField';
import { ConnectMenu } from '@/views/molecules/ConnectMenu';
import { cn } from '@/utils';

export interface MainLayoutProps {
    children: ReactNode;
}

const TABS: { target: StudioView; label: string }[] = [
    { target: 'apps', label: 'Apps' },
    { target: 'conformance', label: 'Conformance' },
    { target: 'prs', label: 'Pull requests' },
    { target: 'onboard', label: 'Onboard' },
    { target: 'settings', label: 'Settings' },
];

export const MainLayout = ({ children }: MainLayoutProps) => {
    const view = useNav((state) => state.view);
    const setView = useNav((state) => state.setView);
    const { resolved: mode } = useAppearance();

    // The app-detail page belongs to the Apps tab.
    const activeTab = view === 'app' ? 'apps' : view;

    return (
        <div className="flex min-h-screen flex-col">
            <AmbientField />
            <header className="sticky top-0 z-10 border-b border-border/70 bg-background/85 backdrop-blur">
                <div className="app-frame app-header">
                    <div className="flex items-center gap-2.5">
                        <Lockup mode={mode} height={36} />
                        <h1 className="text-sm font-medium tracking-tight">Platform Studio</h1>
                    </div>
                    <nav aria-label="Primary navigation">
                        {TABS.map(({ target, label }) => (
                            <button
                                key={target}
                                aria-current={activeTab === target ? 'page' : undefined}
                                onClick={() => setView(target)}
                                className={cn(
                                    'rounded-md px-3 py-1 text-sm font-medium transition-colors',
                                    activeTab === target
                                        ? 'bg-secondary text-foreground'
                                        : 'text-muted-foreground hover:text-foreground',
                                )}
                            >
                                {label}
                            </button>
                        ))}
                    </nav>
                    <div className="ml-auto flex items-center gap-3">
                        <ConnectMenu />
                        <Appearance />
                    </div>
                </div>
            </header>
            <main className="app-frame app-main flex-1">{children}</main>
        </div>
    );
};
