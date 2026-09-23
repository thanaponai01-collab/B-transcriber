const test = require("node:test");
const assert = require("node:assert/strict");
const {
  CUTDECK_BIN_NAME,
  runTransaction,
  getOrCreateBin,
  activeProjectAndSequence,
} = require("../uxp/cutdeck/host/project.js");

// --- CUTDECK_BIN_NAME --------------------------------------------------------

test("CUTDECK_BIN_NAME is 'CutDeck'", () => {
  assert.equal(CUTDECK_BIN_NAME, "CutDeck");
});

// --- runTransaction ----------------------------------------------------------

test("runTransaction runs through project.lockedAccess when host provides it", () => {
  const calls = [];
  const project = {
    lockedAccess: (run) => { calls.push("locked"); run(); },
    executeTransaction: (fn, label) => { calls.push(label); fn({ addAction: () => true }); return true; },
  };
  runTransaction(project, "Test: Action", () => {});
  assert.deepEqual(calls, ["locked", "Test: Action"]);
});

test("runTransaction runs directly when project.lockedAccess is absent", () => {
  const calls = [];
  const project = {
    executeTransaction: (fn, label) => { calls.push(label); fn({ addAction: () => true }); return true; },
  };
  runTransaction(project, "Direct: Action", () => {});
  assert.deepEqual(calls, ["Direct: Action"]);
});

test("runTransaction throws when executeTransaction returns false", () => {
  const project = {
    executeTransaction: () => false,
  };
  assert.throws(
    () => runTransaction(project, "Failing Action", () => {}),
    /Could not complete "Failing Action"/
  );
});

test("runTransaction preserves and rethrows exception from executeTransaction", () => {
  const project = {
    executeTransaction: () => {
      throw new Error("Custom transaction error");
    },
  };
  assert.throws(
    () => runTransaction(project, "Throwing Action", () => {}),
    /Custom transaction error/
  );
});

test("runTransaction throws if project is missing", () => {
  assert.throws(
    () => runTransaction(null, "No project", () => {}),
    /Open a Premiere project first/
  );
});

// --- getOrCreateBin ----------------------------------------------------------

function createFakeBin(name, initialItems = []) {
  const items = [...initialItems];
  return {
    name,
    getItems: async () => items,
    createBinAction: (childName) => ({ __createBin: true, childName, parent: name }),
    _items: items,
  };
}

function createFakeProject(root) {
  let transactionsRun = 0;
  return {
    getRootItem: async () => root,
    executeTransaction: (build, label) => {
      transactionsRun++;
      const compound = {
        addAction: (action) => {
          if (action && action.__createBin) {
            const newBin = createFakeBin(action.childName);
            // Add to the right parent items
            action.parentBinRef._items.push(newBin);
            return true;
          }
          return false;
        },
      };
      // We pass the parent bin ref through wrapper if needed
      build(compound);
      return true;
    },
    transactionsRun: () => transactionsRun,
  };
}

test("getOrCreateBin returns root if pathArray is empty", async () => {
  const root = createFakeBin("Root");
  const project = { getRootItem: async () => root };
  const bin = await getOrCreateBin(project, []);
  assert.equal(bin, root);
});

test("getOrCreateBin finds existing bin without executing transaction", async () => {
  const existing = createFakeBin("CutDeck");
  const root = createFakeBin("Root", [existing]);
  let txCalled = false;
  const project = {
    getRootItem: async () => root,
    executeTransaction: () => { txCalled = true; return true; },
  };
  const bin = await getOrCreateBin(project, ["CutDeck"]);
  assert.equal(bin, existing);
  assert.equal(txCalled, false);
});

test("getOrCreateBin creates missing single bin via transaction", async () => {
  const root = createFakeBin("Root");
  let txRan = false;
  const project = {
    getRootItem: async () => root,
    executeTransaction: (build) => {
      txRan = true;
      build({
        addAction: (action) => {
          root._items.push(createFakeBin(action.childName));
          return true;
        },
      });
      return true;
    },
  };
  const bin = await getOrCreateBin(project, ["CutDeck"]);
  assert.equal(txRan, true);
  assert.equal(bin.name, "CutDeck");
  assert.equal(root._items.length, 1);
});

test("getOrCreateBin creates nested bin hierarchy", async () => {
  const root = createFakeBin("Root");
  let currentParent = root;
  const project = {
    getRootItem: async () => root,
    executeTransaction: (build) => {
      build({
        addAction: (action) => {
          const newBin = createFakeBin(action.childName);
          currentParent._items.push(newBin);
          currentParent = newBin;
          return true;
        },
      });
      return true;
    },
  };
  const nested = await getOrCreateBin(project, ["CutDeck", "ADJ & FX"]);
  assert.equal(nested.name, "ADJ & FX");
  assert.equal(root._items[0].name, "CutDeck");
  assert.equal(root._items[0]._items[0].name, "ADJ & FX");
});

test("getOrCreateBin throws user-facing error when transaction fails", async () => {
  const root = createFakeBin("Root");
  const project = {
    getRootItem: async () => root,
    executeTransaction: () => false,
  };
  await assert.rejects(
    getOrCreateBin(project, ["CutDeck"]),
    /Could not create the "CutDeck" bin in this project/
  );
});

test("getOrCreateBin throws if created bin cannot be found afterward", async () => {
  const root = createFakeBin("Root");
  const project = {
    getRootItem: async () => root,
    executeTransaction: () => true, // claims success, but doesn't add item to root
  };
  await assert.rejects(
    getOrCreateBin(project, ["CutDeck"]),
    /"CutDeck" bin was created but could not be found afterward/
  );
});

test("getOrCreateBin throws if project is missing or pathArray is invalid", async () => {
  await assert.rejects(getOrCreateBin(null, ["CutDeck"]), /Open a Premiere project first/);
  await assert.rejects(getOrCreateBin({}, "invalid"), /pathArray must be an array/);
});

// --- activeProjectAndSequence ------------------------------------------------

test("activeProjectAndSequence throws if project is null (requireProject: true)", async () => {
  const ppro = { Project: { getActiveProject: async () => null } };
  await assert.rejects(
    activeProjectAndSequence(ppro),
    /Open a Premiere project first/
  );
});

test("activeProjectAndSequence returns nulls if project is null and requireProject is false", async () => {
  const ppro = { Project: { getActiveProject: async () => null } };
  const res = await activeProjectAndSequence(ppro, { requireProject: false });
  assert.deepEqual(res, { project: null, sequence: null });
});

test("activeProjectAndSequence throws default sequence error when sequence is missing", async () => {
  const project = { getActiveSequence: async () => null };
  const ppro = { Project: { getActiveProject: async () => project } };
  await assert.rejects(
    activeProjectAndSequence(ppro),
    /Open a sequence first/
  );
});

test("activeProjectAndSequence uses custom sequence error message when provided", async () => {
  const project = { getActiveSequence: async () => null };
  const ppro = { Project: { getActiveProject: async () => project } };
  await assert.rejects(
    activeProjectAndSequence(ppro, { sequenceErrorMessage: "Custom sequence error." }),
    /Custom sequence error\./
  );
});

test("activeProjectAndSequence returns null sequence when requireSequence is false", async () => {
  const project = { getActiveSequence: async () => null };
  const ppro = { Project: { getActiveProject: async () => project } };
  const res = await activeProjectAndSequence(ppro, { requireSequence: false });
  assert.deepEqual(res, { project, sequence: null });
});

test("activeProjectAndSequence returns both project and sequence when present", async () => {
  const sequence = { name: "Timeline 1" };
  const project = { getActiveSequence: async () => sequence };
  const ppro = { Project: { getActiveProject: async () => project } };
  const res = await activeProjectAndSequence(ppro);
  assert.deepEqual(res, { project, sequence });
});
