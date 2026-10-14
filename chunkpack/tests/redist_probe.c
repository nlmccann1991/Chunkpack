/* Test stand-in for a redistributable: writes its command line to
 * redist_ran.txt next to itself so tests can see that [Run] executed it. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>

int main(void)
{
    wchar_t path[MAX_PATH];
    DWORD n = GetModuleFileNameW(NULL, path, MAX_PATH), written;
    while (n && path[n - 1] != L'\\')
        n--;
    lstrcpyW(path + n, L"redist_ran.txt");
    HANDLE f = CreateFileW(path, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, 0, NULL);
    if (f == INVALID_HANDLE_VALUE)
        return 1;
    const wchar_t *cmd = GetCommandLineW();
    WriteFile(f, cmd, lstrlenW(cmd) * sizeof(wchar_t), &written, NULL);
    CloseHandle(f);
    return 0;
}
