/* @vitest-environment node */
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import proConfigHandler from "../landing/api/pro-config.js";

const { fetch: handleProConfig } = proConfigHandler;

describe("landing/api/pro-config.js", () => {
  beforeEach(() => {
    delete process.env.BAKLOG_PRO_CHECKOUT;
  });

  afterEach(() => {
    delete process.env.BAKLOG_PRO_CHECKOUT;
  });

  it("defaults checkout off during beta", async () => {
    const res = await handleProConfig();
    const json = await res.json();
    expect(json.proCheckoutEnabled).toBe(false);
    expect(json.proCheckout).toEqual({ monthly: "", yearly: "" });
  });

  it("enables checkout URLs when BAKLOG_PRO_CHECKOUT=1", async () => {
    process.env.BAKLOG_PRO_CHECKOUT = "1";
    const res = await handleProConfig();
    const json = await res.json();
    expect(json.proCheckoutEnabled).toBe(true);
    expect(json.proCheckout.monthly).toContain("buy.polar.sh");
    expect(json.proCheckout.yearly).toContain("buy.polar.sh");
  });
});
