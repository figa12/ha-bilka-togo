/*
 * Bilka shopping list card: adding to the household's shopping list on the kitchen wall display.
 *
 * Built for one job, done standing at a touch screen: type a name (or tap a known item),
 * optionally an amount, and it is on the list. The list underneath shows what is already there,
 * each row with a ✕ that removes it, and a few seconds to undo.
 *
 * The integration enforces the list's rules (no item twice, amounts joined), so the card only
 * calls the to-do list's own actions. Suggestions come from bilka_togo.known_items: names that
 * have been through a transfer, never just anything someone typed.
 *
 * No build step: a plain custom element, served by the integration.
 */

const UNDO_SECONDS = 5;
const MAX_SUGGESTIONS = 10;

const TEXT = {
  da: {
    name: "Vare",
    amount: "Mængde",
    add: "Tilføj",
    empty: "Indkøbslisten er tom",
    removed: (name) => `«${name}» fjernet`,
    undo: "Fortryd",
    remove: (name) => `Fjern ${name}`,
  },
  en: {
    name: "Item",
    amount: "Amount",
    add: "Add",
    empty: "The shopping list is empty",
    removed: (name) => `“${name}” removed`,
    undo: "Undo",
    remove: (name) => `Remove ${name}`,
  },
};

const sameItem = (a, b) =>
  a.split(/\s+/).join(" ").trim().toLowerCase() === b.split(/\s+/).join(" ").trim().toLowerCase();

class BilkaShoppingListCard extends HTMLElement {
  setConfig(config) {
    this._config = {
      entity: "todo.bilka_to_go_shopping_list",
      // Open the keyboard when the card's pop-up opens (Bubble Card hash), or on load if true.
      autofocus_hash: null,
      language: "da",
      ...config,
    };
    this._t = TEXT[this._config.language] || TEXT.da;
    this._items = [];
    this._known = [];
    if (!this.shadowRoot) this._build();
  }

  // A getter as well as a setter: dashboard plugins (UIX) read a card's hass back, and Home
  // Assistant turns any error while handing hass over into a bare "Configuration error".
  get hass() {
    return this._hass;
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) {
      this._subscribe();
      this._loadKnown();
    }
  }

  connectedCallback() {
    this._onLocation = () => this._maybeFocus();
    window.addEventListener("location-changed", this._onLocation);
    window.addEventListener("hashchange", this._onLocation);
    if (this._hass && !this._unsub) this._subscribe();
    this._maybeFocus();
  }

  disconnectedCallback() {
    window.removeEventListener("location-changed", this._onLocation);
    window.removeEventListener("hashchange", this._onLocation);
    this._unsubscribe();
  }

  getCardSize() {
    return 2 + Math.min(this._items.length, 8);
  }

  _build() {
    const root = this.attachShadow({ mode: "open" });
    root.innerHTML = `
      <style>
        :host {
          --bilka-primary: var(--md-sys-color-primary, var(--primary-color));
          --bilka-on-primary: var(--md-sys-color-on-primary, var(--text-primary-color, #fff));
          --bilka-surface: var(--md-sys-color-surface-container-high, var(--secondary-background-color));
          --bilka-outline: var(--md-sys-color-outline-variant, var(--divider-color));
          display: block;
          color: var(--primary-text-color);
        }
        form { display: flex; gap: 12px; padding: 4px 0 12px; }
        input {
          font: inherit; font-size: 22px; color: inherit;
          background: var(--bilka-surface);
          border: 2px solid transparent; border-radius: 16px;
          height: 64px; padding: 0 20px; box-sizing: border-box; min-width: 0;
        }
        input:focus { outline: none; border-color: var(--bilka-primary); }
        input::placeholder { color: var(--secondary-text-color); }
        /* The name gets the room: on a narrow pop-up the amount shrinks first. */
        #name { flex: 3 1 0; }
        #amount { flex: 1 1 0; min-width: 110px; max-width: 170px; }
        button { font: inherit; cursor: pointer; border: none; -webkit-tap-highlight-color: transparent; }
        #add {
          flex: 0 0 auto; height: 64px; padding: 0 28px; border-radius: 16px;
          font-size: 20px; font-weight: 500;
          background: var(--bilka-primary); color: var(--bilka-on-primary);
        }
        #add:disabled { opacity: .4; cursor: default; }
        #chips { display: flex; flex-wrap: wrap; gap: 10px; padding-bottom: 16px; }
        #chips:empty { display: none; }
        .chip {
          height: 48px; padding: 0 20px; border-radius: 24px; font-size: 19px;
          background: transparent; color: inherit; border: 1px solid var(--bilka-outline);
        }
        .chip.on-list { opacity: .55; }
        ul { list-style: none; margin: 0; padding: 0; }
        li {
          display: flex; align-items: center; gap: 16px;
          min-height: 64px; padding: 0 4px 0 8px;
          border-top: 1px solid var(--bilka-outline);
        }
        li:first-child { border-top: none; }
        .item { flex: 1 1 auto; font-size: 22px; overflow-wrap: anywhere; }
        .amount { color: var(--secondary-text-color); font-size: 19px; margin-left: 10px; }
        .remove {
          flex: 0 0 56px; height: 56px; border-radius: 28px; background: transparent;
          color: var(--secondary-text-color); font-size: 26px; line-height: 56px;
        }
        .remove:active { background: var(--bilka-surface); }
        #empty { color: var(--secondary-text-color); font-size: 20px; padding: 16px 8px; }
        #undo {
          display: none; align-items: center; justify-content: space-between; gap: 16px;
          margin-top: 12px; padding: 0 8px 0 20px; min-height: 64px; border-radius: 16px;
          background: var(--md-sys-color-inverse-surface, #333);
          color: var(--md-sys-color-inverse-on-surface, #fff); font-size: 20px;
        }
        #undo.shown { display: flex; }
        #undo button {
          height: 48px; padding: 0 20px; border-radius: 24px; font-size: 20px; font-weight: 500;
          background: transparent; color: var(--md-sys-color-inverse-primary, var(--bilka-primary));
        }
      </style>
      <form autocomplete="off">
        <input id="name" enterkeyhint="done" autocapitalize="none" autocorrect="off" spellcheck="false">
        <input id="amount" enterkeyhint="done" autocapitalize="none" autocorrect="off" spellcheck="false">
        <button id="add" type="submit" disabled></button>
      </form>
      <div id="chips"></div>
      <ul id="list"></ul>
      <div id="empty"></div>
      <div id="undo"><span id="undo-text"></span><button id="undo-button" type="button"></button></div>
    `;
    const $ = (id) => root.getElementById(id);
    this._name = $("name");
    this._amount = $("amount");
    this._addButton = $("add");
    this._name.placeholder = this._t.name;
    this._amount.placeholder = this._t.amount;
    this._addButton.textContent = this._t.add;
    $("empty").textContent = this._t.empty;
    $("undo-button").textContent = this._t.undo;

    root.querySelector("form").addEventListener("submit", (event) => {
      event.preventDefault();
      this._add(this._name.value, this._amount.value);
    });
    this._name.addEventListener("input", () => {
      this._addButton.disabled = !this._name.value.trim();
      this._renderChips();
    });
    $("undo-button").addEventListener("click", () => this._undo());
    this._renderList();
  }

  async _subscribe() {
    if (!this._hass || this._unsub || !this.isConnected) return;
    try {
      this._unsub = await this._hass.connection.subscribeMessage(
        (message) => {
          this._items = message.items.filter((item) => item.status === "needs_action");
          this._renderList();
          this._renderChips();
        },
        { type: "todo/item/subscribe", entity_id: this._config.entity },
      );
    } catch (err) {
      console.error("bilka-shopping-list-card: could not follow the list", err);
    }
  }

  _unsubscribe() {
    if (this._unsub) {
      this._unsub();
      this._unsub = undefined;
    }
  }

  async _loadKnown() {
    try {
      const result = await this._hass.callWS({
        type: "call_service",
        domain: "bilka_togo",
        service: "known_items",
        service_data: {},
        return_response: true,
      });
      this._known = result.response.items || [];
    } catch (err) {
      this._known = [];
    }
    this._renderChips();
  }

  async _add(name, amount) {
    name = name.trim();
    if (!name) return;
    const data = { item: name };
    if (amount.trim()) data.description = amount.trim();
    this._name.value = "";
    this._amount.value = "";
    this._addButton.disabled = true;
    this._renderChips();
    try {
      await this._hass.callService("todo", "add_item", data, { entity_id: this._config.entity });
    } catch (err) {
      // Put the text back so nothing typed is lost.
      this._name.value = name;
      this._amount.value = amount;
      this._addButton.disabled = false;
      console.error("bilka-shopping-list-card: could not add", err);
      return;
    }
    this._name.focus();
  }

  async _remove(item) {
    const index = this._items.findIndex((i) => i.uid === item.uid);
    const previous = index > 0 ? this._items[index - 1].uid : null;
    await this._hass.callService(
      "todo", "remove_item", { item: item.uid }, { entity_id: this._config.entity },
    );
    this._showUndo({ name: item.summary, amount: item.description || "", previous });
  }

  _showUndo(removed) {
    this._removed = removed;
    const bar = this.shadowRoot.getElementById("undo");
    this.shadowRoot.getElementById("undo-text").textContent = this._t.removed(removed.name);
    bar.classList.add("shown");
    clearTimeout(this._undoTimer);
    this._undoTimer = setTimeout(() => {
      bar.classList.remove("shown");
      this._removed = undefined;
    }, UNDO_SECONDS * 1000);
  }

  async _undo() {
    const removed = this._removed;
    if (!removed) return;
    this._removed = undefined;
    clearTimeout(this._undoTimer);
    this.shadowRoot.getElementById("undo").classList.remove("shown");
    const data = { item: removed.name };
    if (removed.amount) data.description = removed.amount;
    await this._hass.callService("todo", "add_item", data, { entity_id: this._config.entity });
    // Put it back where it was: wait for the list to show it, then move it.
    const restored = await this._waitFor((items) => items.find((i) => sameItem(i.summary, removed.name)));
    if (!restored) return;
    const move = { type: "todo/item/move", entity_id: this._config.entity, uid: restored.uid };
    if (removed.previous && this._items.some((i) => i.uid === removed.previous)) {
      move.previous_uid = removed.previous;
    }
    if (move.previous_uid || this._items[0]?.uid !== restored.uid) {
      try { await this._hass.callWS(move); } catch (err) { /* staying at the end is fine */ }
    }
  }

  _waitFor(find, timeout = 2000) {
    return new Promise((resolve) => {
      const started = Date.now();
      const check = () => {
        const found = find(this._items);
        if (found || Date.now() - started > timeout) resolve(found);
        else setTimeout(check, 50);
      };
      check();
    });
  }

  _renderList() {
    if (!this.shadowRoot) return;
    const list = this.shadowRoot.getElementById("list");
    this.shadowRoot.getElementById("empty").style.display = this._items.length ? "none" : "";
    list.replaceChildren(
      ...this._items.map((item) => {
        const row = document.createElement("li");
        const label = document.createElement("span");
        label.className = "item";
        label.textContent = item.summary;
        if (item.description) {
          const amount = document.createElement("span");
          amount.className = "amount";
          amount.textContent = item.description;
          label.append(amount);
        }
        const remove = document.createElement("button");
        remove.className = "remove";
        remove.type = "button";
        remove.textContent = "✕";
        remove.setAttribute("aria-label", this._t.remove(item.summary));
        remove.addEventListener("click", () => this._remove(item));
        row.append(label, remove);
        return row;
      }),
    );
  }

  _renderChips() {
    if (!this.shadowRoot) return;
    const typed = this._name.value.trim().toLowerCase();
    const starts = [];
    const contains = [];
    for (const name of this._known) {
      const lower = name.toLowerCase();
      if (!typed || lower.startsWith(typed)) starts.push(name);
      else if (lower.includes(typed)) contains.push(name);
    }
    const shown = [...starts, ...contains].slice(0, MAX_SUGGESTIONS);
    this.shadowRoot.getElementById("chips").replaceChildren(
      ...shown.map((name) => {
        const chip = document.createElement("button");
        chip.type = "button";
        chip.className = "chip";
        if (this._items.some((item) => sameItem(item.summary, name))) chip.classList.add("on-list");
        chip.textContent = name;
        // One tap adds it, with whatever amount is typed.
        chip.addEventListener("click", () => this._add(name, this._amount.value));
        return chip;
      }),
    );
  }

  _maybeFocus() {
    const hash = this._config?.autofocus_hash;
    if (hash === true || (hash && window.location.hash === hash)) {
      // Names that became known in a transfer since the last opening.
      if (this._hass) this._loadKnown();
      // Let the pop-up finish opening before the keyboard comes up.
      setTimeout(() => this._name?.focus(), 350);
    }
  }
}

customElements.define("bilka-shopping-list-card", BilkaShoppingListCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "bilka-shopping-list-card",
  name: "Bilka shopping list",
  description: "Add to the household's shopping list from a wall display.",
});
