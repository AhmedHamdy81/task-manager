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

export function validateImageSize(img, spec, label) {
  const expectedW = spec.width;
  const expectedH = spec.height;
  if (!img) {
    console.warn(formatAssetValidation(label, spec, null, null));
    console.warn(`Waiting for production asset:\n${label}`);
    return false;
  }
  if (img.width !== expectedW || img.height !== expectedH) {
    console.warn(formatAssetValidation(label, spec, img.width, img.height));
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
    console.warn(formatAssetValidation(label, spec, null, null));
    console.warn(`Waiting for production asset:\n${label}`);
    return false;
  }
  const frameGuess = frameWidth ? img.width / frameWidth : 0;
  const sizeOk = img.width === expectedW && img.height === expectedH;
  const framesOk = frameGuess === frames;
  if (!sizeOk || !framesOk) {
    console.warn(formatAssetValidation(label, spec, img.width, img.height));
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
  }

  url(rel) {
    if (!rel) return "";
    let src = rel;
    if (!(/^https?:\/\//.test(rel) || rel.startsWith("/"))) {
      src = `${this.baseUrl}/${rel.replace(/^\//, "")}`;
    } else {
      src = rel;
    }
    if (this.cacheKey) {
      src += (src.includes("?") ? "&" : "?") + "v=" + encodeURIComponent(this.cacheKey);
    }
    return src;
  }

  async loadImage(key, rel) {
    if (this.images.has(key)) return this.images.get(key);
    const src = this.url(rel);
    if (!src) {
      this.images.set(key, null);
      return null;
    }
    const img = await new Promise((resolve) => {
      const el = new Image();
      el.onload = () => resolve(el);
      el.onerror = () => resolve(null);
      el.src = src;
    });
    if (!img) {
      console.warn(`[Producer Hunt Asset Validation]\n\nAsset:\n${rel || key}\n\nWaiting for production asset:\n${rel || key}\n\nUsing placeholder fallback.`);
    }
    this.images.set(key, img);
    return img;
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
