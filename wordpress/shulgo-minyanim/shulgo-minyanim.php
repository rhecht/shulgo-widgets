<?php
/**
 * Plugin Name:       ShulGo Minyan Times
 * Plugin URI:        https://shulgo.com/syndication
 * Description:       Show your shul's minyan times from ShulGo, or the next minyanim near a place, with a shortcode. Free; the times stay up to date on their own.
 * Version:           1.0.0
 * Requires at least: 5.0
 * Requires PHP:      7.2
 * Author:            ShulGo
 * Author URI:        https://shulgo.com/
 * License:           GPL-2.0-or-later
 * Text Domain:       shulgo-minyanim
 *
 * Shortcodes:
 *   [shulgo_times shul="your-shul"]           this week's minyan times (shul: the end of its ShulGo address, or the whole address)
 *       days="7" theme="light|dark|auto" accent="12305a" zmanim="1" title="1" height="560"
 *   [shulgo_nearby place="Teaneck, NJ"]       the next minyanim near a place (or lat="…" lng="…")
 *       tefillah="next|shacharis|mincha|maariv" limit="8" radius="" hours="6" theme accent title height
 *   [shulgo_calendar shul="your-shul"]        a link to add the shul's minyanim to a calendar app
 */

if (! defined('ABSPATH')) {
    exit;
}

const SHULGO_MINYANIM_BASE = 'https://shulgo.com/';

/** "your-shul", or a ShulGo address ("https://shulgo.com/shul/your-shul?tab=…") → "your-shul". */
function shulgo_minyanim_slug($shul)
{
    $shul = trim((string) $shul);
    if (preg_match('#/shul/([^/?#]+)#', $shul, $m)) {
        $shul = $m[1];
    }

    return preg_replace('/[^a-z0-9\-]/', '', strtolower($shul));
}

/** The options both widgets take, as a query, leaving out what's left at its default. */
function shulgo_minyanim_common($a)
{
    $q = array();
    if (in_array($a['theme'], array('dark', 'auto'), true)) {
        $q['theme'] = $a['theme'];
    }
    $accent = strtolower(ltrim((string) $a['accent'], '#'));
    if ($accent !== '' && preg_match('/^(?:[0-9a-f]{3}|[0-9a-f]{6})$/', $accent)) {
        $q['accent'] = $accent;
    }
    if ((string) $a['title'] === '0') {
        $q['title'] = '0';
    }

    return $q;
}

/** The frame, sized to fit by ShulGo's small script (loaded once). */
function shulgo_minyanim_frame($src, $label, $height)
{
    wp_enqueue_script('shulgo-widget', SHULGO_MINYANIM_BASE . 'assets/js/shulgo-widget.js', array(), '1.0.0', true);

    return '<iframe src="' . esc_url($src) . '" title="' . esc_attr($label) . '" data-shulgo-widget loading="lazy" style="width:100%;max-width:720px;height:'
        . max(120, (int) $height) . 'px;border:0;overflow:hidden"></iframe>';
}

function shulgo_minyanim_times($atts)
{
    $a    = shortcode_atts(array('shul' => '', 'days' => '7', 'theme' => 'light', 'accent' => '', 'zmanim' => '1', 'title' => '1', 'height' => '560'), $atts, 'shulgo_times');
    $slug = shulgo_minyanim_slug($a['shul']);
    if ($slug === '') {
        return current_user_can('edit_posts') ? '<p><em>ShulGo: add your shul, e.g. [shulgo_times shul="your-shul"].</em></p>' : '';
    }
    $q = shulgo_minyanim_common($a);
    if ((int) $a['days'] !== 7 && (int) $a['days'] > 0) {
        $q['days'] = min(14, (int) $a['days']);
    }
    if ((string) $a['zmanim'] === '0') {
        $q['zmanim'] = '0';
    }
    $src = SHULGO_MINYANIM_BASE . 'embed/shul/' . rawurlencode($slug) . ($q ? '?' . http_build_query($q) : '');

    return shulgo_minyanim_frame($src, __('Minyan times', 'shulgo-minyanim'), $a['height']);
}

function shulgo_minyanim_nearby($atts)
{
    $a = shortcode_atts(array('place' => '', 'lat' => '', 'lng' => '', 'tefillah' => 'next', 'limit' => '8', 'radius' => '', 'hours' => '6',
        'theme' => 'light', 'accent' => '', 'title' => '1', 'height' => '420'), $atts, 'shulgo_nearby');
    $q = array();
    if (is_numeric($a['lat']) && is_numeric($a['lng'])) {
        $q['lat'] = $a['lat'];
        $q['lng'] = $a['lng'];
    }
    if (trim($a['place']) !== '') {
        $q['q'] = trim($a['place']);
    }
    if (! $q) {
        return current_user_can('edit_posts') ? '<p><em>ShulGo: say where, e.g. [shulgo_nearby place="Teaneck, NJ"].</em></p>' : '';
    }
    if (in_array($a['tefillah'], array('shacharis', 'mincha', 'maariv'), true)) {
        $q['t'] = $a['tefillah'];
    }
    foreach (array('limit' => 'limit', 'radius' => 'r', 'hours' => 'hours') as $k => $p) {
        if (is_numeric($a[$k])) {
            $q[$p] = $a[$k];
        }
    }
    $src = SHULGO_MINYANIM_BASE . 'embed/near?' . http_build_query($q + shulgo_minyanim_common($a));

    return shulgo_minyanim_frame($src, __('Minyanim nearby', 'shulgo-minyanim'), $a['height']);
}

function shulgo_minyanim_calendar($atts)
{
    $a    = shortcode_atts(array('shul' => '', 'label' => __('Add our minyanim to your calendar', 'shulgo-minyanim')), $atts, 'shulgo_calendar');
    $slug = shulgo_minyanim_slug($a['shul']);
    if ($slug === '') {
        return '';
    }
    $feed = preg_replace('#^https?://#', 'webcal://', SHULGO_MINYANIM_BASE . 'shul/' . rawurlencode($slug) . '/minyanim.ics');

    return '<a class="shulgo-calendar" href="' . esc_url($feed, array('webcal', 'https', 'http')) . '">' . esc_html($a['label']) . '</a>';
}

add_shortcode('shulgo_times', 'shulgo_minyanim_times');
add_shortcode('shulgo_nearby', 'shulgo_minyanim_nearby');
add_shortcode('shulgo_calendar', 'shulgo_minyanim_calendar');
