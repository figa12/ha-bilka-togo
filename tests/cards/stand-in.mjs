// A real browser-like DOM (jsdom) running the real card, with a stand-in for Home Assistant.
import { readFileSync } from "node:fs";
import { JSDOM } from "jsdom";

const SOURCE = readFileSync(
  new URL("../../custom_components/bilka_togo/frontend/bilka-shopping-list-card.js", import.meta.url),
  "utf8",
);

/** The parts of Home Assistant the card talks to, keeping a shopping list in memory. */
export function standInHass({ items = [], known = [] } = {}) {
  const hass = {
    items: items.map((summary, index) => ({ uid: `uid-${index}`, summary, status: "needs_action" })),
    calls: [],
    live: [],
    // Set to hold back subscribe answers, as a slow connection would.
    holdSubscribe: null,
    emit() {
      for (const { callback } of hass.live) callback({ items: hass.items });
    },
    connection: {
      subscribeMessage: async (callback) => {
        const subscription = { callback };
        if (hass.holdSubscribe) await hass.holdSubscribe;
        hass.live.push(subscription);
        callback({ items: hass.items });
        return () => {
          hass.live = hass.live.filter((other) => other !== subscription);
        };
      },
    },
    callWS: async (message) => {
      hass.calls.push(message);
      return message.service === "known_items" ? { response: { items: known } } : {};
    },
    callService: async (domain, service, data) => {
      hass.calls.push({ domain, service, data });
      if (service === "add_item") {
        hass.items.push({
          uid: `uid-${hass.items.length}-${data.item}`,
          summary: data.item,
          description: data.description,
          status: "needs_action",
        });
      }
      if (service === "remove_item") hass.items = hass.items.filter((item) => item.uid !== data.item);
      hass.emit();
    },
  };
  return hass;
}

/** A page with the card's script loaded, as Home Assistant would have it. */
export async function loadPage(t) {
  const dom = new JSDOM("<!DOCTYPE html><body></body>", {
    runScripts: "outside-only",
    url: "http://homeassistant.local/",
  });
  t.after(() => dom.window.close());
  dom.window.eval(SOURCE);
  dom.window.eval('customElements.define("home-assistant", class extends HTMLElement {})');
  await dom.window.customElements.whenDefined("bilka-shopping-list-card");
  return dom.window;
}

/** Wait for what the card has started (subscribing, service calls) to settle. */
export const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

/** What someone standing at the card can see and do. */
export class Card {
  constructor(window, config, hass) {
    this.window = window;
    this.element = window.document.createElement("bilka-shopping-list-card");
    this.element.setConfig(config);
    this.element.hass = hass;
    window.document.body.append(this.element);
  }

  get root() {
    return this.element.shadowRoot;
  }

  visible(selector) {
    const element = this.root.querySelector(selector);
    return Boolean(element) && !element.closest("[hidden]");
  }

  get nameField() { return this.root.querySelector('input[placeholder="Vare"]'); }
  get amountField() { return this.root.querySelector('input[placeholder="Mængde"]'); }
  get addButton() { return this.root.querySelector('button[type="submit"]'); }
  get suggestions() { return [...this.root.querySelectorAll(".chip")]; }
  get rows() { return [...this.root.querySelectorAll("li")].map((row) => row.querySelector(".item").textContent); }

  shows(part) {
    const selector = {
      name: 'input[placeholder="Vare"]',
      amount: 'input[placeholder="Mængde"]',
      add: 'button[type="submit"]',
      suggestions: "#chips",
      list: "ul",
    }[part];
    return this.visible(selector);
  }

  type(name, amount) {
    this.nameField.value = name;
    this.nameField.dispatchEvent(new this.window.Event("input", { bubbles: true }));
    if (amount !== undefined) this.amountField.value = amount;
  }

  async submit() {
    this.root.querySelector("form").dispatchEvent(new this.window.Event("submit", { cancelable: true }));
    await settle();
  }

  async tapSuggestion(name) {
    this.suggestions.find((chip) => chip.textContent === name).click();
    await settle();
  }

  async remove(name) {
    this.root.querySelector(`button[aria-label="Fjern ${name}"]`).click();
    await settle();
  }

  async undo() {
    this.root.querySelector("#undo button").click();
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
}

/** The card's editor, as Home Assistant opens it: what is ticked, and what it saves. */
export class Editor {
  constructor(window, config) {
    this.window = window;
    const Card = window.customElements.get("bilka-shopping-list-card");
    this.element = Card.getConfigElement();
    this.saved = [];
    this.element.addEventListener("config-changed", (event) => {
      const config = { ...event.detail.config };
      if (config.sections) config.sections = [...config.sections];
      this.saved.push(config);
      // Home Assistant hands the saved config straight back.
      this.element.setConfig(event.detail.config);
    });
    this.element.setConfig(config);
    window.document.body.append(this.element);
  }

  box(section) {
    return this.element.shadowRoot.querySelector(`input[type="checkbox"][name="${section}"]`);
  }

  get ticked() {
    return ["add", "amount", "suggestions", "list"].filter((section) => this.box(section).checked);
  }

  get locked() {
    return ["add", "amount", "suggestions", "list"].filter((section) => this.box(section).disabled);
  }

  click(section) {
    this.box(section).click();
  }

  get lastSaved() {
    return this.saved.at(-1);
  }
}
