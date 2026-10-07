// Runs public/sw.js against stand-ins for the browser's cache and network.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import vm from "node:vm";

const ORIGIN = "http://app.test";
const source = readFileSync(new URL("../public/sw.js", import.meta.url), "utf8");

function boot() {
  const stores = new Map(); // cache name -> Map(url -> body)
  const listeners = {};
  const network = { online: true, calls: [], status: 200 };
  const open = async (name) => {
    if (!stores.has(name)) stores.set(name, new Map());
    const store = stores.get(name);
    return {
      match: async (key) => {
        const url = typeof key === "string" ? new URL(key, ORIGIN).href : key.url;
        return store.has(url) ? { ok: true, body: store.get(url), fromCache: true } : undefined;
      },
      put: async (request, response) => void store.set(request.url, response.body),
    };
  };
  const context = {
    URL,
    self: {
      location: { origin: ORIGIN },
      addEventListener: (type, fn) => (listeners[type] = fn),
      skipWaiting: () => {},
      clients: { claim: async () => {} },
    },
    caches: { open, keys: async () => [...stores.keys()], delete: async (k) => stores.delete(k) },
    fetch: async (request) => {
      network.calls.push(request.url);
      if (!network.online) throw new TypeError("Failed to fetch");
      const response = { ok: network.status < 400, status: network.status, body: `net:${request.url}` };
      return { ...response, clone: () => response };
    },
  };
  vm.runInNewContext(source, context);
  /** Dispatch a fetch event; resolves to the response, or undefined when the worker leaves it to the browser. */
  const get = (path, { method = "GET", mode = "cors", origin = ORIGIN } = {}) => {
    let responded;
    listeners.fetch({ request: { url: origin + path, method, mode }, respondWith: (p) => (responded = p) });
    return responded;
  };
  return { get, network, stores, listeners };
}

test("API responses are fetched fresh and replayed from cache when offline", async () => {
  const sw = boot();
  assert.equal((await sw.get("/api/games/powerball")).body, `net:${ORIGIN}/api/games/powerball`);
  sw.network.online = false;
  const offline = await sw.get("/api/games/powerball");
  assert.equal(offline.fromCache, true);
  assert.equal(offline.body, `net:${ORIGIN}/api/games/powerball`);
  await assert.rejects(sw.get("/api/games/never-seen"), /Failed to fetch/);
});

test("hashed static assets are served from cache without touching the network again", async () => {
  const sw = boot();
  await sw.get("/_next/static/chunks/app.js");
  await sw.get("/_next/static/chunks/app.js");
  assert.equal(sw.network.calls.length, 1);
});

test("an offline navigation falls back to the cached copy, then to the cached home screen", async () => {
  const sw = boot();
  await sw.get("/powerball", { mode: "navigate" });
  await sw.get("/wa-hit5/trends", { mode: "navigate" });
  sw.network.online = false;
  assert.equal((await sw.get("/wa-hit5/trends", { mode: "navigate" })).body, `net:${ORIGIN}/wa-hit5/trends`);
  assert.equal((await sw.get("/megamillions", { mode: "navigate" })).body, `net:${ORIGIN}/powerball`);
});

test("writes and other origins are left to the browser", () => {
  const sw = boot();
  assert.equal(sw.get("/api/games/powerball/forecast/generate", { method: "POST" }), undefined);
  assert.equal(sw.get("/anything", { origin: "https://elsewhere.test" }), undefined);
  assert.equal(sw.network.calls.length, 0);
});

test("error responses are not cached", async () => {
  const sw = boot();
  sw.network.status = 500;
  await sw.get("/api/health");
  sw.network.online = false;
  await assert.rejects(sw.get("/api/health"), /Failed to fetch/);
});

test("activation removes caches from older versions", async () => {
  const sw = boot();
  await (await sw.stores.set("static-v0", new Map()));
  await sw.get("/api/health");
  let done;
  sw.listeners.activate({ waitUntil: (p) => (done = p) });
  await done;
  assert.deepEqual([...sw.stores.keys()], ["data-v1"]);
});
