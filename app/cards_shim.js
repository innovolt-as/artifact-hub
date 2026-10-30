/*
 * cards_shim.js — loaded by app/cards_worker.py into a fresh V8 context before an app's card recipe.
 *
 * It gives hubCard({ db, today, now, timeZone }) a read-only `db` with the same shape as the one in hub.js, so code
 * can be copied between an app and its recipe. The data comes with the job: input.docs maps document paths to their
 * data (null when missing) and input.cols maps collection paths to [{id, data}]. Reading a path the job does not
 * carry records it in `need` and rejects; the worker then answers {need}, the server reads those paths and runs the
 * recipe again with them. __hubRun(input) returns the answer as a JSON string:
 *   {"text": string|null} | {"need": [["doc"|"col", path], ...]} | {"error": code, "message"?: string}
 */
const __hubRun = (() => {
  const MISSING = Symbol("missing"); // thrown by a read whose data the job does not carry
  const META = Object.freeze({ fromCache: false, hasPendingWrites: false });
  const OPS = {
    "==": (a, b) => a === b, "!=": (a, b) => a !== b,
    "<": (a, b) => a < b, "<=": (a, b) => a <= b, ">": (a, b) => a > b, ">=": (a, b) => a >= b,
    "in": (a, b) => b.includes(a), "not-in": (a, b) => !b.includes(a),
    "array-contains": (a, b) => Array.isArray(a) && a.includes(b),
  };

  const segs = (p) => String(p).split("/").filter(Boolean);
  function checkPath(path, wantEven) {
    const s = segs(path);
    if (!s.length || (s.length % 2 === 0) !== wantEven) {
      throw new TypeError(`Not a ${wantEven ? "document" : "collection"} path: ${path}`);
    }
    return s.join("/");
  }

  function docSnap(id, data) {
    const body = data == null ? undefined : Object.freeze(data);
    return { id, exists: body !== undefined, data: () => body, metadata: META };
  }

  function makeDb(input, need) {
    function load(kind, store, path) {
      if (Object.prototype.hasOwnProperty.call(store, path)) return store[path];
      if (!need.some(([k, p]) => k === kind && p === path)) need.push([kind, path]);
      throw MISSING;
    }

    function makeQuery(path, filters, order, max) {
      function run() {
        let list = load("col", input.cols, path)
          .filter((d) => filters.every(([f, op, v]) => f in d.data && OPS[op](d.data[f], v)));
        if (order) {
          const [f, dir] = order, k = dir === "desc" ? -1 : 1;
          list.sort((x, y) => {
            if (!(f in x.data)) return 1;
            if (!(f in y.data)) return -1;
            return x.data[f] < y.data[f] ? -k : x.data[f] > y.data[f] ? k : 0;
          });
        }
        if (max) list = list.slice(0, max);
        return list.map((d) => docSnap(d.id, d.data));
      }
      return {
        where: (f, op, v) => {
          if (!OPS[op]) throw new TypeError(`Unknown operator: ${op}`);
          return makeQuery(path, [...filters, [f, op, v]], order, max);
        },
        orderBy: (f, dir = "asc") => makeQuery(path, filters, [f, dir], max),
        limit: (n) => makeQuery(path, filters, order, n),
        get: async () => {
          const docs = run();
          return { docs, size: docs.length, empty: docs.length === 0, metadata: META, forEach: (fn) => docs.forEach(fn) };
        },
      };
    }

    function docRef(path) {
      path = checkPath(path, true);
      const id = path.split("/").pop();
      return {
        id, path,
        get: async () => docSnap(id, load("doc", input.docs, path)),
        collection: (sub) => collectionRef(path + "/" + sub),
      };
    }

    function collectionRef(path) {
      path = checkPath(path, false);
      return Object.assign(makeQuery(path, [], null, 0), {
        path,
        doc: (id) => docRef(path + "/" + (id ?? "")),
      });
    }

    return Object.freeze({ doc: docRef, collection: collectionRef });
  }

  function describe(e) {
    try { return String(e); } catch (_) { return "uncaught exception"; }
  }

  return async function run(input) {
    if (typeof hubCard !== "function") return JSON.stringify({ error: "no_function" });
    const need = [];
    let out;
    try {
      const v = await hubCard({ db: makeDb(input, need), today: input.today, now: input.now, timeZone: input.tz });
      out = v == null || v === "" ? { text: null } : typeof v === "string" ? { text: v } : { error: "not_text" };
    } catch (e) {
      out = { error: "failed", message: describe(e) };
    }
    // a missing read wins even when the recipe caught it: its answer was computed without that data
    return JSON.stringify(need.length ? { need } : out);
  };
})();
