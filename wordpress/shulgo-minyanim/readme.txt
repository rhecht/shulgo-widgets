=== ShulGo Minyan Times ===
Contributors: shulgo
Tags: synagogue, shul, minyan, jewish, zmanim
Requires at least: 5.0
Tested up to: 6.6
Requires PHP: 7.2
Stable tag: 1.0.0
License: GPLv2 or later

Show your shul's minyan times from ShulGo on your WordPress site — or the next minyanim near a place. Free.

== Description ==

Your times are kept on ShulGo (update them there, or ask us to), and this plugin shows them on your site, always up to date:
this week's Shacharis, Mincha and Maariv, with changes and cancellations, and each day's netz, shkia and candle lighting.

Hotels, kosher restaurants and community sites can show the next minyanim near them instead.

* `[shulgo_times shul="your-shul"]` — your shul's times this week. Use the end of your shul's ShulGo address
  (shulgo.com/shul/**your-shul**), or paste the whole address.
  Options: `days="7"` (1–14), `theme="light|dark|auto"`, `accent="12305a"` (a colour), `zmanim="0"` (no zmanim column),
  `title="0"` (no heading), `height="560"` (used until the frame sizes itself).
* `[shulgo_nearby place="Teaneck, NJ"]` — the next minyanim near a place (or `lat="40.89" lng="-74.01"`).
  Options: `tefillah="mincha"`, `limit="8"`, `radius="1.5"` (miles), `hours="6"`, and the same `theme`, `accent`, `title`, `height`.
* `[shulgo_calendar shul="your-shul"]` — a link that adds your minyanim to Google, Apple or Outlook calendars.

The shortcodes work in posts, pages and the Shortcode block in sidebars and footers.

== Privacy ==

The widget is a frame from ShulGo. ShulGo sets no cookie in it and keeps only a daily count of views per website
(so a shul can see where its times are shown).

== Changelog ==

= 1.0.0 =
* First version: times, nearby minyanim, calendar link.
