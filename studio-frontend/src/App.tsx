import { useNav } from '@/viewmodels/nav';
import { MainLayout } from '@/views/templates/MainLayout';
import { AppDetailPage } from '@/views/pages/AppDetailPage';
import { AppsPage } from '@/views/pages/AppsPage';
import { ConformancePage } from '@/views/pages/ConformancePage';
import { OnboardPage } from '@/views/pages/OnboardPage';
import { PrsPage } from '@/views/pages/PrsPage';
import { SettingsPage } from '@/views/pages/SettingsPage';

const App = () => {
    const view = useNav((state) => state.view);

    return (
        <MainLayout>
            {view === 'apps' && <AppsPage />}
            {view === 'app' && <AppDetailPage />}
            {view === 'conformance' && <ConformancePage />}
            {view === 'prs' && <PrsPage />}
            {view === 'onboard' && <OnboardPage />}
            {view === 'settings' && <SettingsPage />}
        </MainLayout>
    );
};

export default App;
