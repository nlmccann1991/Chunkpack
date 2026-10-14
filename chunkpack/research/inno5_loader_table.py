# Reverse-engineering notes for the Mouse PI GOG installer (Inno Setup 5.6.x, GOG build).
# Usage: python3 -I inno5_loader_table.py setup.exe  - PE resources, SetupLdrOffsetTable, .bin slice headers.
import sys, os, struct, zlib, pefile, glob
exe = sys.argv[1]; d = os.path.dirname(exe)
data = open(exe,'rb').read()
pe = pefile.PE(exe)
print(f"exe size {len(data)}  ({len(data):#x})")
last = max(s.PointerToRawData+s.SizeOfRawData for s in pe.sections)
print(f"end of PE sections {last:#x}; overlay starts there")
sec = pe.OPTIONAL_HEADER.DATA_DIRECTORY[4]
print(f"Authenticode cert table: offset {sec.VirtualAddress:#x} size {sec.Size}")
# resources
for t in pe.DIRECTORY_ENTRY_RESOURCE.entries:
    tn = pefile.RESOURCE_TYPE.get(t.id, t.name)
    for e in t.directory.entries:
        en = e.name if e.name else e.id
        for l in e.directory.entries:
            r = l.data.struct
            print(f"  res {tn}/{en}/{l.id}  size {r.Size}")
            if tn=='RT_RCDATA' and en==11111:
                b = pe.get_data(r.OffsetToData, r.Size)
                print("   SetupLdrOffsetTable raw:", b.hex())
                sig = b[:12]
                ver, totsize, offexe, uncomp, crcexe, off0, off1, tcrc = struct.unpack_from('<IIIIIIII', b, 12)
                print(f"   ID={sig!r} version={ver} TotalSize={totsize} OffsetEXE={offexe:#x} UncompSizeEXE={uncomp} CRCEXE={crcexe:#x} Offset0={off0:#x} Offset1={off1:#x} TableCRC={tcrc:#x}")
                print("   table CRC ok:", zlib.crc32(b[:-4]) & 0xffffffff == tcrc)
                globals().update(offexe=offexe, off0=off0, off1=off1, uncomp=uncomp, crcexe=crcexe)
print("bytes @OffsetEXE:", data[offexe:offexe+8].hex(), "(zlb/lzma-compressed setup.e32)")
print("bytes @Offset0  :", data[off0:off0+64])
print("Offset1 = 0 means file data lives in external .bin slices, not inside exe" if off1==0 else f"Offset1 {off1:#x}")
for b in sorted(glob.glob(os.path.join(d,'*.bin'))):
    h = open(b,'rb').read(16); sz = os.path.getsize(b)
    print(os.path.basename(b), h[:8], "declared", struct.unpack_from('<I',h,8)[0], "actual", sz)
