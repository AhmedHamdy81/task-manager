import { DEFAULT_KEYMAP } from "./config.js";

/** Remappable keyboard input. Simultaneous actions are supported. */
export class Input {
  constructor(keymap = DEFAULT_KEYMAP) {
    this.keymap = { ...keymap };
    this.held = new Set();
    this.pressed = new Set();
    this._onDown = (e) => this._keydown(e);
    this._onUp = (e) => this._keyup(e);
  }

  attach() {
    window.addEventListener("keydown", this._onDown);
    window.addEventListener("keyup", this._onUp);
  }

  detach() {
    window.removeEventListener("keydown", this._onDown);
    window.removeEventListener("keyup", this._onUp);
  }

  remap(action, codes) {
    this.keymap[action] = Array.isArray(codes) ? codes : [codes];
  }

  _actionForCode(code) {
    for (const [action, codes] of Object.entries(this.keymap)) {
      if (codes.includes(code)) return action;
    }
    return null;
  }

  _keydown(e) {
    const action = this._actionForCode(e.code);
    if (!action) return;
    e.preventDefault();
    if (!this.held.has(action)) this.pressed.add(action);
    this.held.add(action);
  }

  _keyup(e) {
    const action = this._actionForCode(e.code);
    if (!action) return;
    e.preventDefault();
    this.held.delete(action);
  }

  isDown(action) {
    return this.held.has(action);
  }

  consume(action) {
    if (!this.pressed.has(action)) return false;
    this.pressed.delete(action);
    return true;
  }

  endFrame() {
    this.pressed.clear();
  }
}
