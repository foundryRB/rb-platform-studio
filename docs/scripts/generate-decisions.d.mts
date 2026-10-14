interface Decision {
  slug: string;
  title: string;
  status: string;
}

export function readDecisions(path: string): Decision[];
export function renderDecisions(records: Decision[]): string;
