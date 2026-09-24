// Vitest 5's happy-dom environment exposes these as getter-only globals.
// Many tests install a fresh happy-dom Window and assign/delete them directly,
// so turn them back into plain writable, configurable properties.
const REASSIGNABLE_GLOBALS = ["localStorage", "sessionStorage", "navigator", "CSS"];

for (const key of REASSIGNABLE_GLOBALS) {
  const desc = Object.getOwnPropertyDescriptor(globalThis, key);
  if (!desc || !desc.configurable || "value" in desc) continue;
  Object.defineProperty(globalThis, key, {
    value: globalThis[key],
    writable: true,
    configurable: true,
    enumerable: desc.enumerable,
  });
}
