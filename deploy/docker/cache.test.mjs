// Execute the shipped worker's handlers. This supplements, but cannot replace,
// Safari/browser CacheStorage and installed-PWA acceptance over real HTTPS.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import vm from 'node:vm';

function worker() {
  const handlers = {}, puts = [], deletions = [];
  const cache = { match: async () => undefined, put: async (...args) => puts.push(args) };
  const caches = { open: async () => cache, keys: async () => ['familyfin-static-old', 'unrelated'],
                   delete: async name => deletions.push(name) };
  const self = { location: { origin: 'https://familyfin.test' },
                 addEventListener: (name, fn) => { handlers[name] = fn; }, clients: { claim() {} } };
  const context = vm.createContext({self, caches, URL, Request, Response, Promise,
                                   fetch: async () => new Response('synthetic', {status:200})});
  vm.runInContext(readFileSync(new URL('../../frontend/public/sw.js', import.meta.url), 'utf8'), context);
  return {handlers, puts, deletions, context, cache};
}

test('API, uploads, mutations and third-party requests never enter worker caches', () => {
  const w = worker();
  for (const [path, method] of [['/api/v1/dashboard','GET'], ['/api/v1/imports/file','POST'],
    ['/upload','POST'], ['/draft','PUT'], ['/api/v1/auth/session','DELETE'], ['https://other.test/script.js','GET']]) {
    let responded = false;
    w.handlers.fetch({ request: { url: path.startsWith('https') ? path : 'https://familyfin.test'+path, method },
                       respondWith() { responded = true; } });
    assert.equal(responded, false, path);
  }
  assert.equal(w.puts.length, 0);
});

test('personal navigation and unversioned assets never persist; versioned chunks can cache', async () => {
  const w = worker();
  for (const path of ['/dashboard','/settings','/uploads/file.xlsx','/draft.json']) {
    let response;
    w.handlers.fetch({request:{url:'https://familyfin.test'+path, method:'GET', mode:'navigate'},
                      respondWith(p) { response = p; }});
    await response;
  }
  assert.equal(w.puts.length, 0);
  let response;
  w.handlers.fetch({request:{url:'https://familyfin.test/_next/static/version/chunk.js', method:'GET'},
                    respondWith(p) { response=p; }});
  await response;
  assert.equal(w.puts.length, 1);
});

test('activation purges prior FamilyFin caches only', async () => {
  const w = worker(); let done;
  w.handlers.activate({waitUntil(p) { done=p; }});
  await done;
  assert.deepEqual(w.deletions, ['familyfin-static-old']);
});

test('offline navigation returns only the generic offline document', async () => {
  const w = worker();
  w.context.fetch = async () => { throw new Error('offline'); };
  w.cache.match = async path => { assert.equal(path,'/offline.html'); return new Response('offline'); };
  let response;
  w.handlers.fetch({request:{url:'https://familyfin.test/dashboard', method:'GET', mode:'navigate'},
                    respondWith(p) { response=p; }});
  assert.equal(await (await response).text(), 'offline');
  assert.equal(w.puts.length, 0);
});
