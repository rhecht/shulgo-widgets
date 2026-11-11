/* Draws ShulGo's icons without any image library: the shul's arched doorway with a clock hand, the same
 * shape as the JewBuntu one, written straight out as PNG.
 *
 *   assets/trayTemplate.png      16×16  }  macOS template images: black with an alpha channel, so the
 *   assets/trayTemplate@2x.png   32×32  }  menu bar tints them for light and dark by itself
 *   assets/tray-light.png        32×32     white, for the Windows tray and Linux
 *   assets/icon.png             512×512    the app icon, in ShulGo's navy and gold
 *
 * Shapes are filled by asking, for each pixel, whether it is inside — with a little oversampling so the
 * arch doesn't come out jagged.
 */

import { deflateSync } from 'node:zlib';
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const assets = join(here, '..', 'assets');

// ---- a very small PNG writer -------------------------------------------------------------------

function crc32(buf) {
    let c = ~0;
    for (const byte of buf) {
        c ^= byte;
        for (let k = 0; k < 8; k++)
            c = (c >>> 1) ^ (0xEDB88320 & -(c & 1));
    }

    return ~c >>> 0;
}

function chunk(type, data) {
    const head = Buffer.alloc(8);
    head.writeUInt32BE(data.length, 0);
    head.write(type, 4, 'ascii');
    const crc = Buffer.alloc(4);
    crc.writeUInt32BE(crc32(Buffer.concat([Buffer.from(type, 'ascii'), data])), 0);

    return Buffer.concat([head, data, crc]);
}

/** @param {Uint8Array} rgba width*height*4 */
function png(width, height, rgba) {
    const stride = width * 4;
    const raw = Buffer.alloc((stride + 1) * height);
    for (let y = 0; y < height; y++) {
        raw[y * (stride + 1)] = 0; // filter: none
        Buffer.from(rgba.buffer, rgba.byteOffset + y * stride, stride).copy(raw, y * (stride + 1) + 1);
    }

    const ihdr = Buffer.alloc(13);
    ihdr.writeUInt32BE(width, 0);
    ihdr.writeUInt32BE(height, 4);
    ihdr[8] = 8;    // 8 bits per channel
    ihdr[9] = 6;    // RGBA
    ihdr[10] = 0;
    ihdr[11] = 0;
    ihdr[12] = 0;

    return Buffer.concat([
        Buffer.from([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]),
        chunk('IHDR', ihdr),
        chunk('IDAT', deflateSync(raw, { level: 9 })),
        chunk('IEND', Buffer.alloc(0)),
    ]);
}

// ---- drawing ------------------------------------------------------------------------------------

/**
 * Fills a size×size image by asking `shade(x, y)` for a colour at a point in a 0..1 square.
 * Each pixel is sampled in a 3×3 grid so edges come out smooth.
 *
 * @param {number} size
 * @param {(x: number, y: number) => [number, number, number, number]|null} shade
 */
function draw(size, shade) {
    const out = new Uint8Array(size * size * 4);
    const steps = 3;
    for (let py = 0; py < size; py++) {
        for (let px = 0; px < size; px++) {
            let r = 0;
            let g = 0;
            let b = 0;
            let a = 0;
            for (let sy = 0; sy < steps; sy++) {
                for (let sx = 0; sx < steps; sx++) {
                    const x = (px + (sx + 0.5) / steps) / size;
                    const y = (py + (sy + 0.5) / steps) / size;
                    const c = shade(x, y);
                    if (!c)
                        continue;
                    r += c[0] * c[3];
                    g += c[1] * c[3];
                    b += c[2] * c[3];
                    a += c[3];
                }
            }
            const n = steps * steps;
            const i = (py * size + px) * 4;
            if (a > 0) {
                out[i] = Math.round(r / a);
                out[i + 1] = Math.round(g / a);
                out[i + 2] = Math.round(b / a);
                out[i + 3] = Math.round((a / n) * 255);
            }
        }
    }

    return out;
}

/** The glyph, in a 0..1 square: roof, two walls, an arched doorway and a clock hand. */
function inGlyph(x, y) {
    // Roof: a triangle from the apex down to the eaves.
    if (y >= 0.14 && y <= 0.34) {
        const t = (y - 0.14) / 0.2;
        const halfWidth = 0.015 + t * 0.395;
        if (Math.abs(x - 0.5) <= halfWidth)
            return true;
    }
    // Eaves.
    if (y > 0.31 && y <= 0.375 && Math.abs(x - 0.5) <= 0.405)
        return true;

    // Body, with the doorway cut out of it.
    if (y > 0.38 && y <= 0.92 && Math.abs(x - 0.5) <= 0.36) {
        const dx = (x - 0.5) / 0.19;
        const dy = (y - 0.66) / 0.28;
        const inDoor = y >= 0.66 ? Math.abs(dx) <= 1 : dx * dx + dy * dy <= 1;
        if (inDoor)
            return false;

        return true;
    }

    return false;
}

/** The clock hand, sitting in the doorway. */
function inHand(x, y) {
    const cx = 0.5;
    const cy = 0.705;
    const r = Math.hypot(x - cx, y - cy);
    if (r > 0.185)
        return false;
    // The two hands, as thick line segments from the centre.
    const near = (ax, ay, bx, by, w) => {
        const vx = bx - ax;
        const vy = by - ay;
        const t = Math.max(0, Math.min(1, ((x - ax) * vx + (y - ay) * vy) / (vx * vx + vy * vy)));

        return Math.hypot(x - (ax + t * vx), y - (ay + t * vy)) <= w;
    };

    return near(cx, cy, cx, cy - 0.125, 0.034) || near(cx, cy, cx + 0.1, cy + 0.065, 0.034);
}

function glyph(colour, withHand = true) {
    return (x, y) => {
        if (withHand && inHand(x, y))
            return colour;
        if (inGlyph(x, y))
            return colour;

        return null;
    };
}

const BLACK = [0, 0, 0, 1];
const WHITE = [255, 255, 255, 1];

mkdirSync(assets, { recursive: true });
writeFileSync(join(assets, 'trayTemplate.png'), png(16, 16, draw(16, glyph(BLACK, false))));
writeFileSync(join(assets, 'trayTemplate@2x.png'), png(32, 32, draw(32, glyph(BLACK))));
writeFileSync(join(assets, 'tray-light.png'), png(32, 32, draw(32, glyph(WHITE))));

// The app icon: the glyph in cream on ShulGo navy, with the clock in gold, rounded like a macOS icon.
const NAVY_TOP = [29, 75, 133];
const NAVY_BOTTOM = [13, 36, 70];
const CREAM = [246, 247, 251, 1];
const GOLD = [242, 183, 5, 1];

writeFileSync(join(assets, 'icon.png'), png(512, 512, draw(512, (x, y) => {
    // A rounded square, inset a little the way macOS icons are.
    const inset = 0.08;
    const radius = 0.21;
    const lo = inset;
    const hi = 1 - inset;
    if (x < lo || x > hi || y < lo || y > hi)
        return null;
    const qx = Math.max(lo + radius - x, 0, x - (hi - radius));
    const qy = Math.max(lo + radius - y, 0, y - (hi - radius));
    if (Math.hypot(qx, qy) > radius)
        return null;

    // Inside the tile: the glyph sits in the middle, a touch smaller than the tile.
    const gx = (x - 0.5) / 0.82 + 0.5;
    const gy = (y - 0.5) / 0.82 + 0.5;
    if (inHand(gx, gy))
        return GOLD;
    if (inGlyph(gx, gy))
        return CREAM;

    const t = (y - lo) / (hi - lo);

    return [
        Math.round(NAVY_TOP[0] + (NAVY_BOTTOM[0] - NAVY_TOP[0]) * t),
        Math.round(NAVY_TOP[1] + (NAVY_BOTTOM[1] - NAVY_TOP[1]) * t),
        Math.round(NAVY_TOP[2] + (NAVY_BOTTOM[2] - NAVY_TOP[2]) * t),
        1,
    ];
})));

console.log('wrote trayTemplate.png, trayTemplate@2x.png, tray-light.png, icon.png');
