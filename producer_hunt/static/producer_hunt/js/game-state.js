export const GameState = {
  BOOT: "BOOT",
  START_SCREEN: "START_SCREEN",
  CHARACTER_SELECT: "CHARACTER_SELECT",
  PLAYING: "PLAYING",
  PAUSED: "PAUSED",
  PLAYER_DEAD: "PLAYER_DEAD",
  GAME_OVER: "GAME_OVER",
  LEVEL_COMPLETE: "LEVEL_COMPLETE",
};

export class GameStateManager {
  constructor(initial = GameState.BOOT) {
    this.current = initial;
    this.previous = null;
    this._listeners = [];
  }

  get() {
    return this.current;
  }

  is(...states) {
    return states.includes(this.current);
  }

  set(next) {
    if (!next || next === this.current) return;
    this.previous = this.current;
    this.current = next;
    for (const fn of this._listeners) fn(this.current, this.previous);
  }

  onChange(fn) {
    this._listeners.push(fn);
  }
}
