#!/bin/bash
# Helper for the TR-8S SD card in STORAGE MODE.
#
# To enter STORAGE MODE: with the pattern stopped, unplug USB, then hold
# [SHIFT] on the TR-8S while plugging the USB cable back into the computer.
# The display shows "STORAGE MODE" and the SD card appears as a USB drive.
#
#   ./tr8s-card.sh find     - locate the card's block device
#   ./tr8s-card.sh mount    - mount it at /run/media/$USER/TR8S (or via udisks)
#   ./tr8s-card.sh tree     - show the card's directory structure
#   ./tr8s-card.sh backup   - copy everything on the card to ./backups/<date>/
#   ./tr8s-card.sh umount   - safely unmount

set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

find_dev() {
    # Roland TR-8S in storage mode: USB mass storage, vendor 0582.
    for dev in /sys/block/sd*; do
        [ -e "$dev" ] || continue
        name=$(basename "$dev")
        # walk up to the USB device to read the vendor id
        real=$(readlink -f "$dev/device")
        vend=""
        p="$real"
        while [ "$p" != "/" ]; do
            if [ -f "$p/idVendor" ]; then vend=$(cat "$p/idVendor"); break; fi
            p=$(dirname "$p")
        done
        if [ "$vend" = "0582" ]; then
            echo "/dev/$name"
            return 0
        fi
    done
    return 1
}

cmd_find() {
    dev=$(find_dev) || { echo "No Roland USB storage device found."; echo "Is the TR-8S in STORAGE MODE? (hold SHIFT while plugging in USB)"; return 1; }
    echo "device: $dev"
    lsblk -o NAME,SIZE,FSTYPE,LABEL,MOUNTPOINT "$dev"
}

cmd_mount() {
    dev=$(find_dev) || { echo "No Roland USB storage device found."; return 1; }
    part="${dev}1"
    [ -b "$part" ] || part="$dev"
    mp=$(lsblk -no MOUNTPOINT "$part" | head -1)
    if [ -n "$mp" ]; then echo "already mounted at: $mp"; echo "$mp"; return 0; fi
    if command -v udisksctl >/dev/null; then
        udisksctl mount -b "$part"
    else
        mp="/run/media/$USER/TR8S"
        sudo mkdir -p "$mp" && sudo mount "$part" "$mp" && echo "mounted at $mp"
    fi
}

card_root() {
    dev=$(find_dev) || return 1
    part="${dev}1"; [ -b "$part" ] || part="$dev"
    lsblk -no MOUNTPOINT "$part" | grep -v '^$' | head -1
}

cmd_tree() {
    root=$(card_root) || { echo "card not mounted; run: $0 mount"; return 1; }
    echo "card root: $root"
    find "$root" -maxdepth 3 -not -path '*/.*' | sed "s|$root|.|" | sort | head -60
    echo
    echo "--- file counts by extension ---"
    find "$root" -type f -not -path '*/.*' | sed 's/.*\.//' | sort | uniq -c | sort -rn | head -20
    echo
    echo "--- total size ---"
    du -sh "$root" 2>/dev/null
}

cmd_backup() {
    root=$(card_root) || { echo "card not mounted; run: $0 mount"; return 1; }
    stamp=$(date +%Y-%m-%d_%H%M%S)
    dest="$HERE/backups/card_$stamp"
    mkdir -p "$dest"
    echo "copying $root -> $dest"
    cp -a "$root/." "$dest/" && sync
    echo "done. size: $(du -sh "$dest" | cut -f1)"
    find "$dest" -type f | wc -l | xargs echo "files:"
}

cmd_umount() {
    dev=$(find_dev) || { echo "device already gone"; return 0; }
    part="${dev}1"; [ -b "$part" ] || part="$dev"
    sync
    if command -v udisksctl >/dev/null; then
        udisksctl unmount -b "$part"
    else
        sudo umount "$part"
    fi
}

case "${1:-find}" in
    find)   cmd_find ;;
    mount)  cmd_mount ;;
    tree)   cmd_tree ;;
    backup) cmd_backup ;;
    umount) cmd_umount ;;
    *) sed -n '2,12p' "$0" ;;
esac
