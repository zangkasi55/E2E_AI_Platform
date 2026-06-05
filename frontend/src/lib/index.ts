// =============================================================================
// lib/index.ts — selects the active Backend (mock vs real) from VITE_USE_MOCK.
// Import { backend } anywhere; the UI is agnostic to which one is live.
// =============================================================================
import type { Backend } from "./backend";
import { USE_MOCK } from "./backend";
import { mockBackend } from "./mockBackend";
import { apiBackend } from "./api";

export const backend: Backend = USE_MOCK ? mockBackend : apiBackend;
export { USE_MOCK } from "./backend";
export type { Backend } from "./backend";
