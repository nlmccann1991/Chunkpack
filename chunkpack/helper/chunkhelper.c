/*
 * chunkhelper.dll - native helper loaded by chunkpack installers.
 *
 * Inno Setup extracts a file's Galaxy-style parts (independent zlib streams)
 * into {tmp}; the [Code] section then calls MergeParts once per file to
 * inflate them in order into the final destination.
 *
 *   int __stdcall MergeParts(const wchar_t *parts, const wchar_t *dest,
 *                            const wchar_t *fileMd5);
 *
 * parts:   one record per line ("\n"), fields "path|inflatedSize|inflatedMd5"
 * dest:    final file path; written to dest + ".cpk-tmp" first, then renamed
 * fileMd5: expected MD5 (hex) of the whole inflated file
 *
 * Returns 0 on success (part files are deleted), otherwise a CH_* code.
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <wincrypt.h>
#include "third_party/miniz/miniz.h"

enum {
    CH_OK = 0,
    CH_BAD_ARGS = 1,
    CH_OPEN_PART = 2,
    CH_READ_PART = 3,
    CH_INFLATE = 4,
    CH_PART_SIZE = 5,
    CH_PART_MD5 = 6,
    CH_CREATE_DEST = 7,
    CH_WRITE_DEST = 8,
    CH_FILE_MD5 = 9,
    CH_RENAME = 10,
    CH_NO_MEMORY = 11,
    CH_CRYPTO = 12,
};

#define MAX_PARTS 65536

typedef struct {
    const wchar_t *path;
    DWORD size;
    const wchar_t *md5;
} part_t;

static HCRYPTPROV g_prov;

static int md5_new(HCRYPTHASH *h)
{
    if (!g_prov && !CryptAcquireContextW(&g_prov, NULL, NULL, PROV_RSA_FULL, CRYPT_VERIFYCONTEXT))
        return 0;
    return CryptCreateHash(g_prov, CALG_MD5, 0, 0, h);
}

/* Finishes the hash and compares it with a hex string, ignoring case. */
static int md5_matches(HCRYPTHASH h, const wchar_t *expected)
{
    static const char hex[] = "0123456789abcdef";
    BYTE digest[16];
    DWORD len = sizeof digest;
    int ok = CryptGetHashParam(h, HP_HASHVAL, digest, &len, 0);
    CryptDestroyHash(h);
    if (!ok)
        return 0;
    for (int i = 0; i < 16; i++) {
        wchar_t hi = expected[2 * i], lo = hi ? expected[2 * i + 1] : 0;
        if ((hi | 0x20) != hex[digest[i] >> 4] || (lo | 0x20) != hex[digest[i] & 15])
            return 0;
    }
    return expected[32] == 0;
}

/* Splits the mutable parts buffer in place into records. Returns count or -1. */
static int parse_parts(wchar_t *s, part_t *out)
{
    int n = 0;
    while (*s) {
        wchar_t *line = s, *bar1, *bar2;
        while (*s && *s != L'\n')
            s++;
        if (*s)
            *s++ = 0;
        if (!*line)
            continue;
        if (n == MAX_PARTS || !(bar1 = wcschr(line, L'|')) || !(bar2 = wcschr(bar1 + 1, L'|')))
            return -1;
        *bar1 = *bar2 = 0;
        out[n].path = line;
        out[n].size = (DWORD)wcstoul(bar1 + 1, NULL, 10);
        out[n].md5 = bar2 + 1;
        n++;
    }
    return n;
}

static int read_all(const wchar_t *path, BYTE **data, DWORD *size)
{
    HANDLE f = CreateFileW(path, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING,
                           FILE_FLAG_SEQUENTIAL_SCAN, NULL);
    LARGE_INTEGER len;
    DWORD got = 0, n;
    if (f == INVALID_HANDLE_VALUE)
        return CH_OPEN_PART;
    if (!GetFileSizeEx(f, &len) || len.QuadPart > 0x7fffffff) {
        CloseHandle(f);
        return CH_READ_PART;
    }
    *size = (DWORD)len.QuadPart;
    if (!(*data = HeapAlloc(GetProcessHeap(), 0, *size ? *size : 1))) {
        CloseHandle(f);
        return CH_NO_MEMORY;
    }
    while (got < *size && ReadFile(f, *data + got, *size - got, &n, NULL) && n)
        got += n;
    CloseHandle(f);
    return got == *size ? CH_OK : CH_READ_PART;
}

static int write_all(HANDLE f, const BYTE *data, DWORD size)
{
    DWORD done = 0, n;
    while (done < size && WriteFile(f, data + done, size - done, &n, NULL) && n)
        done += n;
    return done == size;
}

/* Inflates one part, checks its size and MD5, and appends it to out. */
static int merge_one(const part_t *p, HANDLE out, HCRYPTHASH whole)
{
    BYTE *src = NULL, *dst = NULL;
    DWORD srcLen = 0;
    mz_ulong dstLen = p->size, used;
    HCRYPTHASH h;
    int rc = read_all(p->path, &src, &srcLen);
    if (rc)
        goto done;
    rc = CH_NO_MEMORY;
    if (!(dst = HeapAlloc(GetProcessHeap(), 0, p->size ? p->size : 1)))
        goto done;
    used = srcLen;
    rc = CH_INFLATE;
    if (mz_uncompress2(dst, &dstLen, src, &used) != MZ_OK || used != srcLen)
        goto done;
    rc = CH_PART_SIZE;
    if (dstLen != p->size)
        goto done;
    rc = CH_CRYPTO;
    if (!md5_new(&h))
        goto done;
    if (!CryptHashData(h, dst, dstLen, 0)) {
        CryptDestroyHash(h);
        goto done;
    }
    rc = CH_PART_MD5;
    if (!md5_matches(h, p->md5))
        goto done;
    rc = CH_CRYPTO;
    if (!CryptHashData(whole, dst, dstLen, 0))
        goto done;
    rc = write_all(out, dst, dstLen) ? CH_OK : CH_WRITE_DEST;
done:
    if (src)
        HeapFree(GetProcessHeap(), 0, src);
    if (dst)
        HeapFree(GetProcessHeap(), 0, dst);
    return rc;
}

__declspec(dllexport) int __stdcall MergeParts(const wchar_t *parts, const wchar_t *dest,
                                               const wchar_t *fileMd5)
{
    static part_t list[MAX_PARTS];
    wchar_t *buf = NULL, *tmp = NULL;
    HANDLE out = INVALID_HANDLE_VALUE;
    HCRYPTHASH whole = 0;
    int n, rc = CH_BAD_ARGS;
    size_t plen, dlen;

    if (!parts || !dest || !fileMd5 || !*dest)
        return CH_BAD_ARGS;
    plen = wcslen(parts) + 1;
    dlen = wcslen(dest);
    buf = HeapAlloc(GetProcessHeap(), 0, plen * sizeof(wchar_t));
    tmp = HeapAlloc(GetProcessHeap(), 0, (dlen + 9) * sizeof(wchar_t));
    rc = CH_NO_MEMORY;
    if (!buf || !tmp)
        goto done;
    memcpy(buf, parts, plen * sizeof(wchar_t));
    memcpy(tmp, dest, dlen * sizeof(wchar_t));
    memcpy(tmp + dlen, L".cpk-tmp", 9 * sizeof(wchar_t));

    rc = CH_BAD_ARGS;
    if ((n = parse_parts(buf, list)) <= 0)
        goto done;
    rc = CH_CRYPTO;
    if (!md5_new(&whole))
        goto done;
    rc = CH_CREATE_DEST;
    out = CreateFileW(tmp, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (out == INVALID_HANDLE_VALUE)
        goto done;
    for (int i = 0; i < n; i++)
        if ((rc = merge_one(&list[i], out, whole)))
            goto done;
    CloseHandle(out);
    out = INVALID_HANDLE_VALUE;
    rc = md5_matches(whole, fileMd5) ? CH_OK : CH_FILE_MD5;
    whole = 0;
    if (rc)
        goto done;
    rc = MoveFileExW(tmp, dest, MOVEFILE_REPLACE_EXISTING) ? CH_OK : CH_RENAME;
    if (rc == CH_OK)
        for (int i = 0; i < n; i++)
            DeleteFileW(list[i].path);
done:
    if (out != INVALID_HANDLE_VALUE)
        CloseHandle(out);
    if (whole)
        CryptDestroyHash(whole);
    if (rc && tmp)
        DeleteFileW(tmp);
    if (buf)
        HeapFree(GetProcessHeap(), 0, buf);
    if (tmp)
        HeapFree(GetProcessHeap(), 0, tmp);
    return rc;
}
