// One zip from pre-built entry blocks (build/zipblocks.py). Only headers and the central
// directory are written here; every block's bytes are passed through unchanged.

const LOCAL_SIG = 0x04034b50;
const CENTRAL_SIG = 0x02014b50;
const END_SIG = 0x06054b50;
const MAX = 0xfffffffe; // no Zip64
const encoder = new TextEncoder();

export class LayoutError extends Error {}

function localHeader(entry, nameBytes) {
  const header = new DataView(new ArrayBuffer(30 + nameBytes.length));
  header.setUint32(0, LOCAL_SIG, true);
  header.setUint16(4, entry.version, true);
  header.setUint16(6, entry.flags, true);
  header.setUint16(8, entry.method, true);
  header.setUint16(10, entry.time, true);
  header.setUint16(12, entry.date, true);
  header.setUint32(14, entry.crc, true);
  header.setUint32(18, entry.csize, true);
  header.setUint32(22, entry.usize, true);
  header.setUint16(26, nameBytes.length, true);
  header.setUint16(28, 0, true);
  const bytes = new Uint8Array(header.buffer);
  bytes.set(nameBytes, 30);
  return bytes;
}

function centralHeader(entry, nameBytes, offset) {
  const header = new DataView(new ArrayBuffer(46 + nameBytes.length));
  header.setUint32(0, CENTRAL_SIG, true);
  header.setUint16(4, (3 << 8) | 20, true); // made by: unix, 2.0 (keeps external_attr modes)
  header.setUint16(6, entry.version, true);
  header.setUint16(8, entry.flags, true);
  header.setUint16(10, entry.method, true);
  header.setUint16(12, entry.time, true);
  header.setUint16(14, entry.date, true);
  header.setUint32(16, entry.crc, true);
  header.setUint32(20, entry.csize, true);
  header.setUint32(24, entry.usize, true);
  header.setUint16(28, nameBytes.length, true);
  header.setUint16(30, 0, true); // extra
  header.setUint16(32, 0, true); // comment
  header.setUint16(34, 0, true); // disk
  header.setUint16(36, 0, true); // internal attributes
  header.setUint32(38, entry.external_attr >>> 0, true);
  header.setUint32(42, offset, true);
  const bytes = new Uint8Array(header.buffer);
  bytes.set(nameBytes, 46);
  return bytes;
}

function endRecord(count, size, offset) {
  const end = new DataView(new ArrayBuffer(22));
  end.setUint32(0, END_SIG, true);
  end.setUint16(8, count, true);
  end.setUint16(10, count, true);
  end.setUint32(12, size, true);
  end.setUint32(16, offset, true);
  return new Uint8Array(end.buffer);
}

function concat(chunks) {
  const out = new Uint8Array(chunks.reduce((n, c) => n + c.length, 0));
  let at = 0;
  for (const c of chunks) {
    out.set(c, at);
    at += c.length;
  }
  return out;
}

/**
 * The parts of the zip, in order: Uint8Arrays to write, and {key, size} objects to stream from R2.
 * runner: {prefix, layout} or null for a bundle (no exe); blocks: [{prefix, layout, allow?}]
 * (layers, then the pack); allow, a RegExp, is what entry names that block may hold.
 * exeName: "MakePDF.exe" when there is a runner.
 */
export function planZip(runner, blocks, exeName) {
  const parts = [];
  const central = [];
  const names = new Set();
  let offset = 0;

  if (runner) {
    if (!runner.layout?.exe) throw new LayoutError("runner layout has no exe");
    const exe = runner.layout.exe;
    const exeBytes = encoder.encode(exeName);
    const header = localHeader(exe, exeBytes);
    parts.push(header, { key: `${runner.prefix}/exe.bin`, size: exe.csize });
    central.push(centralHeader(exe, exeBytes, 0));
    names.add(exeName.toLowerCase());
    offset += header.length + exe.csize;
  }

  for (const block of runner ? [runner, ...blocks] : blocks) {
    const { layout, prefix, allow } = block;
    if (layout?.format !== 1 || !Array.isArray(layout.entries)) throw new LayoutError(`bad layout in ${prefix}`);
    parts.push({ key: `${prefix}/blocks.bin`, size: layout.size });
    for (const entry of layout.entries) {
      if (allow && !allow.test(entry.name)) throw new LayoutError(`unexpected entry in ${prefix}`);
      const lower = entry.name.toLowerCase();
      if (names.has(lower)) throw new LayoutError(`two entries named ${entry.name}`);
      if (entry.offset < 0 || entry.offset >= layout.size) throw new LayoutError(`bad offset in ${prefix}`);
      names.add(lower);
      central.push(centralHeader(entry, encoder.encode(entry.name), offset + entry.offset));
    }
    offset += layout.size;
  }
  const directory = concat(central);
  if (offset > MAX || offset + directory.length > MAX || central.length > 0xffff) {
    throw new LayoutError("download too large for a zip without Zip64");
  }
  parts.push(directory, endRecord(central.length, directory.length, offset));
  const size = parts.reduce((n, p) => n + (p instanceof Uint8Array ? p.length : p.size), 0);
  return { parts, size };
}
