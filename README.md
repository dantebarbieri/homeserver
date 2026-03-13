# mail-config

Portable terminal mail setup using [aerc](https://aerc-mail.org/),
[khard](https://github.com/luber/khard) (contacts), and
[vdirsyncer](https://github.com/pimutils/vdirsyncer) (CardDAV sync). Works on
Linux, macOS (Homebrew), and WSL.

Configuration lives in this repo and is symlinked into place by `setup.sh`.
Credential files (`accounts.conf`, `vdirsyncer/config`) are gitignored — only
`.example` templates are tracked.

## Components

| Tool       | Purpose                              | Config dir (Linux)             |
|------------|--------------------------------------|--------------------------------|
| aerc       | Terminal email client (IMAP + SMTP)  | `~/.config/aerc/`             |
| khard      | CLI vCard address book               | `~/.config/khard/`            |
| vdirsyncer | CardDAV ↔ local filesystem sync      | `~/.config/vdirsyncer/`       |

## File structure

```
mail-config/
├── setup.sh                    # One-shot installer (symlinks, dirs, cron)
├── aerc/
│   ├── aerc.conf               # Main config (non-default settings only)
│   ├── binds.conf              # Key bindings (vim-style)
│   └── accounts.conf.example   # Template — copy to accounts.conf
├── khard/
│   └── khard.conf              # Points at vdirsyncer's local contact store
└── vdirsyncer/
    └── config.example          # Template — copy to config
```

## Prerequisites

Install the core tools and the HTML-to-text converter (`w3m`) used by aerc's
built-in `html` filter:

```bash
# Debian / Ubuntu / WSL
sudo apt install aerc khard vdirsyncer w3m

# macOS (Homebrew)
brew install aerc khard vdirsyncer w3m

# Arch
sudo pacman -S aerc khard vdirsyncer w3m

# NixOS (declared in configuration.nix)
# aerc khard vdirsyncer w3m pass
```

You also need a credential store:

- **Linux / WSL** — [pass](https://www.passwordstore.org/) (requires GPG):
  ```bash
  sudo apt install pass
  gpg --full-generate-key
  pass init "your@email.com"
  ```
- **macOS** — Keychain (built-in, no setup needed).

## Installation

```bash
git clone <this-repo> && cd mail-config
./setup.sh
```

`setup.sh` does the following:

1. **Detects the platform** (macOS vs Linux) and sets config paths accordingly
   (`~/Library/Preferences/aerc` on macOS, `~/.config/aerc` on Linux).
2. **Symlinks** `aerc/`, `khard/`, and `vdirsyncer/` into the config directory.
3. **Creates data directories** under `~/.local/share/vdirsyncer/` for local
   contact storage and sync status.
4. **Bootstraps credential files** by copying `.example` templates to their
   real names (if they don't already exist). `accounts.conf` is chmod 600.
5. **Registers a crontab entry** to run `vdirsyncer sync` every 15 minutes.

## Post-install setup

### 1. Store app passwords

Generate app-specific passwords for Gmail and iCloud (regular passwords won't
work — both providers require app passwords when using IMAP/SMTP).

```bash
# Linux (pass)
pass insert email/gmail-app-password
pass insert email/icloud-app-password
pass insert contacts/icloud-app-password

# macOS (Keychain)
security add-generic-password -s "aerc-gmail" -a "you@gmail.com" -w
security add-generic-password -s "aerc-icloud" -a "you@icloud.com" -w
security add-generic-password -s "vdirsyncer-icloud" -a "you@icloud.com" -w
```

### 2. Edit credential files

Fill in your real email addresses and verify the credential commands match your
platform:

- `aerc/accounts.conf` — IMAP/SMTP accounts (Gmail + iCloud)
- `vdirsyncer/config` — CardDAV username for iCloud contacts

### 3. Initial contact sync

```bash
vdirsyncer discover icloud_contacts
vdirsyncer sync icloud_contacts
khard list   # verify contacts appear
```

### 4. Launch aerc

```bash
aerc
```

## Account notes

### Gmail

- Uses IMAP (`imaps://imap.gmail.com:993`) and SMTP (`smtps://smtp.gmail.com:465`).
- `copy-to` is intentionally omitted — Gmail automatically saves sent messages
  server-side. Setting it causes duplicates.

### iCloud

- Uses IMAP (`imaps://imap.mail.me.com:993`) and SMTP with STARTTLS
  (`smtp+starttls://smtp.mail.me.com:587`).
- `copy-to` is set to `Sent Messages` (iCloud's IMAP sent folder name).
- Contact sync via CardDAV at `https://contacts.icloud.com/`.

## Key bindings

`binds.conf` provides vim-style navigation. Highlights:

| Key       | Action                  | Context     |
|-----------|-------------------------|-------------|
| `j` / `k` | Next / previous message | messages    |
| `J` / `K` | Next / previous folder  | messages    |
| `Enter`   | Open message            | messages    |
| `C`, `m`  | Compose new             | messages    |
| `rr`      | Reply all               | messages    |
| `rq`      | Reply all (quoted)      | messages    |
| `d`       | Delete (with prompt)    | messages    |
| `v`       | Toggle mark             | messages    |
| `T`       | Toggle threads          | messages    |
| `/`       | Search                  | messages    |
| `y`       | Send                    | review      |
| `q`       | Quit / close            | everywhere  |
