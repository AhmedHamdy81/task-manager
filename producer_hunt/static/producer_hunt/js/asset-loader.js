/**
 * Load / validate sprite strips. Missing or invalid art never crashes gameplay.
 */
import { PORTRAIT_HEIGHT, PORTRAIT_WIDTH } from "./sprite-spec.js";

export function formatAssetValidation(label, spec, actualW, actualH) {
  const expectedW = spec.frames ? spec.frameWidth * spec.frames : spec.width;
  const expectedH = spec.frames ? spec.frameHeight : spec.height;
  const actual = actualW == null ? "failed to load" : `${actualW} × ${actualH}`;
  const lines = [
    "[Producer Hunt Asset Validation]",
    "",
    "Asset:",
    label,
    "",
    "Expected:",
    `${expectedW} × ${expectedH}`,
  ];
  if (spec.frames) lines.push(`${spec.frames} frames`);
  lines.push("", "Actual:", actual, "", "Using placeholder fallback.");
  return lines.join("\n");
}

const _assetWarnings = new Set();

function warnAsset(message) {
  if (_assetWarnings.has(message)) return;
  _assetWarnings.add(message);
  console.warn(message);
}

export function validateImageSize(img, spec, label) {
  const expectedW = spec.width;
  const expectedH = spec.height;
  if (!img) {
    warnAsset(formatAssetValidation(label, spec, null, null));
    return false;
  }
  if (img.width !== expectedW || img.height !== expectedH) {
    warnAsset(formatAssetValidation(label, spec, img.width, img.height));
    return false;
  }
  return true;
}

export function validateSpriteStrip(img, spec, label) {
  const frameWidth = spec.frameWidth;
  const frameHeight = spec.frameHeight;
  const frames = spec.frames;
  const expectedW = frameWidth * frames;
  const expectedH = frameHeight;
  if (!img) {
    warnAsset(formatAssetValidation(label, spec, null, null));
    return false;
  }
  const frameGuess = frameWidth ? img.width / frameWidth : 0;
  const sizeOk = img.width === expectedW && img.height === expectedH;
  const framesOk = frameGuess === frames;
  if (!sizeOk || !framesOk) {
    warnAsset(formatAssetValidation(label, spec, img.width, img.height));
    return false;
  }
  return true;
}

export class AssetLoader {
  constructor(baseUrl = "", options = {}) {
    this.baseUrl = String(baseUrl || "").replace(/\/$/, "");
    this.cacheKey = options.cacheKey || "";
    this.images = new Map();
    this.sheets = new Map();
    this.characterKits = new Map();
    this.enemyKits = new Map();
    this._inflight = new Map();
    this._warned = new Set();
    this.loadTimeoutMs = options.loadTimeoutMs || 12000;
  }

  _warnOnce(message) {
    if (this._warned.has(message)) return;
    this._warned.add(message);
    console.warn(message);
  }

  _safeRel(rel) {
    const raw = String(rel || "").trim();
    if (!raw) return false;
    if (raw.includes("..") || raw.includes("\\") || raw.includes("\0")) return false;
    if (/^[a-zA-Z]:/.test(raw) || raw.startsWith("file:") || raw.startsWith("//")) return false;
    if (/^https?:/i.test(raw)) return false;
    if (raw.startsWith("/")) return raw.startsWith("/producer-hunt/static/");
    return true;
  }

  url(rel) {
    if (!this._safeRel(rel)) {
      this._warnOnce("Required static asset failed to load: path was rejected.");
      return "";
    }
    let src = rel;
    if (!rel.startsWith("/")) {
      src = `${this.baseUrl}/${rel.replace(/^\//, "")}`;
    }
    if (this.cacheKey) {
      src += (src.includes("?") ? "&" : "?") + "v=" + encodeURIComponent(this.cacheKey);
    }
    return src;
  }

  async loadImage(key, rel) {
    if (this.images.has(key)) return this.images.get(key);
    if (this._inflight.has(key)) return this._inflight.get(key);
    const src = this.url(rel);
    if (!src) {
      this.images.set(key, null);
      return null;
    }
    const pending = new Promise((resolve) => {
      const el = new Image();
      let done = false;
      const finish = (value) => {
        if (done) return;
        done = true;
        resolve(value);
      };
      const timer = setTimeout(() => finish(null), this.loadTimeoutMs);
      el.onload = () => {
        clearTimeout(timer);
        finish(el);
      };
      el.onerror = () => {
        clearTimeout(timer);
        finish(null);
      };
      el.src = src;
    }).then((img) => {
      if (!img) {
        warnAsset(`Required static asset failed to load: ${rel || key}`);
      }
      this.images.set(key, img);
      this._inflight.delete(key);
      return img;
    });
    this._inflight.set(key, pending);
    return pending;
  }

  get(key) {
    return this.images.get(key) || null;
  }

  sheet(key) {
    return this.sheets.get(key) || null;
  }

  async loadSheet(key, spec) {
    const image = await this.loadImage(key, spec.src);
    let ok = false;
    if (spec.frames) {
      ok = validateSpriteStrip(image, spec, spec.src);
    } else {
      ok = validateImageSize(image, spec, spec.src);
    }
    const entry = { ...spec, image: ok ? image : null };
    this.sheets.set(key, entry);
    return entry;
  }

  async loadCatalog(catalog) {
    const entries = Object.entries(catalog || {});
    await Promise.all(entries.map(([key, spec]) => this.loadSheet(key, spec)));
  }

  async _hydrateAnims(config) {
    const kit = {
      ...config,
      animations: {},
    };
    for (const [name, clip] of Object.entries(config.animations || {})) {
      const image = await this.loadImage(clip.src, clip.src);
      const ok = validateSpriteStrip(
        image,
        {
          frameWidth: config.frameWidth,
          frameHeight: config.frameHeight,
          frames: clip.frames,
        },
        clip.src
      );
      kit.animations[name] = {
        ...clip,
        image: ok ? image : null,
        frameWidth: config.frameWidth,
        frameHeight: config.frameHeight,
        renderWidth: config.renderWidth || config.frameWidth,
        renderHeight: config.renderHeight || config.frameHeight,
      };
    }
    return kit;
  }

  async loadCharacterKit(config) {
    if (this.characterKits.has(config.id)) return this.characterKits.get(config.id);
    const kit = await this._hydrateAnims(config);
    kit.portraitImage = null;
    if (config.portrait) {
      const portrait = await this.loadImage(`portrait:${config.id}`, config.portrait);
      const ok = validateImageSize(
        portrait,
        { width: PORTRAIT_WIDTH, height: PORTRAIT_HEIGHT },
        config.portrait
      );
      kit.portraitImage = ok ? portrait : null;
    }
    this.characterKits.set(config.id, kit);
    return kit;
  }

  async loadEnemyKit(config) {
    if (this.enemyKits.has(config.id)) return this.enemyKits.get(config.id);
    const kit = await this._hydrateAnims(config);
    this.enemyKits.set(config.id, kit);
    return kit;
  }

  characterKit(id) {
    return this.characterKits.get(id) || null;
  }

  enemyKit(id) {
    return this.enemyKits.get(id) || null;
  }
}
