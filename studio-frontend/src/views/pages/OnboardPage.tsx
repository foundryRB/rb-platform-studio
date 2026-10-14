import { Card } from '@/components/ui/card';
import {
    CreateAppRepoForm,
    OffboardAppForm,
    ReconcileAppForm,
    ReconcileIdentityForm,
} from '@/views/organisms/LifecycleForms';
import { OnboardAppForm } from '@/views/organisms/OnboardAppForm';
import { OnboardDatabaseForm } from '@/views/organisms/OnboardDatabaseForm';
import { OnboardEventsForm } from '@/views/organisms/OnboardEventsForm';
import { OnboardIdentityForm } from '@/views/organisms/OnboardIdentityForm';
import { OnboardOutcome } from '@/views/organisms/OnboardOutcome';

export const OnboardPage = () => (
    <div className="mx-auto flex max-w-4xl flex-col gap-4">
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <div className="flex flex-col gap-4">
                <Card className="p-5">
                    <CreateAppRepoForm />
                </Card>
                <Card className="p-5">
                    <OnboardAppForm />
                </Card>
            </div>
            <div className="flex flex-col gap-4">
                <Card className="p-5">
                    <OnboardDatabaseForm />
                </Card>
                <Card className="p-5">
                    <OnboardIdentityForm />
                    <OnboardEventsForm />
                </Card>
                <Card className="p-5">
                    <ReconcileAppForm />
                </Card>
                <Card className="p-5">
                    <ReconcileIdentityForm />
                </Card>
                <Card className="p-5">
                    <OffboardAppForm />
                </Card>
            </div>
        </div>
        <OnboardOutcome />
    </div>
);
