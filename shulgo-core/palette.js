/* ShulGo's colours, in one place.
 *
 * These are the website's and the phone app's values (mobile/src/constants/theme.ts and
 * public/assets/css/site.css), written as plain data so the GNOME widget, the GTK window and any later
 * Mac, Windows, iOS or Android build all paint the same product.
 */

export const Brand = {
    navy: '#12305a',
    navy2: '#1d4b85',
    gold: '#f2b705',
    goldLight: '#ffd54f',
    red: '#b3261e',
    green: '#1c7c3a',
};

export const Palette = {
    light: {
        bg: '#f5f6f8',
        card: '#ffffff',
        raised: '#eef1f5',
        selected: '#dfe6f1',
        line: '#dfe3e8',
        text: '#1b2430',
        muted: '#5d6877',
        accent: Brand.navy,
        accentFg: '#ffffff',
        link: '#1d5fb8',
        good: '#1c7c3a',
        warn: '#9a5b00',
        bad: '#b3261e',
        mikvah: '#0e7c86',
    },
    dark: {
        bg: '#0b1220',
        card: '#141d2e',
        raised: '#1c2740',
        selected: '#243353',
        line: '#26324a',
        text: '#f2f4f7',
        muted: '#a9b3c2',
        accent: '#8fb3ea',
        accentFg: '#ffffff',
        link: '#8fb3ea',
        good: '#5fd39a',
        warn: '#f3b65b',
        bad: '#ff8a80',
        mikvah: '#5cc9d2',
    },
};

/**
 * libadwaita's named colours, set to ShulGo's. GTK has no prefers-color-scheme, so the right set is
 * written out whenever the system switches between light and dark.
 *
 * @param {boolean} dark
 * @returns {string} GTK CSS
 */
export function adwaitaColors(dark) {
    const c = dark ? Palette.dark : Palette.light;
    const headerbar = dark ? '#121c2e' : '#ffffff';
    const view = dark ? '#0e1727' : '#ffffff';

    return [
        `@define-color accent_color ${c.accent};`,
        `@define-color accent_bg_color ${dark ? Brand.navy2 : Brand.navy};`,
        `@define-color accent_fg_color ${c.accentFg};`,
        `@define-color window_bg_color ${c.bg};`,
        `@define-color window_fg_color ${c.text};`,
        `@define-color view_bg_color ${view};`,
        `@define-color view_fg_color ${c.text};`,
        `@define-color headerbar_bg_color ${headerbar};`,
        `@define-color headerbar_fg_color ${c.text};`,
        `@define-color card_bg_color ${c.card};`,
        `@define-color card_fg_color ${c.text};`,
        `@define-color popover_bg_color ${c.card};`,
        `@define-color popover_fg_color ${c.text};`,
        `@define-color sidebar_bg_color ${c.raised};`,
        `@define-color sidebar_fg_color ${c.text};`,
        `@define-color sidebar_backdrop_color ${c.raised};`,
        `@define-color success_color ${c.good};`,
        `@define-color warning_color ${c.warn};`,
        `@define-color error_color ${c.bad};`,
        `@define-color shulgo_gold ${Brand.gold};`,
        `@define-color shulgo_mikvah ${c.mikvah};`,
        '',
    ].join('\n');
}
