// Investigation only. Profile: Premiere executable SHA-256
// b24e2b442a8e0350edbc0c214d2fcae2f68c7d9843ae399e5058d5b5a6786094.
// Observes constructors and layout; never calls a native function or changes values.
const image = Process.getModuleByName("Adobe Premiere Pro.exe");
if (typeof Checksum === "undefined" || typeof Checksum.compute !== "function") {
  throw new Error("An in-process checksum implementation is required; source bytes are never sent.");
}
const documents = new Map();
let nextId = 1;
let layoutCount = 0;
let factoryCount = 0;

function checkedAddress(rva, expected) {
  const address = image.base.add(rva);
  const bytes = Array.from(new Uint8Array(address.readByteArray(expected.length)));
  if (!expected.every((value, i) => bytes[i] === value)) {
    throw new Error(`Profile mismatch at RVA ${rva.toString(16)}`);
  }
  return address;
}

const factory = checkedAddress(0x195a3b50, [0x48, 0x8b, 0xc4]);
const acquireLayout = checkedAddress(0x1ba78320, [0x48, 0x89, 0x5c, 0x24, 0x18]);
const destroyDocument = checkedAddress(0x199b6410, [0x48, 0x8b, 0x09, 0x48, 0x85, 0xc9]);

Interceptor.attach(destroyDocument, {
  onEnter(args) {
    const key = args[0].toString();
    const record = documents.get(key);
    documents.delete(key);
    if (record) send({ kind: "document-destroyed", document: key, sourceId: record.id });
  },
});

Interceptor.attach(factory, {
  onEnter(args) {
    this.observe = false;
    this.out = args[0];
    const withinLimit = factoryCount++ < 512;
    try {
      const size = args[2].toUInt32();
      if (size < 16 || size > 65536 || !withinLimit) return;
      if (args[1].add(8).readU32() !== 0x11223344) return;
      this.out = args[0];
      this.sourceSha256 = Checksum.compute("sha256", args[1].readByteArray(size));
      this.sourceByteCount = size;
      this.observe = true;
    } catch (error) {
      send({ kind: "factory-read-error", error: String(error) });
    }
  },
  onLeave() {
    try {
      const document = this.out.readPointer();
      if (document.isNull()) return;
      documents.delete(document.toString());
      if (!this.observe) return;
      const record = { id: nextId++, sourceSha256: this.sourceSha256,
        sourceByteCount: this.sourceByteCount };
      documents.set(document.toString(), record);
      send({ kind: "document-created", document: document.toString(), ...record });
    } catch (error) {
      send({ kind: "factory-result-error", error: String(error) });
    }
  },
});

Interceptor.attach(acquireLayout, {
  onEnter(args) {
    this.observe = layoutCount++ < 256;
    if (!this.observe) return;
    this.out = args[0];
    try {
      // Traced chain: layout input -> owner -> shared TextDocument pointer.
      this.document = args[1].readPointer().readPointer().toString();
      this.record = documents.get(this.document) || null;
    } catch (error) {
      this.observe = false;
      send({ kind: "layout-owner-error", error: String(error) });
    }
  },
  onLeave() {
    if (!this.observe) return;
    try {
      const liveRecord = this.record && documents.get(this.document) === this.record
        ? this.record : null;
      const layout = this.out.readPointer();
      if (layout.isNull()) {
        send({ kind: "layout-empty", document: this.document, sourceId: liveRecord?.id || null });
        return;
      }
      const begin = layout.add(0xbd0).readPointer();
      const end = layout.add(0xbd8).readPointer();
      const size = end.sub(begin).toInt32();
      if (size < 0 || size % 20 !== 0 || size > 20480) {
        send({ kind: "layout-vector-rejected", size });
        return;
      }
      const rectangles = [];
      for (let i = 0; i < size / 20; i++) {
        rectangles.push([4, 8, 12, 16].map((offset) => begin.add(i * 20 + offset).readFloat()));
      }
      send({ kind: "document-layout", document: this.document,
        sourceId: liveRecord?.id || null, rectangles,
        paragraphFlag: layout.add(0x10).readU8() });
    } catch (error) {
      send({ kind: "layout-result-error", error: String(error) });
    }
  },
});

send({ kind: "document-layout-observer-ready", base: image.base.toString(),
  limits: { factoryCalls: 512, layoutCalls: 256, sourceBytes: 65536, rectangles: 1024 } });
