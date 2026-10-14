import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    include: ['tests/**/*.test.ts'],
    environment: 'node',
    // A fresh scaffold may have no test files yet (scaffolded with --no-intent,
    // or before the STARLIGHT bundle's claim tests land), so an empty run passes.
    passWithNoTests: true,
  },
});
