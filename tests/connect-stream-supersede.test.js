/** @vitest-environment happy-dom */
import { describe, expect, it, vi } from "vitest";

vi.mock("../js/personal-storage.js", () => ({
  getPersonal: vi.fn((g) => g._personal || { status: "backlog" }),
  filterOutHidden: vi.fn((arr) => arr),
}));

describe("replaceActiveConnectStream", () => {
  it("closes the prior EventSource when a new one is registered", async () => {
    const { replaceActiveConnectStream } = await import("../js/connections.js");
    const first = { close: vi.fn(), onerror: () => {} };
    const second = { close: vi.fn(), onerror: () => {} };

    expect(replaceActiveConnectStream("steam", first)).toBeNull();
    const prev = replaceActiveConnectStream("steam", second);
    expect(prev).toBe(first);
    expect(first.close).toHaveBeenCalledTimes(1);
    expect(first.onerror).toBeNull();
    expect(second.close).not.toHaveBeenCalled();
  });

  it("does not close when re-registering the same stream object", async () => {
    const { replaceActiveConnectStream } = await import("../js/connections.js");
    const es = { close: vi.fn(), onerror: () => {} };
    replaceActiveConnectStream("gog", es);
    replaceActiveConnectStream("gog", es);
    expect(es.close).not.toHaveBeenCalled();
  });
});
