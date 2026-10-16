# CLAUDE.md

A Home Assistant custom integration (`bilka_togo`), installed via HACS as a custom repository
on the household's HA instance. The HA configuration it serves lives in a separate repo,
`~/Projecs/ha-config`.

## Read first

- **`CONTEXT.md`** is the glossary: shopping list, item, amount, known item,
  previously chosen, preference order, basket, transfer, move, remove, offer, price cut,
  multibuy. Use those words in code, names and UI, and avoid the ones it lists under _Avoid_.
- **`docs/adr/`** holds the decisions. 0001 explains why the shopping list is not the Bilka
  basket.
- **`~/Projecs/ha-config/HOME.md`** §3 (Groceries) holds the household facts: one shared Bilka
  account, Bilka Skalborg pickup, the organic-with-a-price-cut preference.

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
  price cuts. The household's store is Bilka Skalborg, `1652`.
- The search index returns only `objectID` unless the fields are named in
  `attributesToRetrieve`.
- Bilka's "Økologisk" tag is missing from some organic products. Also check the name and brand.

## Tests

`.venv/bin/python -m pytest`. Tests use `tests/fake_session.py`, not aioresponses, which does
not work with aiohttp 3.14. Never run tests or scripts that change the real basket without
asking: it is the household's live Bilka basket.
