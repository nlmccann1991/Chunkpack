# Reverse-engineering notes for the Mouse PI GOG installer (Inno Setup 5.6.x, GOG build).
# Usage: python3 -I inno5_setup_e32.py setup.exe out.e32  - unpacks setup.e32 (OffsetEXE = 0x2197fd for Mouse PI) and undoes the CALL transform.
import sys, struct, zlib, lzma
data = open(sys.argv[1],'rb').read(); pos = 0x2197fd
hcrc, stored, comp = struct.unpack_from('<IIB', data, pos)
print(f"setup.e32 block: StoredSize={stored} Compressed={comp} hdrCRC ok={zlib.crc32(data[pos+4:pos+9])&0xffffffff==hcrc}; ends at {pos+9+stored} (TotalSize=2670230)")
pos += 9; end = pos+stored; p=b''
while pos < end:
    pos += 4; c = data[pos:min(pos+4096,end)]; pos += len(c); p += c
raw = lzma.LZMADecompressor(lzma.FORMAT_ALONE).decompress(p[:5]+b'\xff'*8+p[5:])
print("decompressed", len(raw), "bytes; starts", raw[:2])
# undo Inno's x86 CALL/JMP address transform (TransformCallInstructions, 5.2+ flavour)
b = bytearray(raw); i = 0; n = len(b)
while i < n - 4:
    if b[i] in (0xE8, 0xE9):
        addr = i + 5
        if b[i+4] in (0x00, 0xFF):
            rel = b[i+1] | b[i+2]<<8 | b[i+3]<<16
            rel = (rel - addr) & 0xFFFFFF  # decode: subtract
            b[i+1], b[i+2], b[i+3] = rel & 0xFF, (rel>>8)&0xFF, (rel>>16)&0xFF
            if rel & 0x800000: b[i+4] ^= 0xFF  # sign-extend into the top byte
        i += 5
    else: i += 1
print("CRC raw", hex(zlib.crc32(raw)&0xffffffff), "CRC untransformed", hex(zlib.crc32(bytes(b))&0xffffffff), "expected 0x78ffe9a1")
open(sys.argv[2],'wb').write(b)
