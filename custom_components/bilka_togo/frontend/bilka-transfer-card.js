/*
 * Bilka transfer card: moving the shopping list into the Bilka basket, on a phone.
 *
 * A transfer is a series of moves with no final confirmation (CONTEXT.md, ADR 0001). The card
 * shows the basket on top and the shopping list underneath. Tapping an item opens it: a count,
 * the products chosen for it before (in preference order), and a search of Bilka's range.
 * Tapping a product is the move: the line goes into the basket and the item leaves the list.
 *
 * - Swipe an item left to delete it (a remove: it never touches the basket), with undo.
 * - Long-press a previously chosen product to forget it for that item.
 * - "Tøm kurv" asks twice; "Til kassen" opens Bilka's checkout, where the order is placed.
 *
 * Everything goes through the bilka_togo actions and the to-do list's own; the card keeps no
 * rules of its own. No build step: a plain custom element, served by the integration.
 */

const UNDO_SECONDS = 5;
const LONG_PRESS_MS = 550;
const SWIPE_OPEN_PX = 60;
const CONFIRM_SECONDS = 3;

const TEXT = {
  da: {
    basket: "Kurven",
    basketEmpty: "Kurven er tom",
    lines: (n) => (n === 1 ? "1 vare" : `${n} varer`),
    empty: "Tøm kurv",
    emptySure: "Tøm? Tryk igen",
    checkout: "Til kassen",
    listEmpty: "Indkøbslisten er tom",
    count: "Antal",
    chosen: "Valgt før",
    search: "Søg i Bilka",
    searchButton: "Søg",
    offersOnly: "Kun tilbud",
    organicOnly: "Kun øko",
    noResults: "Ingen varer fundet",
    organic: "Øko",
    offer: "Tilbud",
    inBasket: (n) => `${n} i kurven`,
    lastTime: (n) => `Sidst ${n} stk`,
    soldOut: "Udsolgt",
    multibuy: (text, have, need) => `${text} · ${have}/${need}`,
    moved: (count, name) => `${count} × ${name} lagt i kurven`,
    delete: "Slet",
    deleteItem: "Fjern fra listen",
    deleted: (name) => `«${name}» slettet`,
    undo: "Fortryd",
    forgetQuestion: (product, item) => `Glem ${product} for «${item}»?`,
    forget: "Glem",
    cancel: "Annuller",
    loading: "Henter…",
    retry: "Prøv igen",
    perUnit: (unit) => `kr/${unit}`,
  },
  en: {
    basket: "Basket",
    basketEmpty: "The basket is empty",
    lines: (n) => (n === 1 ? "1 product" : `${n} products`),
    empty: "Empty basket",
    emptySure: "Sure? Tap again",
    checkout: "Checkout",
    listEmpty: "The shopping list is empty",
    count: "Count",
    chosen: "Chosen before",
    search: "Search Bilka",
    searchButton: "Search",
    offersOnly: "Offers only",
    organicOnly: "Organic only",
    noResults: "Nothing found",
    organic: "Organic",
    offer: "Offer",
    inBasket: (n) => `${n} in basket`,
    lastTime: (n) => `Last ${n}`,
    soldOut: "Sold out",
    multibuy: (text, have, need) => `${text} · ${have}/${need}`,
    moved: (count, name) => `${count} × ${name} added to the basket`,
    delete: "Delete",
    deleteItem: "Remove from list",
    deleted: (name) => `“${name}” deleted`,
    undo: "Undo",
    forgetQuestion: (product, item) => `Forget ${product} for “${item}”?`,
    forget: "Forget",
    cancel: "Cancel",
    loading: "Loading…",
    retry: "Retry",
    perUnit: (unit) => `kr/${unit}`,
  },
};

const sameItem = (a, b) =>
  a.split(/\s+/).join(" ").trim().toLowerCase() === b.split(/\s+/).join(" ").trim().toLowerCase();

const kroner = (ore) =>
  (ore / 100).toLocaleString("da-DK", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/** Build an element: el("div", {class: "x", onclick: f}, child, "text", ...). */
const el = (tag, props = {}, ...children) => {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === undefined || value === null || value === false) continue;
    if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (key === "class") node.className = value;
    else node.setAttribute(key, value === true ? "" : value);
  }
  node.append(...children.flat().filter((c) => c !== null && c !== undefined && c !== false));
  return node;
};

class BilkaTransferCard extends HTMLElement {
  setConfig(config) {
    this._config = {
      entity: "todo.bilka_to_go_shopping_list",
      checkout_url: "https://www.bilkatogo.dk/kassen",
      language: "da",
      ...config,
    };
    this._t = TEXT[this._config.language] || TEXT.da;
    this._transfer = null; // get_transfer's answer
    this._listItems = null; // the to-do list as last seen, to notice changes
    this._open = null; // uid of the item that is open
    this._counts = {}; // uid → chosen count
    this._searches = {}; // uid → {query, offers, organic, results, loading}
    this._busy = new Set(); // "move:<pid>", "empty", "forget:<pid>"
    this._swiped = null; // uid of the row swiped open
    this._forgetting = null; // {uid, pid} awaiting confirmation
    this._error = null;
    if (!this.shadowRoot) this._build();
    this._render();
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) this._subscribe();
  }

  connectedCallback() {
    // Coming back to the phone: Bilka's basket may have changed in the app meanwhile.
    this._onVisible = () => {
      if (document.visibilityState === "visible" && this._hass) this._refresh();
    };
    document.addEventListener("visibilitychange", this._onVisible);
    if (this._hass && !this._unsub) this._subscribe();
  }

  disconnectedCallback() {
    document.removeEventListener("visibilitychange", this._onVisible);
    if (this._unsub) {
      this._unsub();
      this._unsub = undefined;
    }
  }

  getCardSize() {
    return 3 + (this._transfer?.items.length || 0);
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6 };
  }

  // --- talking to Home Assistant -------------------------------------------------------------

  async _action(service, data = {}) {
    const result = await this._hass.callWS({
      type: "call_service",
      domain: "bilka_togo",
      service,
      service_data: data,
      return_response: true,
    });
    return result.response;
  }

  async _subscribe() {
    if (!this._hass || this._unsub || !this.isConnected) return;
    try {
      this._unsub = await this._hass.connection.subscribeMessage(
        (message) => {
          const items = message.items.filter((item) => item.status === "needs_action");
          const seen = JSON.stringify(items.map((i) => [i.uid, i.summary, i.description]));
          if (seen === this._listItems) return;
          this._listItems = seen;
          this._refreshSoon();
        },
        { type: "todo/item/subscribe", entity_id: this._config.entity },
      );
    } catch (err) {
      this._fail(err);
    }
  }

  _refreshSoon() {
    clearTimeout(this._refreshTimer);
    this._refreshTimer = setTimeout(() => this._refresh(), 300);
  }

  async _refresh() {
    try {
      this._transfer = await this._action("get_transfer");
      this._error = null;
      const uids = new Set(this._transfer.items.map((i) => i.uid));
      if (this._open && !uids.has(this._open)) this._open = null;
    } catch (err) {
      this._fail(err, false);
    }
    this._render();
  }

  async _search(item) {
    const search = this._searchOf(item);
    if (!search.query.trim()) return;
    search.loading = true;
    this._render();
    try {
      const { products } = await this._action("search", {
        query: search.query.trim(),
        offers_only: search.offers,
        organic_only: search.organic,
      });
      search.results = products;
      this._error = null;
    } catch (err) {
      this._fail(err, false);
    }
    search.loading = false;
    this._render();
  }

  async _move(item, product) {
    const key = `move:${product.id}`;
    if (this._busy.size) return;
    const count = this._countOf(item);
    this._busy.add(key);
    this._render();
    try {
      const result = await this._action("move", {
        item: item.uid,
        product_id: product.id,
        count,
      });
      this._transfer.basket = result.basket;
      // Work through the list: the next item opens by itself.
      const items = this._transfer.items;
      const next = items[items.findIndex((i) => i.uid === item.uid) + 1];
      this._transfer.items = items.filter((i) => i.uid !== item.uid);
      this._open = next ? next.uid : null;
      if (next) this._autoSearch(next);
      this._error = null;
      this._toast(this._t.moved(count, product.name));
    } catch (err) {
      this._fail(err, false);
    }
    this._busy.delete(key);
    this._render();
  }

  async _emptyBasket() {
    if (!this._confirmEmpty) {
      this._confirmEmpty = true;
      this._render();
      clearTimeout(this._confirmTimer);
      this._confirmTimer = setTimeout(() => {
        this._confirmEmpty = false;
        this._render();
      }, CONFIRM_SECONDS * 1000);
      return;
    }
    clearTimeout(this._confirmTimer);
    this._confirmEmpty = false;
    this._busy.add("empty");
    this._render();
    try {
      this._transfer.basket = (await this._action("empty_basket")).basket;
      this._error = null;
    } catch (err) {
      this._fail(err, false);
    }
    this._busy.delete("empty");
    this._render();
  }

  async _forget(item, product) {
    this._forgetting = null;
    this._busy.add(`forget:${product.id}`);
    this._render();
    try {
      await this._action("forget", { item: item.name, product_id: product.id });
      item.previously_chosen = item.previously_chosen.filter((p) => p.id !== product.id);
      if (!item.previously_chosen.length) this._autoSearch(item);
    } catch (err) {
      this._fail(err, false);
    }
    this._busy.delete(`forget:${product.id}`);
    this._render();
  }

  async _delete(item) {
    this._swiped = null;
    const items = this._transfer.items;
    const index = items.findIndex((i) => i.uid === item.uid);
    const previous = index > 0 ? items[index - 1].uid : null;
    try {
      await this._hass.callService(
        "todo", "remove_item", { item: item.uid }, { entity_id: this._config.entity },
      );
    } catch (err) {
      this._fail(err);
      return;
    }
    this._transfer.items = items.filter((i) => i.uid !== item.uid);
    if (this._open === item.uid) this._open = null;
    this._render();
    this._toast(this._t.deleted(item.name), this._t.undo, () => this._restore(item, previous));
  }

  async _restore(item, previous) {
    const data = { item: item.name };
    if (item.amount) data.description = item.amount;
    await this._hass.callService("todo", "add_item", data, { entity_id: this._config.entity });
    // Put it back where it was once the list has it again.
    for (let tries = 0; tries < 40; tries++) {
      const restored = this._transfer?.items.find((i) => sameItem(i.name, item.name));
      if (restored) {
        if (previous || this._transfer.items[0].uid !== restored.uid) {
          const move = { type: "todo/item/move", entity_id: this._config.entity, uid: restored.uid };
          if (previous && this._transfer.items.some((i) => i.uid === previous)) {
            move.previous_uid = previous;
          }
          try { await this._hass.callWS(move); } catch (err) { /* the end of the list is fine */ }
        }
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
  }

  _fail(err, render = true) {
    console.error("bilka-transfer-card:", err);
    this._error = err?.message || String(err);
    if (render) this._render();
  }

  // --- state helpers ---------------------------------------------------------------------------

  _countOf(item) {
    if (!(item.uid in this._counts)) {
      this._counts[item.uid] =
        item.suggested_count || item.previously_chosen[0]?.last_count || 1;
    }
    return this._counts[item.uid];
  }

  _searchOf(item) {
    if (!this._searches[item.uid]) {
      this._searches[item.uid] = {
        query: item.name, offers: false, organic: false, results: null, loading: false,
      };
    }
    return this._searches[item.uid];
  }

  /** An item with nothing chosen before goes straight to Bilka's range. */
  _autoSearch(item) {
    const search = this._searchOf(item);
    if (!item.previously_chosen.length && search.results === null && !search.loading) {
      this._search(item);
    }
  }

  _toggle(item) {
    this._swiped = null;
    this._forgetting = null;
    this._open = this._open === item.uid ? null : item.uid;
    if (this._open) this._autoSearch(item);
    this._render();
    if (this._open) {
      requestAnimationFrame(() =>
        this.shadowRoot.querySelector(".row.open")?.scrollIntoView({ block: "nearest", behavior: "smooth" }),
      );
    }
  }

  _toast(text, action, onAction) {
    const bar = this.shadowRoot.getElementById("toast");
    bar.replaceChildren(el("span", {}, text));
    if (action) {
      bar.append(el("button", {
        type: "button",
        onclick: () => { bar.classList.remove("shown"); onAction(); },
      }, action));
    }
    bar.classList.add("shown");
    clearTimeout(this._toastTimer);
    this._toastTimer = setTimeout(() => bar.classList.remove("shown"), UNDO_SECONDS * 1000);
  }

  // --- drawing ---------------------------------------------------------------------------------

  _build() {
    const root = this.attachShadow({ mode: "open" });
    root.innerHTML = `
      <style>
        :host {
          --bilka-primary: var(--md-sys-color-primary, var(--primary-color));
          --bilka-on-primary: var(--md-sys-color-on-primary, var(--text-primary-color, #fff));
          --bilka-card: var(--ha-card-background, var(--card-background-color));
          --bilka-surface: var(--md-sys-color-surface-container-high, var(--secondary-background-color));
          --bilka-outline: var(--md-sys-color-outline-variant, var(--divider-color));
          --bilka-offer: var(--md-sys-color-error, #c62828);
          --bilka-organic: #2e7d32;
          --bilka-radius: var(--ha-card-border-radius, 16px);
          display: block;
          color: var(--primary-text-color);
          font-size: 15px;
        }
        button { font: inherit; color: inherit; cursor: pointer; border: none; background: none;
          -webkit-tap-highlight-color: transparent; }
        button:disabled { opacity: .45; cursor: default; }
        #basket {
          position: sticky; top: 0; z-index: 2;
          background: var(--bilka-card); border-radius: var(--bilka-radius);
          padding: 12px 14px; margin-bottom: 12px;
          box-shadow: var(--ha-card-box-shadow, none);
        }
        .basket-line { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
        .basket-title { font-size: 17px; font-weight: 500; }
        .basket-total { font-size: 17px; font-weight: 600; white-space: nowrap; }
        .basket-sub { color: var(--secondary-text-color); font-size: 13px; margin-top: 2px; }
        .basket-actions { display: flex; gap: 8px; margin-top: 10px; }
        .basket-actions > * { flex: 1 1 0; height: 40px; border-radius: 20px; font-size: 15px;
          display: flex; align-items: center; justify-content: center; text-decoration: none; }
        #empty-basket { border: 1px solid var(--bilka-outline); }
        #empty-basket.sure { background: var(--bilka-offer); color: #fff; border-color: transparent; }
        #checkout { background: var(--bilka-primary); color: var(--bilka-on-primary); font-weight: 500; }
        #error { display: none; background: var(--md-sys-color-error-container, #fdecea);
          color: var(--md-sys-color-on-error-container, #611a15); border-radius: 12px;
          padding: 10px 14px; margin-bottom: 12px; font-size: 14px; }
        #error.shown { display: flex; align-items: center; gap: 10px; justify-content: space-between; }
        #error button { font-weight: 500; padding: 6px 8px; }
        ul { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
        .row { background: var(--bilka-card); border-radius: var(--bilka-radius); overflow: hidden;
          box-shadow: var(--ha-card-box-shadow, none); }
        .slide { position: relative; overflow: hidden; }
        .delete { position: absolute; inset: 0 0 0 auto; width: 96px; background: var(--bilka-offer);
          color: #fff; font-weight: 500; visibility: hidden; }
        /* Cards can be see-through, so Slet is only there while a row is swiped. */
        .swiped .delete, .slide.revealing .delete { visibility: visible; }
        .head { position: relative; display: flex; align-items: center; gap: 10px;
          min-height: 56px; padding: 0 14px; background: var(--bilka-card);
          touch-action: pan-y; user-select: none; transition: transform .2s ease; }
        .head.dragging { transition: none; }
        .swiped .head { transform: translateX(-96px); }
        .name { flex: 1 1 auto; font-size: 17px; overflow-wrap: anywhere; }
        .amount { color: var(--secondary-text-color); font-size: 15px; margin-left: 8px; }
        .chevron { color: var(--secondary-text-color); transition: transform .2s; font-size: 14px; }
        .open .chevron { transform: rotate(180deg); }
        .body { padding: 2px 12px 14px; border-top: 1px solid var(--bilka-outline); }
        .counter { display: flex; align-items: center; justify-content: space-between; padding: 10px 2px; }
        .stepper { display: flex; align-items: center; gap: 4px; }
        .stepper button { width: 40px; height: 40px; border-radius: 20px; font-size: 22px;
          background: var(--bilka-surface); }
        .stepper span { min-width: 36px; text-align: center; font-size: 19px; font-weight: 600; }
        h3 { font-size: 13px; font-weight: 500; text-transform: uppercase; letter-spacing: .04em;
          color: var(--secondary-text-color); margin: 10px 2px 6px; }
        .tiles { display: flex; flex-direction: column; gap: 6px; }
        .tile { position: relative; display: flex; align-items: center; gap: 10px; width: 100%;
          text-align: left; padding: 8px; border-radius: 12px; background: var(--bilka-surface);
          user-select: none; -webkit-user-select: none; -webkit-touch-callout: none; }
        .tile:active:not(:disabled) { filter: brightness(.94); }
        .tile.busy { opacity: .6; }
        .tile img, .tile .noimg { flex: 0 0 52px; width: 52px; height: 52px; border-radius: 8px;
          object-fit: contain; background: #fff; pointer-events: none; }
        .info { flex: 1 1 auto; min-width: 0; }
        .pname { font-size: 15px; line-height: 1.25; display: -webkit-box; -webkit-line-clamp: 2;
          -webkit-box-orient: vertical; overflow: hidden; }
        .meta { color: var(--secondary-text-color); font-size: 13px; margin-top: 1px; }
        .tags { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 4px; }
        .tag { font-size: 11px; font-weight: 600; padding: 2px 6px; border-radius: 6px;
          border: 1px solid var(--bilka-outline); color: var(--secondary-text-color); }
        .tag.offer { background: var(--bilka-offer); color: #fff; border-color: transparent; }
        .tag.organic { background: var(--bilka-organic); color: #fff; border-color: transparent; }
        .tag.full { border-color: var(--bilka-organic); color: var(--bilka-organic); }
        .tag.have { border-color: var(--bilka-primary); color: var(--bilka-primary); }
        .price { flex: 0 0 auto; text-align: right; white-space: nowrap; }
        .now { font-size: 16px; font-weight: 600; }
        .tile.cut .now { color: var(--bilka-offer); }
        .was { font-size: 12px; color: var(--secondary-text-color); text-decoration: line-through; }
        .unit { font-size: 11px; color: var(--secondary-text-color); }
        .forget { display: flex; align-items: center; gap: 8px; min-height: 68px; box-sizing: border-box;
          padding: 8px 8px 8px 12px; border-radius: 12px; background: var(--bilka-surface);
          border: 1px solid var(--bilka-offer); font-size: 14px; }
        .forget span { flex: 1 1 auto; }
        .forget button { height: 36px; padding: 0 12px; border-radius: 18px; font-weight: 500; }
        .forget .yes { background: var(--bilka-offer); color: #fff; }
        form { display: flex; gap: 6px; }
        input { flex: 1 1 auto; min-width: 0; font: inherit; font-size: 16px; color: inherit;
          background: var(--bilka-surface); border: 2px solid transparent; border-radius: 12px;
          height: 44px; padding: 0 12px; box-sizing: border-box; }
        input:focus { outline: none; border-color: var(--bilka-primary); }
        form button { flex: 0 0 auto; height: 44px; padding: 0 16px; border-radius: 12px;
          background: var(--bilka-primary); color: var(--bilka-on-primary); font-weight: 500; }
        .filters { display: flex; gap: 6px; margin: 8px 0; }
        .filter { height: 32px; padding: 0 12px; border-radius: 16px; font-size: 14px;
          border: 1px solid var(--bilka-outline); }
        .filter.on { background: var(--bilka-primary); color: var(--bilka-on-primary);
          border-color: transparent; }
        .note { color: var(--secondary-text-color); font-size: 14px; padding: 8px 2px; }
        .remove-item { display: block; margin: 12px auto 0; padding: 8px 12px;
          color: var(--secondary-text-color); font-size: 14px; }
        .list-empty { background: var(--bilka-card); border-radius: var(--bilka-radius);
          padding: 18px 14px; color: var(--secondary-text-color); }
        #toast { position: fixed; left: 12px; right: 12px; bottom: calc(96px + env(safe-area-inset-bottom));
          z-index: 10; display: none; align-items: center; justify-content: space-between; gap: 12px;
          min-height: 48px; padding: 4px 6px 4px 16px; border-radius: 12px;
          background: var(--md-sys-color-inverse-surface, #333);
          color: var(--md-sys-color-inverse-on-surface, #fff); font-size: 15px;
          box-shadow: 0 4px 12px rgba(0, 0, 0, .25); }
        #toast.shown { display: flex; }
        #toast button { height: 40px; padding: 0 14px; font-weight: 600;
          color: var(--md-sys-color-inverse-primary, var(--bilka-primary)); }
      </style>
      <div id="basket"></div>
      <div id="error"></div>
      <ul id="list"></ul>
      <div id="toast"></div>
    `;
  }

  _render() {
    if (!this.shadowRoot || !this._config) return;
    // Keep the search field as it was across a redraw.
    const active = this.shadowRoot.activeElement;
    const focused = active?.dataset?.uid && active.tagName === "INPUT"
      ? { uid: active.dataset.uid, start: active.selectionStart, end: active.selectionEnd }
      : null;

    this._renderBasket();
    this._renderError();
    this._renderList();

    if (focused) {
      const input = this.shadowRoot.querySelector(`input[data-uid="${focused.uid}"]`);
      if (input) {
        input.focus();
        input.setSelectionRange(focused.start, focused.end);
      }
    }
  }

  _renderBasket() {
    const t = this._t;
    const basket = this._transfer?.basket;
    const box = this.shadowRoot.getElementById("basket");
    if (!basket) {
      box.replaceChildren(el("div", { class: "basket-sub" }, this._error ? "" : t.loading));
      return;
    }
    box.replaceChildren(
      el("div", { class: "basket-line" },
        el("span", { class: "basket-title" },
          basket.lines ? `${t.basket} · ${t.lines(basket.lines)}` : t.basketEmpty),
        basket.lines ? el("span", { class: "basket-total" }, `${kroner(basket.total)} kr`) : null,
      ),
      el("div", { class: "basket-actions" },
        el("button", {
          id: "empty-basket",
          type: "button",
          class: this._confirmEmpty ? "sure" : "",
          disabled: !basket.lines || this._busy.has("empty"),
          onclick: () => this._emptyBasket(),
        }, this._confirmEmpty ? t.emptySure : t.empty),
        el("a", {
          id: "checkout", href: this._config.checkout_url, target: "_blank", rel: "noopener",
        }, `${t.checkout} →`),
      ),
    );
  }

  _renderError() {
    const box = this.shadowRoot.getElementById("error");
    box.classList.toggle("shown", Boolean(this._error));
    box.replaceChildren(
      el("span", {}, this._error || ""),
      el("button", { type: "button", onclick: () => this._refresh() }, this._t.retry),
    );
  }

  _renderList() {
    const list = this.shadowRoot.getElementById("list");
    if (!this._transfer) {
      list.replaceChildren();
      return;
    }
    const items = this._transfer.items;
    if (!items.length) {
      list.replaceChildren(el("li", { class: "list-empty" }, this._t.listEmpty));
      return;
    }
    list.replaceChildren(...items.map((item) => this._row(item)));
  }

  _row(item) {
    const open = this._open === item.uid;
    const head = el("div", { class: "head", role: "button", "aria-expanded": String(open) },
      el("span", { class: "name" }, item.name,
        item.amount ? el("span", { class: "amount" }, item.amount) : null),
      el("span", { class: "chevron" }, "▾"),
    );
    this._swipeable(head, item);
    return el("li", { class: `row${open ? " open" : ""}${this._swiped === item.uid ? " swiped" : ""}` },
      el("div", { class: "slide" },
        el("button", { class: "delete", type: "button", onclick: () => this._delete(item) }, this._t.delete),
        head,
      ),
      open ? this._body(item) : null,
    );
  }

  _body(item) {
    const t = this._t;
    const search = this._searchOf(item);
    const count = this._countOf(item);
    const setCount = (n) => {
      this._counts[item.uid] = Math.min(99, Math.max(1, n));
      this._render();
    };
    return el("div", { class: "body" },
      el("div", { class: "counter" },
        el("span", {}, t.count),
        el("div", { class: "stepper" },
          el("button", { type: "button", disabled: count <= 1, onclick: () => setCount(count - 1) }, "−"),
          el("span", {}, String(count)),
          el("button", { type: "button", disabled: count >= 99, onclick: () => setCount(count + 1) }, "+"),
        ),
      ),
      item.previously_chosen.length ? [
        el("h3", {}, t.chosen),
        el("div", { class: "tiles" }, item.previously_chosen.map((p) => this._tile(item, p, true))),
      ] : null,
      el("h3", {}, t.search),
      el("form", {
        autocomplete: "off",
        onsubmit: (event) => {
          event.preventDefault();
          this.shadowRoot.activeElement?.blur();
          this._search(item);
        },
      },
        el("input", {
          type: "search", enterkeyhint: "search", value: search.query, "data-uid": item.uid,
          oninput: (event) => { search.query = event.target.value; },
        }),
        el("button", { type: "submit" }, t.searchButton),
      ),
      el("div", { class: "filters" },
        this._filter(item, "offers", t.offersOnly),
        this._filter(item, "organic", t.organicOnly),
      ),
      search.loading ? el("div", { class: "note" }, t.loading)
        : search.results && !search.results.length ? el("div", { class: "note" }, t.noResults)
        : search.results ? el("div", { class: "tiles" }, search.results.map((p) => this._tile(item, p, false)))
        : null,
      el("button", { class: "remove-item", type: "button", onclick: () => this._delete(item) }, t.deleteItem),
    );
  }

  _filter(item, key, label) {
    const search = this._searchOf(item);
    return el("button", {
      type: "button",
      class: `filter${search[key] ? " on" : ""}`,
      "aria-pressed": String(search[key]),
      onclick: () => { search[key] = !search[key]; this._search(item); },
    }, label);
  }

  _tile(item, product, chosen) {
    const t = this._t;
    const busy = this._busy.has(`move:${product.id}`) || this._busy.has(`forget:${product.id}`);
    const mb = product.multibuy;
    const unit = (product.unit_price_unit || "").replace(/\.$/, "").toLowerCase();
    const tile = el("button", {
      type: "button",
      class: `tile${product.price_cut ? " cut" : ""}${busy ? " busy" : ""}`,
      disabled: !product.in_stock || (this._busy.size > 0 && !busy),
    },
      product.image
        ? el("img", { src: product.image, alt: "", loading: "lazy", draggable: "false" })
        : el("div", { class: "noimg" }),
      el("div", { class: "info" },
        el("div", { class: "pname" }, product.name),
        el("div", { class: "meta" }, [product.brand, product.size].filter(Boolean).join(" · ")),
        el("div", { class: "tags" },
          product.price_cut ? el("span", { class: "tag offer" }, t.offer) : null,
          product.organic ? el("span", { class: "tag organic" }, t.organic) : null,
          mb ? el("span", { class: `tag${mb.in_basket >= mb.units ? " full" : ""}` },
            t.multibuy(mb.description, mb.in_basket, mb.units)) : null,
          product.in_basket ? el("span", { class: "tag have" }, t.inBasket(product.in_basket)) : null,
          chosen && product.last_count ? el("span", { class: "tag" }, t.lastTime(product.last_count)) : null,
          !product.in_stock ? el("span", { class: "tag" }, t.soldOut) : null,
        ),
      ),
      el("div", { class: "price" },
        el("div", { class: "now" }, kroner(product.price)),
        product.price_cut ? el("div", { class: "was" }, kroner(product.normal_price)) : null,
        product.unit_price ? el("div", { class: "unit" },
          `${kroner(product.unit_price)} ${t.perUnit(unit)}`) : null,
      ),
    );
    let pressed = false;
    tile.addEventListener("click", () => {
      if (pressed) { pressed = false; return; }
      this._move(item, product);
    });
    if (!chosen) return tile;

    // Long-press: forget this product for this item.
    let timer;
    let start;
    const cancel = () => clearTimeout(timer);
    tile.addEventListener("contextmenu", (event) => event.preventDefault());
    tile.addEventListener("pointerdown", (event) => {
      start = [event.clientX, event.clientY];
      pressed = false;
      timer = setTimeout(() => {
        pressed = true;
        this._forgetting = { uid: item.uid, pid: product.id };
        this._render();
      }, LONG_PRESS_MS);
    });
    tile.addEventListener("pointermove", (event) => {
      if (start && Math.hypot(event.clientX - start[0], event.clientY - start[1]) > 10) cancel();
    });
    tile.addEventListener("pointerup", cancel);
    tile.addEventListener("pointercancel", cancel);

    const forgetting = this._forgetting?.uid === item.uid && this._forgetting.pid === product.id;
    if (!forgetting) return tile;
    return el("div", { class: "forget" },
      el("span", {}, t.forgetQuestion(product.name, item.name)),
      el("button", { type: "button", onclick: () => { this._forgetting = null; this._render(); } }, t.cancel),
      el("button", { type: "button", class: "yes", onclick: () => this._forget(item, product) }, t.forget),
    );
  }

  /** Swipe a row left to show Slet; a tap opens it, or closes the swipe. */
  _swipeable(head, item) {
    let start = null;
    let dx = 0;
    let dragging = false;
    const base = () => (this._swiped === item.uid ? -96 : 0);
    head.addEventListener("pointerdown", (event) => {
      start = [event.clientX, event.clientY];
      dx = 0;
      dragging = false;
      // A drag that ended in a redraw never gets its click, so the flag is reset here.
      this._suppressClick = false;
    });
    head.addEventListener("pointermove", (event) => {
      if (!start) return;
      const x = event.clientX - start[0];
      const y = event.clientY - start[1];
      if (!dragging && Math.abs(x) > 10 && Math.abs(x) > Math.abs(y)) {
        dragging = true;
        head.classList.add("dragging");
        head.parentElement.classList.add("revealing");
        head.setPointerCapture(event.pointerId);
      }
      if (dragging) {
        dx = x;
        head.style.transform = `translateX(${Math.min(0, Math.max(-120, base() + dx))}px)`;
      }
    });
    const end = () => {
      if (!start) return;
      start = null;
      head.classList.remove("dragging");
      head.parentElement.classList.remove("revealing");
      head.style.transform = "";
      if (!dragging) return;
      const offset = base() + dx;
      this._swiped = offset < -SWIPE_OPEN_PX ? item.uid : null;
      this._suppressClick = true;
      this._render();
    };
    head.addEventListener("pointerup", end);
    head.addEventListener("pointercancel", end);
    head.addEventListener("click", () => {
      if (this._suppressClick) { this._suppressClick = false; return; }
      if (this._swiped) {
        this._swiped = null;
        this._render();
        return;
      }
      this._toggle(item);
    });
  }
}

customElements.define("bilka-transfer-card", BilkaTransferCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "bilka-transfer-card",
  name: "Bilka transfer",
  description: "Move the household's shopping list into the Bilka To Go basket, on a phone.",
});
