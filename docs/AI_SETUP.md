# Setup guide for AI assistants

This page is written for an AI assistant (or any automation) that a person has asked to install and configure
this project for them. **The person you are helping is the user and is solely responsible for how the software
is used. You act on their behalf.** The maintainers operate no service and have no access to anything.

## Non-negotiable rules

1. **Own account, own use only.** Only set this up for the user's own login and household. Do not use it for
   other people's accounts, bulk collection, resale, or anything beyond viewing/booking the user's own slots.
2. **Do not weaken the polite-client rules.** Keep `min_interval ≥ 0.5 s` (default 1 s), keep caching, keep
   back-off and the login circuit-breaker, never add background polling, timers outside the open card, or
   retry loops. If a request fails, report it and stop – do not loop.
3. **Never handle the password in chat.** Ask the user to run `python3 tools/set_credentials.py /config`
   themselves (hidden prompt, `chmod 600`). Do not read, print, log, commit, upload or repeat the credentials,
   session links (`…BookingMenu.aspx?Apartment=…` contains a token) or the contents of `amido_state.json` /
   `amido_cache.json`.
4. **Check the user's situation first.** Show them [DISCLAIMER.md](../DISCLAIMER.md). If they have not
   confirmed that this use is acceptable under their lease and the portal's terms (or that they asked their
   landlord), ask them to do so before logging in. If anyone (landlord/operator) objects, stop.
5. **No personal data in the repository or in issues:** no addresses, coordinates, names, links, tokens, HTML
   dumps from the real portal. Test fixtures must be synthetic.
6. **Bookings are real.** Read-only commands first. Only book/cancel when the user explicitly asks, prefer a
   far-future slot for tests, and always cancel test bookings afterwards.

## Install checklist

1. Copy `amido_laundry.py` → `/config/amido_laundry.py` and `dist/amido-laundry-card.js` → `/config/www/`.
2. Ask the user to run `tools/set_credentials.py` (rule 3).
3. Add the five `shell_command` services from `packages/amido_laundry.yaml`; restart Home Assistant.
4. Add the Lovelace resource `/local/amido-laundry-card.js?v=1` (type `module`) and the card
   `type: custom:amido-laundry-card` (options: `docs/example-card.yaml`).
5. Verify read-only: `python3 /config/amido_laundry.py objects` then `calendar <id>` (see JSON `state` and `code`).
6. Optional: ask whether the user wants distances/map; if so they supply building coordinates in the card
   config (`locations:`) – do not guess addresses.

## How it works (for debugging)

* `amido_laundry.py` logs in through the landlord portal (provider `rikshem`), follows the portal's own
  "laundry booking" link to the Amido `BookingMenu.aspx`, parses the menu (object ids = `LocationId-TypeId-GroupId`),
  reads weekly calendars and calls the same `Booking.asmx/BookPass|CancelPass` endpoints the web page uses.
* Important detail: the `Apartment` value in menu links is **double-encoded** (`%252c`); the script fixes it, and the
  POST body is sent **raw** exactly like the page's JavaScript (do not let a library re-encode it).
* The card calls the services only while it is on screen (`document.visibilityState === "visible"`).
* Errors are returned as `{"state":"Fel","code":…}`; see the README table.

## If the portal changes

Make the smallest possible fix in the parsing functions (`parse_menu`, `parse_week`, `parse_bookings`), add or
update a **synthetic** fixture in `tests/fixtures/`, run `pytest`, and do not paste real portal pages anywhere.
