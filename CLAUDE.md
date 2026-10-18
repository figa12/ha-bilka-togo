# CLAUDE.md

A Home Assistant custom integration (`bilka_togo`), installed via HACS as a custom repository.
If a `CLAUDE.local.md` exists, read it too: it holds the maintainer's own setup and is never
committed.

## Read first

- **`CONTEXT.md`** is the glossary: shopping list, item, amount, known item,
  previously chosen, preference order, basket, transfer, move, remove, offer, price cut,
  multibuy. Use those words in code, names and UI, and avoid the ones it lists under _Avoid_.
- **`docs/adr/`** holds the decisions. 0001 explains why the shopping list is not the Bilka
  basket.

## Bilka API traps (all verified against the live API, 2026-10-16)

- The `jwt_token` header name must stay lowercase. Bilka answers `Jwt_token` with
  "Missing jwt_token".
- A dropped or missing session does not fail. Bilka answers as the anonymous user
  (`uid: -1`) with a normal 200, so always check `uid`.
- `ChangeLineCount`'s `count` sets the quantity; it does not add. Adding means reading the
  basket first.
- The basket always holds a "Pakkeservice" service line (the packing choice). Never touch it,
  and never count it as an item.
- Prices must be read from `storeData[<store id>]`. The top-level price ignores store-only
  price cuts. The store is the account's pickup store.
- The search index returns only `objectID` unless the fields are named in
  `attributesToRetrieve`.
- Bilka's "Økologisk" tag is missing from some organic products. Also check the name and brand.

## Tests

`.venv/bin/python -m pytest`. The venv has `pytest-homeassistant-custom-component==0.13.365`,
which pins HA 2026.9.2 (the live version), and `home-assistant-frontend==20260826.7`, the
frontend that version needs; bump both together with HA. Client tests use `tests/fake_session.py`, not aioresponses, which does
not work with aiohttp 3.14. Never run tests or scripts that change the real basket without
asking: it is a real person's live Bilka basket.

## Cards

Plain custom elements in `custom_components/bilka_togo/frontend/`, no build step. The
integration serves that folder and adds each card as a frontend module with a content hash, so
no dashboard resource is needed and browsers refetch a changed card. Check syntax with
`node --check`. A card change is not finished until it has been rendered on the real dashboard
at the real size it will be shown at (a wall display, a phone).

Before deploying, a card can be looked at in headless Firefox with a stand-in `hass`:
`firefox --headless --window-size=390,1000 --screenshot out.png file://…/index.html`. The
screenshot is taken at the load event, so fill the card synchronously (set its state and call
its render) rather than through the stand-in's promises. The cards define themselves only once
`home-assistant` is defined, so the page must define a stand-in one
(`customElements.define("home-assistant", class extends HTMLElement {})`).
