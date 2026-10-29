/* SPDX-License-Identifier: GPL-2.0-only
 * Read-only NTFS state inspection. Build against the pinned libntfs-3g.
 * Do not use ntfs-3g.probe --readwrite as a substitute: it opens O_RDWR.
 */
#include "config.h"
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/stat.h>
#include "volume.h"
#include "logging.h"
#include "endians.h"
#include "logfile.h"

/* Read-only counterpart of volume.c's static ntfs_volume_check_logfile,
 * using the pinned upstream public logfile API. v2.0 can retain Windows
 * metadata for Fast Startup even on a data volume without hiberfil.sys.
 * Return 1 for cached metadata, 0 for a clean journal, -1 for unknown.
 */
static int logfile_state(ntfs_volume *vol)
{
    ntfs_inode *inode;
    ntfs_attr *attribute;
    RESTART_PAGE_HEADER *restart = NULL;
    int result;
    inode = ntfs_inode_open(vol, FILE_LogFile);
    if (!inode) return -1;
    attribute = ntfs_attr_open(inode, AT_DATA, AT_UNNAMED, 0);
    if (!attribute) {
        ntfs_inode_close(inode);
        return -1;
    }
    result = (ntfs_check_logfile(attribute, &restart) &&
              ntfs_is_logfile_clean(attribute, restart)) ? 0 : -1;
    if (restart && restart->major_ver == const_cpu_to_le16(2) &&
                   restart->minor_ver == const_cpu_to_le16(0)) result = 1;
    free(restart);
    ntfs_attr_close(attribute);
    if (ntfs_inode_close(inode)) result = -1;
    return result;
}

static int unknown(const char *error)
{
    printf("{\"schema\":1,\"status\":\"unknown\",\"volume_flags\":null,\"error\":\"%s\"}\n", error);
    return 1;
}

int main(int argc, char **argv)
{
    ntfs_volume *vol;
    struct stat info;
    unsigned long mounted = 0;
    unsigned flags;
    int hibernated, saved_errno, journal;
    const char *state;
    ntfs_log_set_handler(ntfs_log_handler_stderr);
    if (argc != 2) return unknown("usage");
    if (stat(argv[1], &info) || !(S_ISBLK(info.st_mode) || S_ISREG(info.st_mode)))
        return unknown("invalid_device");
    if (ntfs_check_if_mounted(argv[1], &mounted)) return unknown("mount_state_unavailable");
    if (mounted & NTFS_MF_MOUNTED) return unknown("already_mounted");
    /* RDONLY controls the underlying open; FORENSIC also forbids recovery.
     * A metadata inconsistency, including MFT/MFTMirr record 3, fails here.
     */
    vol = ntfs_mount(argv[1], NTFS_MNT_RDONLY | NTFS_MNT_FORENSIC);
    if (!vol) return unknown("metadata_unreadable");
    if (ntfs_version_is_supported(vol)) {
        ntfs_umount(vol, FALSE);
        return unknown("unsupported_ntfs_version");
    }
    flags = le16_to_cpu(vol->flags);
    /* Read-only mounts skip this upstream check; call it explicitly.
     * EPERM means a recognized hibernation header or short hibernation file.
     * Other errors are unknown, never evidence that repair is safe.
     */
    errno = 0;
    hibernated = ntfs_volume_check_hiberfile(vol, 1);
    saved_errno = errno;
    journal = logfile_state(vol);
    if (ntfs_umount(vol, FALSE)) return unknown("close_failed");
    if (hibernated && saved_errno != EPERM) return unknown("hibernation_check_failed");
    if (!hibernated && journal < 0) return unknown("journal_check_failed");
    state = (hibernated || journal == 1) ? "hibernated" : (flags & le16_to_cpu(VOLUME_IS_DIRTY)) ? "dirty" : "clean";
    printf("{\"schema\":1,\"status\":\"%s\",\"volume_flags\":%u,\"error\":null}\n", state, flags);
    return 0;
}
