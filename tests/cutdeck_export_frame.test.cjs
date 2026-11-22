"use strict";
// export_frame writes its check frames beside the .prproj (CutDeck\Frames), not in the panel's
// temp folder, so they stay with the project and the user can clear them (user, 2026-11-22).

const test = require("node:test");
const assert = require("node:assert/strict");
const Module = require("node:module");

function fakeFolder(nativePath, children = {}) {
  return {
    isFolder: true,
    nativePath,
    children,
    getEntry: async (name) => {
      if (children[name]) return children[name];
      throw new Error(`no ${name}`);
    },
    createFolder: async (name) => (children[name] = fakeFolder(`${nativePath}\\${name}`)),
  };
}

const temp = fakeFolder("C:\\Temp\\PluginData");
let projectFolder = null;
const stubs = {
  uxp: {
    storage: {
      localFileSystem: {
        getTemporaryFolder: async () => temp,
        getEntryWithUrl: async () => projectFolder,
      },
    },
  },
};
const realLoad = Module._load;
Module._load = function (request, ...rest) {
  if (Object.prototype.hasOwnProperty.call(stubs, request)) return stubs[request];
  return realLoad.call(this, request, ...rest);
};
test.after(() => { Module._load = realLoad; });

const { controlHandlers } = require("../uxp/cutdeck/timeline/control.js");

function fakePpro(projectPath) {
  const sequence = {
    name: "TT short",
    getPlayerPosition: async () => ({ ticks: "0" }),
    getFrameSize: async () => ({ width: 1080, height: 1920 }),
  };
  const project = { path: projectPath, getActiveSequence: async () => sequence, getSequences: async () => [sequence] };
  const writes = [];
  const ppro = {
    Project: { getActiveProject: async () => project },
    TickTime: { createWithTicks: (t) => ({ ticks: t }) },
    Exporter: {
      exportSequenceFrame: async (seq, at, file, dir) => {
        writes.push({ file, dir });
        const folder = [temp, projectFolder, projectFolder && projectFolder.children.CutDeck,
          projectFolder && projectFolder.children.CutDeck && projectFolder.children.CutDeck.children.Frames]
          .find((f) => f && f.nativePath === dir);
        folder.children[file] = { getMetadata: async () => ({ size: 2048 }) };
        return true;
      },
    },
  };
  return { ppro, writes };
}

test("export_frame: a saved project's frame goes to CutDeck\\Frames beside the .prproj", async () => {
  projectFolder = fakeFolder("E:\\Show\\PREMIERE PRO");
  const { ppro, writes } = fakePpro("E:\\Show\\PREMIERE PRO\\show.prproj");
  const out = await controlHandlers(ppro).export_frame({ ticks: "0" });
  assert.equal(writes[0].dir, "E:\\Show\\PREMIERE PRO\\CutDeck\\Frames");
  assert.match(out.path, /^E:\\Show\\PREMIERE PRO\\CutDeck\\Frames\\cutdeck-frame-\d+\.png$/);
  assert.equal(out.bytes, 2048);
  // the folder is made once and reused
  await controlHandlers(ppro).export_frame({ ticks: "0" });
  assert.equal(writes[1].dir, writes[0].dir);
});

test("export_frame: an unsaved project still uses the temp folder", async () => {
  projectFolder = null;
  const { ppro, writes } = fakePpro("");
  const out = await controlHandlers(ppro).export_frame({ ticks: "0" });
  assert.equal(writes[0].dir, "C:\\Temp\\PluginData");
  assert.match(out.path, /^C:\\Temp\\PluginData\\cutdeck-frame-\d+\.png$/);
});
