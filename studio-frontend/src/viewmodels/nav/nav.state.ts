export type StudioView = 'apps' | 'app' | 'conformance' | 'prs' | 'onboard' | 'settings';

export interface NavState {
    view: StudioView;
}
