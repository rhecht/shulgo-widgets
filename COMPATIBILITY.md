# ShulGo at a glance on the desktop — what runs where

A web page can't put text in the taskbar or menu bar. Each build below is a small program for one kind of desktop,
all on the same public API (`/api/v1/next`, `/api/v1/zmanim`) with a key from "Link this computer". Each asks
ShulGo every 15 minutes at most, keeps the last answer, counts down locally, and says how old the times are when
offline. None writes files on ShulGo's server.

| Desktop | Build | Where it shows | State |
|---|---|---|---|
| macOS 11+ (Intel, Apple silicon) | [`desktop/`](desktop) (Electron) | Menu bar: the next minyan's time as text; click for the list and zmanim | **Tried and working** |
| Windows 10 / 11 | [`desktop/`](desktop) (Electron) | Notification area icon, tooltip and window | Builds; not yet run by anyone |
| Windows 10 / 11 (no install) | [`windows-tray/shulgo-tray.ps1`](windows-tray/shulgo-tray.ps1) | Notification area icon; tooltip = next minyan and minutes to go; right-click list | Written 2026-11-19; not yet run |
| **Windows 7 SP1, 8, 8.1** | [`windows-tray/shulgo-tray.ps1`](windows-tray/shulgo-tray.ps1) (PowerShell 2 + .NET 3.5, built in) | Same as above | Written 2026-11-19; not yet run. Needs TLS 1.2 (.NET 4.5+ or KB3140245) |
| GNOME 45–50 (Ubuntu, Fedora, JewBuntu) | [`jewbuntu/`](jewbuntu) | Top bar text + menu | **Tried and working** |
| Xfce / old 32-bit hardware (e.g. Pentium III, 256 MB) | [`shulgo-xfce/`](shulgo-xfce) (Python 3 + GTK3) | System tray + popup | Run once in emulation (QEMU, i686) |
| KDE, other Linux panels | [`desktop/`](desktop) (64-bit) or [`shulgo-xfce/`](shulgo-xfce) | Tray icon | Not tried |

**Taskbar text itself:** only the macOS menu bar and the GNOME top bar show live text. Windows shows an icon whose
tooltip and menu hold the times (Windows doesn't let programs write text into the taskbar).

## Not supported, and the fallback

- **Windows XP / Vista, macOS before 10.13, very old browsers:** no TLS 1.2, so they can't reach shulgo.com safely
  (we won't weaken the site's security for them). Fallback: a phone, or ShulGo's phone line (GO-2-SHUL).
- **Any computer with a browser but nothing installable:** bookmark `https://shulgo.com/next`. It's a plain page that
  works without JavaScript, or pin it as the browser's home page.
