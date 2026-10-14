# Reverse-engineering notes for the Mouse PI GOG installer (Inno Setup 5.6.x, GOG build).
# Usage: python3 -I inno5_header_blocks.py setup.exe outdir  - decodes the two setup header blocks (Offset0 = 0x2f000 for Mouse PI).
import sys, struct, zlib, lzma
exe, out = sys.argv[1], sys.argv[2]
data = open(exe,'rb').read()
pos = 0x2f000 + 64          # past "Inno Setup Setup Data (5.6.2) (u)" ID
for n in range(2):
    hcrc, stored, comp = struct.unpack_from('<IIB', data, pos)
    ok = zlib.crc32(data[pos+4:pos+9]) & 0xffffffff == hcrc
    print(f"block {n} @ {pos:#x}: StoredSize={stored} Compressed={comp} headerCRC ok={ok}")
    pos += 9; end = pos + stored; payload = b''; chunks = 0; bad = 0
    while pos < end:
        crc = struct.unpack_from('<I', data, pos)[0]; pos += 4
        c = data[pos:min(pos+4096, end)]; pos += len(c); chunks += 1
        bad += (zlib.crc32(c) & 0xffffffff) != crc
        payload += c
    print(f"   {chunks} chunks of <=4096 bytes, each CRC32-prefixed; bad CRCs: {bad}")
    if not comp:
        open(f"{out}/block{n}.bin","wb").write(payload); print("   stored raw"); continue
    props = payload[:5]
    raw = lzma.LZMADecompressor(lzma.FORMAT_ALONE).decompress(props + b'\xff'*8 + payload[5:])
    lc = props[0] % 9; lp = (props[0]//9) % 5; pb = props[0]//45
    print(f"   LZMA1 props lc={lc} lp={lp} pb={pb} dict={struct.unpack_from('<I',props,1)[0]}; decompressed {len(raw)} bytes")
    open(f"{out}/block{n}.bin",'wb').write(raw)
print("data after blocks @", hex(pos), data[pos:pos+16])
