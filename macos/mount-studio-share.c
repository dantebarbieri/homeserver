#include <CoreFoundation/CoreFoundation.h>
#include <NetFS/NetFS.h>
#include <ctype.h>
#include <fcntl.h>
#include <limits.h>
#include <pwd.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mount.h>
#include <sys/stat.h>
#include <unistd.h>

#define HOME "/var/lib/studio-worker"

static void wipe(void *buffer, size_t size) {
    volatile unsigned char *bytes = buffer;
    while (size--) *bytes++ = 0;
}

static int verified_mount(const char *target, const char *source, int readonly) {
    struct statfs info;
    if (statfs(target, &info) != 0) {
        perror("statfs");
        return -1;
    }
    if (strcmp(info.f_fstypename, "smbfs") != 0) return 0;
    if (strcasecmp(info.f_mntfromname, source) != 0
        || strcmp(info.f_mntonname, target) != 0 || info.f_owner != getuid()
        || !(info.f_flags & MNT_NOSUID) || !(info.f_flags & MNT_NODEV)
        || !!(info.f_flags & MNT_RDONLY) != readonly) {
        fprintf(stderr, "Unexpected SMB source or mount permissions at %s\n", target);
        return -1;
    }
    return 1;
}

int main(int argc, char **argv) {
    struct passwd *user = getpwuid(getuid());
    if (!user || strcmp(user->pw_name, "_studio") != 0 || argc != 2
        || (strcmp(argv[1], "media") != 0 && strcmp(argv[1], "cache") != 0)) {
        fprintf(stderr, "Run as _studio: mount-studio-share media|cache\n");
        return 1;
    }
    int readonly = strcmp(argv[1], "media") == 0;
    char requested[PATH_MAX], target[PATH_MAX], source[128], url_text[128];
    snprintf(requested, sizeof(requested), HOME "/mounts/%s", argv[1]);
    // NetFS needs the canonical mountpoint; /var is a symlink on macOS.
    if (!realpath(requested, target)) { perror("mountpoint realpath"); return 1; }
    snprintf(source, sizeof(source), "//studio@127.0.0.1:1445/%s", argv[1]);
    snprintf(url_text, sizeof(url_text), "smb:%s", source);
    int mounted = verified_mount(target, source, readonly);
    if (mounted != 0) return mounted < 0 ? 1 : 0;

    int fd = open(HOME "/Library/Preferences/nsmb.conf", O_RDONLY | O_NOFOLLOW);
    struct stat info;
    if (fd < 0 || fstat(fd, &info) != 0 || !S_ISREG(info.st_mode)
        || info.st_uid != getuid() || (info.st_mode & 077) != 0) {
        fprintf(stderr, "Missing or insufficiently private SMB credential file\n");
        if (fd >= 0) close(fd);
        return 1;
    }
    FILE *file = fdopen(fd, "r");
    if (!file) { perror("fdopen"); close(fd); return 1; }
    char line[512], secret[65] = {0};
    while (fgets(line, sizeof(line), file)) {
        if (strncmp(line, "password=", 9) != 0) continue;
        size_t length = strcspn(line + 9, "\r\n");
        if (length != 64 || secret[0]) { secret[0] = 0; break; }
        memcpy(secret, line + 9, 64);
    }
    int failed = ferror(file);
    fclose(file);
    for (size_t i = 0; i < 64; i++) if (!isxdigit((unsigned char)secret[i])) failed = 1;
    if (failed) {
        fprintf(stderr, "Invalid private SMB credential\n");
        wipe(secret, sizeof(secret));
        return 1;
    }
    CFStringRef url_string = CFStringCreateWithCString(NULL, url_text, kCFStringEncodingUTF8);
    CFURLRef url = CFURLCreateWithString(NULL, url_string, NULL);
    CFStringRef target_string = CFStringCreateWithCString(NULL, target, kCFStringEncodingUTF8);
    CFURLRef mountpath = CFURLCreateWithFileSystemPath(NULL, target_string, kCFURLPOSIXPathStyle, true);
    CFStringRef password = CFStringCreateWithCString(NULL, secret, kCFStringEncodingUTF8);
    wipe(secret, sizeof(secret));
    wipe(line, sizeof(line));
    CFMutableDictionaryRef open_options = CFDictionaryCreateMutable(NULL, 0,
        &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
    CFMutableDictionaryRef mount_options = CFDictionaryCreateMutable(NULL, 0,
        &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
    CFDictionarySetValue(open_options, kNAUIOptionKey, kNAUIOptionNoUI);
    CFDictionarySetValue(open_options, kNetFSAllowLoopbackKey, kCFBooleanTrue);
    CFDictionarySetValue(mount_options, kNetFSMountAtMountDirKey, kCFBooleanTrue);
    int flags = MNT_DONTBROWSE | MNT_NOSUID | MNT_NODEV | (readonly ? MNT_RDONLY : 0);
    CFNumberRef mount_flags = CFNumberCreate(NULL, kCFNumberIntType, &flags);
    CFDictionarySetValue(mount_options, kNetFSMountFlagsKey, mount_flags);
    CFArrayRef mountpoints = NULL;
    // Pass the password directly to NetFS, never in argv, environment or logs.
    int status = NetFSMountURLSync(url, mountpath, CFSTR("studio"), password,
        open_options, mount_options, &mountpoints);
    if (mountpoints) CFRelease(mountpoints);
    CFRelease(mount_flags);
    CFRelease(mount_options);
    CFRelease(open_options);
    CFRelease(password);
    CFRelease(mountpath);
    CFRelease(target_string);
    CFRelease(url);
    CFRelease(url_string);
    if (status != 0) {
        fprintf(stderr, "NetFS mount failed for %s (status %d)\n", argv[1], status);
        return 1;
    }
    if (verified_mount(target, source, readonly) != 1) return 1;
    printf("Verified %s share mounted through restricted SSH transport\n", argv[1]);
    return 0;
}
