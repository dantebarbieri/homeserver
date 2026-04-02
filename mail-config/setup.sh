#!/bin/sh
set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# --------------------------------------------------
# 1. Detect platform and set paths
# --------------------------------------------------
if [ "$(uname)" = "Darwin" ]; then
    AERC_TARGET=~/Library/Preferences/aerc
    CONFIG_DIR=~/Library/Preferences
    PLATFORM="macos"
else
    CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}"
    AERC_TARGET="$CONFIG_DIR/aerc"
    PLATFORM="linux"
fi

echo "==> Platform: $PLATFORM"
echo "==> Config dir: $CONFIG_DIR"
echo ""

# --------------------------------------------------
# 1b. Validate required tools
# --------------------------------------------------
echo "==> Checking required tools..."

missing=0
for cmd in aerc khard vdirsyncer; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "    WARNING: '$cmd' not found — install it before using this config"
        missing=1
    fi
done

if [ "$PLATFORM" = "linux" ] && ! command -v pass >/dev/null 2>&1; then
    echo "    WARNING: 'pass' not found. Install it for credential storage."
    missing=1
fi

if [ "$PLATFORM" = "macos" ] && ! command -v security >/dev/null 2>&1; then
    echo "    WARNING: 'security' command not found (should be built into macOS)."
    missing=1
fi

if [ "$missing" = "0" ]; then
    echo "    All required tools found"
fi
echo ""

# --------------------------------------------------
# 2. Create symlinks
# --------------------------------------------------
echo "==> Creating symlinks..."

ln -sfn "$SCRIPT_DIR/aerc"       "$AERC_TARGET"
ln -sfn "$SCRIPT_DIR/khard"      "$CONFIG_DIR/khard"
ln -sfn "$SCRIPT_DIR/vdirsyncer" "$CONFIG_DIR/vdirsyncer"

echo "    aerc       -> $AERC_TARGET"
echo "    khard      -> $CONFIG_DIR/khard"
echo "    vdirsyncer -> $CONFIG_DIR/vdirsyncer"
echo ""

# --------------------------------------------------
# 3. Create data directories
# --------------------------------------------------
echo "==> Creating data directories..."
mkdir -p ~/.local/share/vdirsyncer/contacts/icloud
mkdir -p ~/.local/share/vdirsyncer/calendars/icloud
mkdir -p ~/.local/share/vdirsyncer/status
echo "    ~/.local/share/vdirsyncer/contacts/icloud"
echo "    ~/.local/share/vdirsyncer/calendars/icloud"
echo "    ~/.local/share/vdirsyncer/status"
echo ""

# --------------------------------------------------
# 4. Bootstrap config files from examples
# --------------------------------------------------
echo "==> Bootstrapping config files from examples..."

# aerc accounts.conf
if [ ! -f "$SCRIPT_DIR/aerc/accounts.conf" ]; then
    cp "$SCRIPT_DIR/aerc/accounts.conf.example" "$SCRIPT_DIR/aerc/accounts.conf"
    chmod 600 "$SCRIPT_DIR/aerc/accounts.conf"
    echo "    Created aerc/accounts.conf (chmod 600)"
else
    # Ensure permissions are correct even if file already exists
    chmod 600 "$SCRIPT_DIR/aerc/accounts.conf"
    echo "    aerc/accounts.conf already exists (permissions verified)"
fi

# vdirsyncer config
if [ ! -f "$SCRIPT_DIR/vdirsyncer/config" ]; then
    cp "$SCRIPT_DIR/vdirsyncer/config.example" "$SCRIPT_DIR/vdirsyncer/config"
    echo "    Created vdirsyncer/config"
else
    echo "    vdirsyncer/config already exists"
fi
echo ""

# --------------------------------------------------
# 5. Register crontab for vdirsyncer sync
# --------------------------------------------------
CRON_JOB="*/15 * * * * vdirsyncer sync icloud_contacts icloud_calendars 2>/dev/null"

echo "==> Setting up periodic contact & calendar sync (every 15 min)..."
if command -v crontab >/dev/null 2>&1; then
    if crontab -l 2>/dev/null | grep -qF "vdirsyncer sync"; then
        echo "    Crontab entry already exists, skipping"
    else
        (crontab -l 2>/dev/null || true; echo "$CRON_JOB") | crontab -
        echo "    Added: $CRON_JOB"
    fi
else
    echo "    crontab not found — if you're on NixOS, the systemd timer"
    echo "    (vdirsyncer-sync.timer) handles this instead."
fi
echo ""

# --------------------------------------------------
# 6. Print next steps
# --------------------------------------------------
cat << 'INSTRUCTIONS'
=====================================================
  Setup complete! Next steps:
=====================================================

1. EDIT CREDENTIALS FILES

   These files were created from examples and need
   your real values:

   aerc/accounts.conf
     - Fill in your Gmail and iCloud email addresses
     - Update the *-cred-cmd lines for your platform

   vdirsyncer/config
     - Replace YOUR_APPLE_ID@icloud.com with your
       actual Apple ID

2. STORE YOUR APP PASSWORDS

INSTRUCTIONS

if [ "$PLATFORM" = "macos" ]; then
cat << 'MACOS_INSTRUCTIONS'
   macOS — using Keychain:

     # Store passwords in Keychain:
     security add-generic-password \
       -s "aerc-gmail" -a "you@gmail.com" -w "your-app-password"
     security add-generic-password \
       -s "aerc-icloud" -a "you@icloud.com" -w "your-app-password"
     security add-generic-password \
       -s "vdirsyncer-icloud" -a "you@icloud.com" -w "your-app-password"

     Then in accounts.conf, use:
       source-cred-cmd = security find-generic-password -s "aerc-gmail" -w
       outgoing-cred-cmd = security find-generic-password -s "aerc-gmail" -w

MACOS_INSTRUCTIONS
else
cat << 'LINUX_INSTRUCTIONS'
   Linux — using pass (recommended):

     # One-time setup (if not already done):
     gpg --full-generate-key       # use ECC default
     pass init "your@email.com"    # your GPG key email

     # Store your app passwords:
     pass insert email/gmail-app-password
     pass insert email/icloud-app-password
     pass insert contacts/icloud-app-password

     Then in accounts.conf, use:
       source-cred-cmd = pass email/gmail-app-password
       outgoing-cred-cmd = pass email/gmail-app-password

LINUX_INSTRUCTIONS
fi

cat << 'FINAL'
3. INITIAL CONTACT SYNC

     vdirsyncer discover icloud_contacts
     vdirsyncer sync icloud_contacts
     khard list    # verify contacts appear

4. INITIAL CALENDAR SYNC

     vdirsyncer discover icloud_calendars
     vdirsyncer sync icloud_calendars
     khal list    # verify events appear (requires khal)

5. TEST AERC

     aerc

=====================================================
FINAL
