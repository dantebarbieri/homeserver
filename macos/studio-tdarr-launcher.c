/*
 * Launchd job program for com.danteb.studio-tdarr.
 *
 * macOS checks a file access (Full Disk Access, which covers SMB volumes) against
 * the "responsible process" of the caller. Apple's own programs (bash, sudo, cron)
 * do not hand that responsibility to the non-Apple programs they start, so a
 * LaunchDaemon whose program is /bin/bash leaves Tdarr and ffmpeg unable to open a
 * single file on the media mount (EPERM). A non-Apple job program does hand it on:
 * every process below this one is attributed to this binary, so one Full Disk
 * Access grant for this file covers the whole node.
 *
 * It does nothing else. It must be started by launchd as root, and it only execs
 * /bin/bash on one root-owned script in /Library/PrivilegedHelperTools, so the
 * grant cannot be used to run anything else. Any change to this file changes its
 * code hash and silently voids the grant, so behaviour belongs in the script.
 *
 * Build, as the admin user (any change to the binary voids the grant, so rebuild only when the
 * source changes, then install root:wheel 0755 and grant Full Disk Access to the installed path):
 *   clang -O2 -Wall -o com.danteb.studio-tdarr-launcher studio-tdarr-launcher.c
 *   codesign --force --sign - --identifier com.danteb.studio-tdarr-launcher com.danteb.studio-tdarr-launcher
 */
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#define SCRIPT_DIR "/Library/PrivilegedHelperTools"
#define SCRIPT_PREFIX SCRIPT_DIR "/com.danteb.studio-"

static int fail(const char *what, const char *detail)
{
    fprintf(stderr, "studio-tdarr-launcher: %s%s%s\n", what, detail ? ": " : "", detail ? detail : "");
    return 78;
}

static int root_only(const struct stat *st)
{
    return st->st_uid == 0 && !(st->st_mode & (S_IWGRP | S_IWOTH));
}

int main(int argc, char **argv)
{
    struct stat st;

    if (argc != 2)
        return fail("usage", "studio-tdarr-launcher <script>");
    if (geteuid() != 0 || getppid() != 1)
        return fail("refusing to run", "start it from system launchd as root");

    const char *script = argv[1];
    if (strncmp(script, SCRIPT_PREFIX, strlen(SCRIPT_PREFIX)) != 0 ||
        strchr(script + strlen(SCRIPT_DIR) + 1, '/') != NULL || strstr(script, "..") != NULL)
        return fail("script must be directly in " SCRIPT_DIR " and named com.danteb.studio-*", script);
    if (stat(SCRIPT_DIR, &st) != 0 || !S_ISDIR(st.st_mode) || !root_only(&st))
        return fail("unsafe directory", SCRIPT_DIR);
    if (lstat(script, &st) != 0)
        return fail(strerror(errno), script);
    if (!S_ISREG(st.st_mode) || !root_only(&st))
        return fail("script must be a regular file owned by root and not writable by others", script);

    char *const args[] = {"/bin/bash", (char *)script, NULL};
    char *const env[] = {"PATH=/usr/bin:/bin:/usr/sbin:/sbin", NULL};
    execve("/bin/bash", args, env);
    return fail("cannot exec /bin/bash", strerror(errno));
}
