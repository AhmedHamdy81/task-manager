import { DEFAULT_KEYMAP } from "./config.js";

/** Remappable keyboard + optional gamepad input. Simultaneous actions are supported. */
export class Input {
  constructor(keymap = DEFAULT_KEYMAP) {
    this.keymap = { ...keymap };
    this.held = new Set();
    this.pressed = new Set();
    this._keys = new Set();
    this._gp = new Set();
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

  _syncHeld() {
    this.held = new Set([...this._keys, ...this._gp]);
  }

  _keydown(e) {
    const action = this._actionForCode(e.code);
    if (!action) return;
    e.preventDefault();
    if (!this._keys.has(action)) this.pressed.add(action);
    this._keys.add(action);
    this._syncHeld();
  }

  _keyup(e) {
    const action = this._actionForCode(e.code);
    if (!action) return;
    e.preventDefault();
    this._keys.delete(action);
    this._syncHeld();
  }

  pollGamepad() {
    if (typeof navigator === "undefined" || typeof navigator.getGamepads !== "function") return;
    const gp = Array.from(navigator.getGamepads() || []).find(Boolean);
    const now = new Set();
    if (gp) {
      const ax = gp.axes?.[0] || 0;
      const ay = gp.axes?.[1] || 0;
      if (ax < -0.55 || gp.buttons?.[14]?.pressed) now.add("moveLeft");
      if (ax > 0.55 || gp.buttons?.[15]?.pressed) now.add("moveRight");
      if (ay < -0.55 || gp.buttons?.[12]?.pressed) now.add("jump");
      if (ay > 0.55 || gp.buttons?.[13]?.pressed) now.add("crouch");
      if (gp.buttons?.[3]?.pressed) now.add("interact");
      if (gp.buttons?.[0]?.pressed) now.add("confirm");
      if (gp.buttons?.[1]?.pressed || gp.buttons?.[9]?.pressed) now.add("pause");
      if (gp.buttons?.[2]?.pressed) now.add("shoot");
      if (gp.buttons?.[5]?.pressed || gp.buttons?.[7]?.pressed) now.add("special");
      if (gp.buttons?.[4]?.pressed) now.add("weaponCycle");
    }
    for (const action of now) {
      if (!this._gp.has(action)) this.pressed.add(action);
    }
    this._gp = now;
    this._syncHeld();
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

  clearTransient() {
    this.held.clear();
    this.pressed.clear();
    this._keys.clear();
    this._gp.clear();
  }
}
