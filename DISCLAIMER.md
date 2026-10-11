# Disclaimer – please read before using

**This project is unofficial.** It is not affiliated with, endorsed by, sponsored by or supported by any
landlord, housing company, or by Amido or any of its customers. All product and company names are
trademarks of their respective owners and are used here only to describe compatibility.

## Your responsibility

* You are the only person responsible for how you use this software. By using it you confirm that you
  have read and will follow **the terms that apply to you** – your lease, the landlord's portal/website
  terms, and the terms of the booking system.
* When this project was written (October 2026) no public terms of use covering automated access could be
  found on the landlord pages that were checked, and the portals publish no `robots.txt`. **The absence of a
  rule is not a permission.** If you are unsure, ask your landlord / property manager (a short message
  template is at the end of this file).
* If the portal operator or landlord asks you to stop, **stop**, and remove the software.

## Intended use – and what it must not be used for

Allowed (the intended purpose): *one person using their own account* to look at, book and cancel their own
household's laundry-room and sauna slots from their own Home Assistant, a few times a day at most – the
same thing the web page does for you.

Not allowed / not supported:

* accounts that are not yours, shared "booking services", resale or any commercial use;
* crawling, bulk collection or monitoring of other residents' bookings, or anything beyond the objects you
  are entitled to see;
* circumventing booking quotas, rate limits, captchas or any other protection;
* raising the request rate, adding background polling or scripted loops. The built-in limits
  (request spacing, caching, back-off, login circuit-breaker) are there to protect the portal and **your
  account from being locked** – do not remove them.

## No warranty

The software is provided "as is" (MIT license). The portal can change at any time and break it; a
booking may fail or be made/cancelled incorrectly. **Always verify important bookings in the official
portal.** The authors are not liable for missed or wrong bookings, account problems, or any other damage.

## Privacy and data protection

* Everything runs on **your own** Home Assistant. Nothing is sent to the authors – there is no server,
  telemetry or analytics.
* Your login is stored only in a local file you create (`amido_credentials.json`, chmod 600). Session
  links, caches and state are also local files with the same permissions. Keep your backups private.
* The optional map loads Leaflet from `unpkg.com` (with a subresource-integrity hash) and map tiles from
  OpenStreetMap, and "Directions" opens Google Maps. Those services see your IP address (and, for
  directions, the coordinates in the link). Set `map: false` to avoid all of that.

## Concerns from landlords, portal operators or rights holders

If you represent a landlord, operator or rights holder and have a concern about this project, please open an
issue in the repository. It will be taken seriously and handled promptly.

---

### Template: asking your landlord (Swedish / English)

> Hej! Jag har ett eget hemautomationssystem (Home Assistant) och vill kunna se och boka *mina egna* tider i
> tvättstugan/bastun därifrån, med samma inloggning som jag använder på webben, några gånger per dag.
> Är det okej? / Hello! I run Home Assistant at home and would like to view and book *my own* laundry/sauna
> slots from it, with my normal login, a few times per day. Is that acceptable?
