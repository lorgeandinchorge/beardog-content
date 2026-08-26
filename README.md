# beardog-content

Content repo for the Bear Dog Launcher. The launcher clones this repo and
installs what it finds here into a player's Turtle WoW client.

**This repo is not meant to be installed by hand.** Copying these folders into
a game client yourself will get the addons in place but will miss the DLL
pairing, the realmlist repair, and the file protection the launcher does. Use
the launcher.

## What is here

| Path | What it is |
|---|---|
| `addons/` | The addon folders that have no upstream repo, or that must not drift from the DLLs we ship. Extracted, not zipped. |
| `client/` | Managed executables and DLLs, mirroring their paths inside the client's `Game` folder, plus `client/Data/patch-Q.MPQ`. |
| `meta/addon-meta.json` | The full addon catalogue: every group, where it comes from, and which folders it installs. |

## What is deliberately NOT here

- **Community addons with a live upstream repo.** The launcher pulls those
  straight from their authors' GitHub repos. `meta/addon-meta.json` records the
  URL and branch for each. Nothing is mirrored here, so upstream authors keep
  credit and we keep no copies to maintain.
- **The stock Blizzard and Turtle UI folders.** Those are Blizzard's and
  Turtle's files, not ours to redistribute. The launcher takes them from each
  player's own client copy, which already has them.

## Publishing an update

Edit the files, then commit and push. That is the whole release process --
there is no server, no build step, and nothing to sign. Launchers pick the
change up on their next update check.

Changing `meta/addon-meta.json` is how you add, remove, or pin an addon for
everyone at once. It does not require a new launcher build.

## A note on line endings

`.gitattributes` disables git's newline conversion for every file in this repo.
That is deliberate and must not be relaxed: the launcher decides whether a
player's file is current by comparing SHA-256 hashes, so a checkout that
rewrites `LF` to `CRLF` would make every file look modified on some machines
and not others.
