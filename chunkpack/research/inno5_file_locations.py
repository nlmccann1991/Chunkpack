# Reverse-engineering notes for the Mouse PI GOG installer (Inno Setup 5.6.x, GOG build).
# Usage: python3 -I inno5_file_locations.py block1.bin  - parses the 74-byte file location records.
import sys, struct, collections
b = open(sys.argv[1],'rb').read(); SZ = 74
print(f"{len(b)} bytes / {SZ} = {len(b)/SZ}")
FL = ['VersionInfoValid','VersionInfoNotValid','TimeStampInUTC','IsUninstExe','CallInstructionOptimized','Touch','ChunkEncrypted','ChunkCompressed','SolidBreak','Sign','SignOnce']
ents = []
for i in range(0, len(b), SZ):
    first, last, start, sub, orig, csize = struct.unpack_from('<IIIQQQ', b, i)
    sha1 = b[i+36:i+56]; ts, vms, vls, flags = struct.unpack_from('<QIIH', b, i+56)
    ents.append((first,last,start,sub,orig,csize,sha1,flags))
chunks = collections.OrderedDict()
for e in ents: chunks.setdefault((e[0],e[2]), []).append(e)
print("entries:", len(ents), " distinct chunks:", len(chunks))
print("slices referenced:", sorted({e[0] for e in ents} | {e[1] for e in ents}))
print("total uncompressed: %.2f GB" % (sum(e[4] for e in ents)/1e9))
print("total chunk compressed (unique): %.2f GB" % (sum(v[0][5] for v in chunks.values())/1e9))
fc = collections.Counter(); 
for e in ents:
    for k,n in enumerate(FL):
        if e[7] >> k & 1: fc[n]+=1
print("flag counts:", dict(fc))
print("spanning chunks (first!=last slice):", sum(1 for v in chunks.values() if v[0][0]!=v[0][1]))
print("first 5 entries:")
for e in ents[:5]: print("  slice %d-%d start=%d sub=%d size=%d csize=%d sha1=%s flags=%#x" % (e[0],e[1],e[2],e[3],e[4],e[5],e[6].hex()[:16],e[7]))
big = max(chunks.values(), key=len); print("largest solid chunk holds", len(big), "files")
