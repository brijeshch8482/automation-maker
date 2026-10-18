# MakeMyEXE Desktop App: Detailed Design

> **Status: approved 2026-10-18: the primary delivery model.** It replaces "one zip per automation" and the single-file launcher idea; `ARCHITECTURE.md` §8 points here.
> The open questions in §15 use their **recommended defaults** until the founder decides otherwise. Keep anything that depends on them (free set, device limit, prices) a setting, not code.

---

## 1. Summary

The user installs **one Windows app, MakeMyEXE**, once. It ships with a few free automations. Every further automation (a paid catalog one or the user's own custom one) arrives as one small signed file (`.mmx` bundle). Double-clicking it adds the automation to the app's list, and it gets its own Start menu shortcut.

```text
Install once: MakeMyEXE-Setup.exe (~35 MB, per-user, no admin)
  └── MakeMyEXE app
        ├── 🆓 PDF Merge · Make PDF · Bulk Rename · Invoice Generator   (pre-installed)
        ├── 💳 Excel Combine                                           (bought on the website → .mmx → added)
        └── ✨ GST Report (custom)                                      (made on the website → .mmx → added)
```

**What stays exactly as built:**
- The engine (Runner), the pack format v1 and its Ed25519 verification
- Linux pack builds and the build gates
- Library layers and the policy gate
- The routines

**What changes:**
- What the user downloads: an installer once, then bundles.
- Where packs and layers live on the PC: a shared store.
- New pieces: the Hub UI, licensing, and devices.

### Why this model
| Concern | Per-app zip / single exe | **Installed app** |
|---|---|---|
| Code signing | Every app exe signed separately | **One app** (installer + its binaries) |
| SmartScreen / Smart App Control / AV | Hits every new exe | Hits one binary, and reputation builds once |
| Download per automation | ~30 MB | **KB to a few MB** (pack + needed layers) |
| Disk for 10 automations | ~700 MB (10 runtimes) | **~80 MB + layers** (shared runtime, shared layers) |
| First-run extraction problems | Must be solved (atomic extract, locks, AV scan time) | **Gone**: the installer does it once |
| Paid automations | Awkward | Natural: free list + paid additions |
| Install step | None | **One-time**, per-user, no admin |

---

## 2. User experience (flows)

### 2.1 Install
1. Website › **Download MakeMyEXE** › `MakeMyEXE-Setup-1.4.0.exe` (signed in the live phase).
2. Double-click › installer (per-user, **no admin, no UAC**) › Install › done.
3. Start menu: **MakeMyEXE**, plus one shortcut per pre-installed automation.

### 2.2 First open (the Hub)
- The list of automations shows name, short description, a 🔒 offline / 🌐 online badge, and version.
- **Your MakeMyEXE ID:** `MMX-7K3Q-9DWA-2FPL` with a **Copy** button, plus **Link this PC** (opens the browser at `makemyexe.com/link?id=…`. The browser makes the request, not the app).
- **Add automation…** (file picker for `.mmx`) and drag-and-drop.
- About: the app version, plus a **Check for updates on the website** button, which opens the browser; the app itself makes no call.

### 2.3 Get a free catalog automation
Website › automation page › **Add to MakeMyEXE** › browser downloads `PDF-Split.mmx` › double-click › "Add **PDF Split** to MakeMyEXE?" › **Add** › it appears in the list and the Start menu.

### 2.4 Buy a paid automation
1. The user is signed in on the website, and the PC is linked (§7.2).
2. Automation page › **Buy ₹X** › payment › **Download** › `Excel-Combine.mmx` (it carries a license for the user's linked PCs).
3. Double-click › Add › appears in the list.

### 2.5 Custom automation
The website flow is unchanged (describe → spec → confirm → build). When the job is `ready`: **Download** › `GST-Report.mmx` (pack + needed layers + license) › double-click › Add.

### 2.6 Run an automation
Click it in the Hub, or use its Start menu shortcut. It opens in **its own window and its own process**, and the screens are exactly what the engine shows today.

### 2.7 Update the app
The website shows the latest version, and About in the app shows the installed one. The user downloads the new installer, runs it, and it upgrades in place. Automations, layers, settings and licenses stay.

### 2.8 New PC or reinstall
- **Reinstall on the same PC:** `install.json` is kept, so the ID stays the same and everything still works.
- **New PC:** install, then **Link this PC**, then on the website **My automations › Download all**, then import. Settings don't move automatically. The user can export them from the app (§3.4).

### 2.9 Uninstall
Settings › Apps › MakeMyEXE › Uninstall. The app binaries are removed. Then it asks: "Also remove your automations and their settings?", with **Keep** as the default. Files the user made with the automations (PDFs, invoices) are **never touched**.

---

## 3. On the PC

### 3.1 Layout
```text
%LOCALAPPDATA%\Programs\MakeMyEXE\              app binaries (installer-owned)
  MakeMyEXE.exe                                 one exe: Hub mode and Run mode
  runtime\1\                                    _internal of runtime major 1 (Python 3.12, Qt, engine, core libs)
  runtime\2\                                    only while an installed automation still needs major 1 or 2

%LOCALAPPDATA%\MakeMyEXE\                       the store (app-owned, not roaming)
  install.json                                  install_id, created_at, format
  store\automations\<id>\<version>\             verified pack contents (manifest.json, manifest.sig, spec.json, ...)
  store\libs\<dist>-<version>\                  verified layers, shared by every automation
  store\licenses\<license_id>.json + .sig
  store\index.json                              installed automations, versions, which layers each uses
  store\icons\<id>.ico                          shortcut icons (data, so the exe hash never changes)
  logs\                                         local only, rotated, never sent anywhere

%APPDATA%\MakeMyEXE\<id>\                       settings.json, data.sqlite (as today)
```

### 3.2 One exe, two modes
- **Hub mode:** `MakeMyEXE.exe` with no arguments. It shows the list, imports files, shows the ID, and creates shortcuts.
- **Run mode:** `MakeMyEXE.exe --run <id>[@<version>]`. One process per automation, which loads the matching runtime major.
- **Import:** `MakeMyEXE.exe --import <file.mmx>`, used by the `.mmx` file association; it opens the Hub's import dialog.

Separate processes mean a crash or a heavy import (pandas) in one automation never affects the Hub or another automation. Each process gets **only its own layers** on `sys.path`.

### 3.3 No network in the app, at all
- The Hub has no network code: purchases, linking and update checks open the **browser**.
- The socket guard runs in Hub mode too. A test asserts that the Hub process never opens a socket.
- Run mode keeps today's rule: sockets are blocked unless the automation's spec declares network with domains.

### 3.4 Settings export and import
Per automation: **Export settings** writes a `.json` the user saves wherever they like; **Import settings** reads one. This covers moving to a new PC without any cloud sync.

---

## 4. The bundle format (`.mmx`, format 2)

A bundle is a zip that wraps today's packs, unchanged:

```text
GST-Report.mmx
├── bundle.json                       {"format": 2, "packs": [...], "layers": [...], "licenses": [...]}
├── packs\gst-report-1.0.0.mmx        pack format v1, exactly as built today (signed manifest pins its layers)
├── layers\openpyxl-3.1.5\...         + RECORD.json
├── layers\et_xmlfile-2.0.0\...       + RECORD.json
├── license.json                      only for paid / custom automations (§7)
├── license.sig
└── icon.ico                          optional
```

- `bundle.json` isn't signed and isn't trusted. It's only a table of contents. Trust comes from the pack signature (which pins the layers through `record_sha256`) and the license signature.
- One bundle can hold several packs ("Download all" for a new PC).
- **Layers are always included** for the automations in the bundle. The website can't know what the user has (the app is offline), and the app skips layers it already has.
- A plain pack v1 (`app.mmx`) also imports, as a bundle with one pack and no layers.

---

## 5. Import

Order of operations (all offline):
1. Open the zip and read `bundle.json` (untrusted).
2. For each pack:
   1. Verify `manifest.sig` with a trusted key (`catalog` or `jobs`).
   2. Verify every file hash.
   3. Check `runner.major` + `tested_with` against the installed app (§8). If the app is too old: "Update MakeMyEXE to 1.5 or newer to add this."
   4. For each layer in the manifest: if it's already in `store\libs\` with the same `record_sha256`, reuse it. Otherwise take it from the bundle and verify its `RECORD.json` hash and every file. Nothing unlisted is allowed.
   5. If the pack's `kind` needs a license (§7): find a license in the bundle or the store that covers this automation, version and this `install_id`, and verify its signature. If there's none: "This automation is licensed to another MakeMyEXE ID. Link this PC on the website and download it again."
3. Show the confirmation: name, version, 🔒/🌐 + domains, size, and "Replaces version X" when updating.
4. Write everything into `…\store\…\.tmp-<random>\`, then **rename atomically** into place, then update `index.json`.
5. Create the Start menu shortcut.

**Rules:**
- **Downgrade:** importing an older version than the installed one asks first. Default: keep the newer one.
- **Keep previous version:** the last 2 versions of each automation are kept, and the user can switch back in the Hub.
- **Garbage collection:** a layer no installed version uses is removed on the next start. It's our own store, never the user's files.

---

## 6. Running an automation

1. Hub or shortcut › `MakeMyEXE.exe --run gst-report`.
2. The process resolves the version from `index.json` (default: the newest installed).
3. **Verify again on every start:** the pack signature, file hashes, layers, and the license. This costs ~ms for the pack and ~0.2 s for a large layer. The store is user-writable, so verify at import isn't enough.
4. `sys.path` = the runtime of the pack's major + **only this automation's layers**.
5. The offline guard and the custom-step sandbox apply exactly as today, and the engine UI runs.

---

## 7. Licensing (paid and custom automations)

### 7.1 What's protected, and how much
The goal is **deterrence, not DRM**. We stop a `.mmx` from simply being forwarded to friends; we don't fight determined crackers. Prices are small, and heavy DRM would cost honest users more than it saves.

### 7.2 MakeMyEXE ID and linking
- `install_id`: 128 random bits, created at first start and stored in `install.json`. It's shown as `MMX-XXXX-XXXX-XXXX` (base32 + checksum).
- **No hardware fingerprint** (privacy). It is tied to the install, and a reinstall keeps `install.json`.
- **Linking:** the website's **My PCs** page lets the user paste the ID, or press **Link this PC** in the app, which opens the browser with the ID in the URL. The user names the PC ("Office laptop"). Limit: 3 PCs per account, and the user can remove one to add another.

### 7.3 License file
```json
{
  "format": 1,
  "license_id": "lic_01J…",
  "automation_id": "excel-combine",
  "major": 1,
  "install_ids": ["MMX-7K3Q-9DWA-2FPL", "MMX-…"],
  "kind": "purchase | custom | free",
  "issued_at": "2026-10-18T10:00:00Z"
}
```
- It's signed with a **third Ed25519 key, `license`**, held by the **API** (Render env `LICENSE_SIGNING_KEY`). The API writes the license at download time for the user's currently linked PCs, and the Worker puts it into the bundle (the token carries it).
- **No email, name or account id** in the license. It's privacy-neutral.
- **Blast radius:** a leaked `license` key lets someone forge licenses (piracy) but **can't make code run**. Code still needs a `catalog`/`jobs` signature, which is why that key is allowed to live in the internet-facing API, unlike the other two.
- **Covers a major version:** updates within the same major need no new purchase.
- **Linking a new PC:** the user downloads again, and the new license includes the new ID.
- **Refund or abuse:** future downloads are refused. Installed copies keep working (offline; it can't be revoked).

### 7.4 Which automations need a license
| Kind | License |
|---|---|
| Free (pre-installed or free catalog) | None |
| Paid catalog | `purchase` |
| Custom | `custom`. Whether custom builds are paid is a pricing decision; technically they work the same way |

---

## 8. Versions and compatibility

- **App version = engine version** (`engine-v<semver>`).
- **Minor releases only add.** A pack with `runner.major = 1, tested_with = 1.3.0` runs on any app 1.x ≥ 1.3. On an older 1.x, import refuses with "update the app".
- **Major release** (e.g. Python 3.12 → 3.13, an incompatible engine change): the installer installs `runtime\2\` and **keeps `runtime\1\`** while any installed automation needs it. The website rebuilds catalog packs for the new major, and custom ones get rebuilt from the saved spec.
- Layers are built per Python ABI (cp312), so they belong to a runtime major.
- **Release gate:** before the website offers a new app version, every catalog pack and every non-expired job pack is smoke-tested on it on Windows (as in `ARCHITECTURE.md` §8.7).
- **Updates are never automatic** (our rule). The website and About show versions, and the user decides.

---

## 9. Installer

- **Per-user installer** (Inno Setup, built on windows-latest in the release workflow; releases are rare, so the 2× Windows minutes are fine). It installs into `%LOCALAPPDATA%\Programs\MakeMyEXE\` and needs no admin.
- **Registers (HKCU only):**
  - the `.mmx` file association → `MakeMyEXE.exe --import "%1"`
  - Start menu entries
  - the uninstall entry
- **Upgrade in place:** it keeps the store, settings and `install.json`, and keeps old runtime majors that are still needed.
- **Live phase, for offices: a signed MSI** (WiX) that installs into Program Files with admin rights. That's admin-protected, and it works with AppLocker publisher rules.
- **Size:** installer ~35 MB, installed ~70–80 MB (budget in `ARCHITECTURE.md` §8.8).

---

## 10. Security model

| Layer | What protects it |
|---|---|
| Installer, `MakeMyEXE.exe`, every DLL/`.pyd` in `runtime\` | **Authenticode** code signing with a timestamp (live phase). Also a hash list of `runtime\` compiled into the exe, checked at start (quick check every start, full check daily), because a per-user install folder is user-writable |
| DLL loading | Restricted DLL search order in the bootloader (no side-loading from the current or exe folder) |
| Automation code | Pack Ed25519 signature (`catalog`, `jobs` keys, in GitHub `main`-only environments) + build gates + run-time sandbox |
| Libraries | Pinned by `record_sha256` inside the signed pack manifest; policy gate on the server |
| Entitlement | License Ed25519 signature (`license` key, API) |
| Privacy | No network in the Hub; run mode offline unless declared; no telemetry; the license carries no PII |
| Isolation | One process per automation, own layers only |

**What a signature means:** it proves origin and integrity, not safety. The gates and the sandbox provide safety.

**Residual risks:**
- Malware already running as the user can modify a per-user install. The quick checks catch corruption and casual tampering, not a determined attacker who already owns the account. The MSI in Program Files closes this for offices.
- A compromised but popular library release (layers). Release age, hash pins and OSV reduce this risk; they don't remove it.

---

## 11. Server side changes

### 11.1 API (FastAPI)
- **New tables:**
  - `devices`: user_id, install_id, label, created_at, removed_at
  - `entitlements`: user_id, automation_id, major, kind, source_ref, created_at
  - `purchases`: later, with the payment gateway
- **New endpoints:**
  - `GET/POST/DELETE /me/devices`
  - `GET /me/automations` (everything the user owns, for "Download all")
  - `GET /app/latest` (version, size, installer token)
  - Bundle downloads: `GET /automations/{id}/bundle`, `GET /jobs/{id}/bundle`. They return a Worker URL whose token carries the pack, layers and the **signed license**.
- **Catalog:** each automation gets `price` (0 = free) and `preinstalled` (bool).
- **New secret:** `LICENSE_SIGNING_KEY` (Render env).

### 11.2 Worker
- It streams a **bundle** instead of a Runner zip: `bundle.json` + the pack + layer blocks + `license.json` + `.sig`. `zipblocks` and the zip writer are reused, and the Runner blocks are no longer part of an automation download.
- The installer is served as a plain R2 object (a 15-minute signed link or a Worker token).

### 11.3 R2 layout
```text
app/<version>/MakeMyEXE-Setup-<version>.exe     + app/latest.json (pointer, flipped after the release gate)
packs/catalog/<id>/<version>/app.mmx, Guide.pdf  latest 2 versions per automation
packs/jobs/<job_id>/attempt-<n>/app.mmx          lifecycle: 14 days (the spec is kept; it can be rebuilt)
layers/<dist>/<version>/blocks.bin, layout.json, RECORD.json
```

### 11.4 Website
- A **Download MakeMyEXE** page (requirements, size, version, a SmartScreen note during internal testing).
- Automation page: **Add to MakeMyEXE** (free) or **Buy** (paid). Job page: **Add to MakeMyEXE**.
- **My PCs** (link/remove) and **My automations** (download one, or download all).
- The guide stays on the website (Guide.pdf), and the app has **Help › Guide** for each automation from its pack.

---

## 12. What happens to the work already merged

| Piece | Fate |
|---|---|
| Engine, pack format v1, Ed25519 verify (`engine/pack.py`, `engine/ed25519.py`) | **Kept as is.** Packs sit inside bundles |
| `build/pack.py`, `build/pack_check.py`, Linux pack builds, gates, routines | **Kept** |
| `build/runner.py` | **Becomes the app build** (Hub + Run mode + runtime), plus the installer step |
| `build/zipblocks.py`, Worker zip writer, download tokens | **Kept**; the Worker assembles bundles instead of Runner zips |
| Per-app zip download (Runner + pack in a zip) | **Internal testing only**, until the app ships, then removed |
| Single-file launcher (SFX) idea | **Dropped** |
| Standalone PyInstaller fallback | Open question (§15) |
| Library layers + policy gate (2c) | **Kept**; layers go to the shared store |

---

## 13. Phases

| Phase | Goal | Done when |
|---|---|---|
| 2b (finish) | Publish the catalog packs + the Runner; download tokens through the Worker | As in ARCHITECTURE §13 (the per-app zip is fine for internal testing) |
| **2d: Desktop app** | Hub + Run mode + import + store + per-automation processes + shortcuts + `.mmx` association + Inno Setup installer + bundle format 2 + Worker bundles + website "Download MakeMyEXE" / "Add to MakeMyEXE" | Install the app on a clean Windows 11 VM; pre-installed automations run; a downloaded bundle (with a layer) imports and runs; a tampered bundle is refused; uninstall keeps the user's files |
| 2c | Library layers + policy gate (unchanged), now feeding the shared store. **Layers and the pack manifest are keyed by platform** (`windows-x64` the only one for now), so macOS (§16) is another platform build, not a format change | As in ARCHITECTURE §13 |
| **2e: Licensing** | devices, entitlements, license key + signing, license checks in import/run, "My PCs", paid flag in the catalog (payment gateway stubbed) | A paid bundle imports only on a linked ID; a forwarded bundle is refused on another PC |
| 6 (live) | Code signing (installer + binaries), MSI for offices, payment gateway, Smart App Control test | Clean install on Windows 11 with SAC on: no block, no "unknown publisher" |

Order: finish 2b → 2d → 2c → 2e. Payments and code signing come with the live phase.

**Launch order (decided 2026-10-18):** finish internal testing → buy the domain → Windows public release → then decide on macOS (§16).

---

## 14. Signing and prerequisites checklist

### 14.1 Needed now (free, internal phase)
- [ ] **Ed25519 key pairs** for `catalog` and `jobs`: `python3 -m build.pack keygen --key-id <id> --out <dir>` (`docs/DEPLOY.md` §9). `build/trusted_keys.json` is still empty.
  - Private keys go **only** into the GitHub environment secrets: `catalog` (automation-maker) and `publish` (automation-builds).
  - Public keys go into `build/trusted_keys.json` (committed; they're public).
  - Keep an **offline backup** of the private keys (an encrypted file or a password manager). Lose them and existing packs can't be re-signed.
- [ ] **`license` key pair** (phase 2e). The private key goes into Render env `LICENSE_SIGNING_KEY`; the public key is embedded in the app.
- [ ] **`DOWNLOAD_TOKEN_SECRET`**: the same random value in Render and in the Worker secret.
- [ ] Windows test machine or VM: Windows 11 with Defender **and Smart App Control on**, plus Windows 10. A free Microsoft evaluation VM works.

### 14.2 Needed before the public launch (Windows code signing)
- [ ] **Decide the legal identity:**
  - **Individual:** the certificate shows your name as the publisher.
  - **Business:** proprietorship (Udyam/GST) or Pvt Ltd. The certificate shows "MakeMyEXE …", which inspires more trust. A payment gateway needs KYC anyway.
- [ ] **OV code-signing certificate** from a CA (Sectigo, SSL.com, Certum, DigiCert, …):
  - Documents: government ID (PAN/Aadhaar/passport), address proof, phone verification. For a business, add registration documents. Some CAs also check a public business listing or a D-U-N-S number.
  - Since June 2023 the key must live on a hardware token or **cloud HSM**. Use **cloud signing** (SSL.com eSigner, Certum SimplySign, DigiCert KeyLocker, …), so GitHub Actions can sign without a USB token.
  - Cost: roughly US$200–500/year plus any cloud-signing fee. Check current prices.
  - Validation takes a few days for individuals and longer for businesses. **Start a few weeks before launch.**
  - Azure Artifact (Trusted) Signing is cheaper, but check whether it currently accepts Indian individuals or businesses.
- [ ] **Signing step** in the trusted release job: `signtool` (Windows) or `jsign` (Linux) with the cloud HSM. Sign the installer, `MakeMyEXE.exe` and every DLL/`.pyd`, always with an **RFC 3161 timestamp**, so signatures stay valid after the certificate expires.
- [ ] **Reputation warm-up:** start signing catalog releases a few weeks before launch.
- [ ] **Microsoft submission account** (WDSI) for false positives.
- [ ] **VirusTotal API key** (free) for hash lookups in CI. Never upload job builds.
- [ ] Bootloader hardening (DLL search order) and the `runtime\` hash list, both before signing.

### 14.3 Business pieces (live phase)
- [ ] Domain (`makemyexe.com`, after the trademark check) + business email (support@, the publisher contact for the CA).
- [ ] Payment gateway (Razorpay/Cashfree), which needs KYC and the business identity. Webhook → `purchases` → `entitlements`.
- [ ] Pricing: how many free automations (3–5), the price per paid automation, whether custom builds are paid.
- [ ] Terms and Privacy updated for licenses, devices and purchases. No PII in licenses.

---

## 15. Open questions for review

1. **Free set:** which 3–5 automations come pre-installed? (Default: the four current catalog automations, as a setting.)
2. **Custom automations:** paid per build, included in a subscription, or free during beta? (Default: free during the internal phase; they still get a `custom` license.)
3. **Device limit:** 3 PCs per account, OK? (Default: 3, as a setting.)
4. **Standalone fallback** for technical library failures (no Windows wheel, lock conflict): keep it as a separate per-app zip outside the app, or drop it and go straight to `needs_library`? (Recommendation: drop it in 2d, and decide later if real cases appear.)
5. **Per-automation Start menu shortcuts:** always, or only when the user pins one? (Default: always.)
6. **Internal phase:** keep the per-app zip download alongside the app until 2d is verified? (Recommendation: yes.)
7. **Installer tool:** Inno Setup (simple, Windows build) vs NSIS (builds on Linux). (Recommendation: Inno Setup, since releases already run on windows-latest.)
8. **MSI for offices:** at launch, or only when a business asks? (Default: when a business asks.)

---

## 16. macOS (later, not planned yet)

Decided 2026-10-18: **no Mac work until after the Windows release.** Kept here so earlier phases don't close the door.

**Already platform-neutral:** spec, API, website, Worker, R2, licensing, the Ed25519 seal and `trusted_keys.json`, and the `.mmx` pack itself (spec + pure-Python custom step + samples: one pack runs on both). The engine is Python + PySide6, so the UI ports.

**What a Mac version needs:**
- **Runner:** PyInstaller `MakeMyEXE.app`, arm64 only (Intel Macs are fading out).
- **Signing is required from day one:** Apple Developer Program ($99/year), Developer ID, hardened runtime, notarization on every release. Since macOS 15, unsigned apps can only be opened through System Settings, so even testers need a signed build.
- **Layers:** macOS wheels per layer, **codesigned with our Team ID** in CI (library validation). Not the `disable-library-validation` entitlement. That's why 2c keys layers by platform.
- **Install and store:** a `.dmg` (drag to Applications), store in `~/Library/Application Support/MakeMyEXE`, `.mmx` association through `Info.plist` (document type + UTI), the Hub as the only entry point (no Start menu shortcuts), a "Remove all data" button since uninstall is drag-to-Trash.
- **Engine:** a Mac replacement for `shortcuts.py`, `open` instead of `explorer`, path/case checks, per-OS guide screenshots.
- **CI cost:** macOS minutes count 10× on private repos. Mac runs only for Runner releases and layer builds; custom packs stay Linux-tested (pure Python + allowlist).
- **Not the Mac App Store:** its sandbox forbids running downloaded code. Developer ID distribution only.

Rough effort when we start: 1–2 weeks of code, plus the Apple membership.

