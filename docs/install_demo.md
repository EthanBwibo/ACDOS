# Installing the demo app

How to put the ACDOS app on two or three phones for the defence demo, and which account
each phone signs in with. The demo itself, step by step, is in `docs/demo_runbook.md`.

## The APK

- **Where:** the GitHub release `v1.0-defence` (a draft until the freeze), asset
  `acdos-v1.0-defence-debug.apk`. The APK is never committed.
- **Built from:** `main` at c6bcf10 (#277), with `assembleDebug`. It is debug-signed with the
  build laptop's debug key.
- **Talks to:** the Azure API (`https://acdos-api.azurewebsites.net`) and the Supabase project
  `ACDOS`. There is no local or tunnel address in it, so it works on any network with internet
  access.
- **Package:** `com.kq.acdos`, version 1.0, for Android 8.0 (API 26) or later.
- **Check the download:** its SHA-256 is in the release notes. On the laptop run
  `certutil -hashfile acdos-v1.0-defence-debug.apk SHA256`, or in Git Bash run `sha256sum`.

While the release is a draft, only people with access to the repository can see it. Download
the APK on the laptop and use one of the two ways below. Once the release is published, a
phone can download the APK from the release page itself.

## Sideloading

Do this the day before, on every phone.

### A. Over USB with adb (quickest for several phones)

1. On the phone, turn on developer options and USB debugging: **Settings > About phone**, tap
   **Build number** seven times, then **Settings > System > Developer options > USB
   debugging**.
2. Connect the phone to the laptop and accept the "Allow USB debugging?" prompt on the phone.
3. In PowerShell on the laptop, with the APK in the current folder:

   ```
   & "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe" devices
   & "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe" -s <serial> install -r acdos-v1.0-defence-debug.apk
   ```

   `-s <serial>` picks the phone when several are connected; `devices` lists the serials.
   `-r` keeps the app's data if this build is already installed. It should end with
   `Success`.

### B. Without a cable

1. Copy the APK to the phone, e.g. through Google Drive, a USB file transfer, or the release
   page once it is published.
2. Open it from the phone's **Files** app (or from the browser's downloads).
3. Android asks whether to allow that app (Files, Drive or Chrome) to install unknown apps.
   Allow it, go back, and tap **Install**.

### If it won't install

**"App not installed"**, or an adb error with `INSTALL_FAILED_UPDATE_INCOMPATIBLE`, means the
phone has an older ACDOS signed with a different debug key, e.g. built on another computer.
Uninstall it first (**Settings > Apps > ACDOS > Uninstall**, or
`adb -s <serial> uninstall com.kq.acdos`), then install again. Uninstalling also clears the old
app's sign-in and offline queue, which is fine for the demo.

## Which account on which phone

Every account's password is the `SEED_PASSWORD` that `scripts/seed_test_accounts.py` was last
run with. It isn't written down in the repository. The full account list is in
`docs/demo_accounts.md`. The app takes its role from the account; there is no role choice at
sign-in.

### Three phones (one per role)

| Phone | Account | Shows |
|---|---|---|
| 1, the dispatcher | `dispatcher@acdos.test` | Overview, Plan, Routes, Fleet & crew, Messages: plans each wave, records a breakdown, re-plans |
| 2, a driver | The driver of a van in the wave being shown. Defence day: `driver-v01@` … `driver-v20@acdos.test` for `defence-KDX 001` … `020`. Demo morning: `driver-101a@`, `-102a@` or `-103a@acdos.test` for `demo-KDH 101A` … `103A` | The van's current route stop by stop, its Schedule (one route per wave), and Call for the next stop's crew member |
| 3, a crew member | Defence day: a named crew member with a pickup in that wave, e.g. `amina@acdos.test` (early, 04:00–06:30) or `chao@acdos.test` (mid, 08:00–10:00). Demo morning: `crew@acdos.test` | Their pickup and ETA, any change to acknowledge, the preset messages, and Call driver from 30 min before the pickup |

To pick the driver: after planning a wave on phone 1, open **Routes**, note the plate of a
route that has the crew member from phone 3 on it, and sign phone 2 in as that van's driver
(`defence-KDX 004` → `driver-v04@acdos.test`). Then the driver's next stop, the crew
member's pickup and the Call buttons all line up.

### Two phones

- Phone 1 is the dispatcher, as above.
- Phone 2 switches between the driver and the crew member: **⋮ > Profile > Sign out**, then
  sign in as the other account.
- Or run the dispatcher on the laptop's emulator (`Dispatcher_API34`; see the runbook) and
  use both phones for the driver and the crew member.

### Before the demo

1. `https://acdos-api.azurewebsites.net/health` answers `{"status":"ok"}`.
2. The accounts exist and have the expected password: `python scripts/seed_test_accounts.py`
   (safe to re-run).
3. Sign in once on each phone with its account and check that its first screen loads.
4. Nothing is pushed to the phones: Firebase isn't set up (#55). Pull down to refresh on the
   driver's Route tab and the crew member's Pickup tab after each step on the dispatcher's
   phone.
