import "@testing-library/jest-dom/vitest";

// jsdom lacks ResizeObserver (used by Recharts and the map).
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver ??= ResizeObserverStub as unknown as typeof ResizeObserver;
