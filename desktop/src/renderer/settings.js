/* The settings window's view. Every control writes straight through to the main process, which saves it
 * and tells the panel and the menu bar at once — there is no Save button for anything but the key.
 */

const $ = (id) => document.getElementById(id);

const CHOICES = ['travelMode', 'tefillah', 'mikvahFor', 'menuBarText', 'glass'];
const SLIDERS = [
    { id: 'windowMinutes', label: (v) => (v < 60 ? `${v} min` : `${Math.floor(v / 60)}h${v % 60 ? ` ${v % 60}m` : ''}`) },
    { id: 'listLength', label: (v) => `${v} row${v === 1 ? '' : 's'}` },
    { id: 'refreshSeconds', label: (v) => (v < 60 ? `${v} sec` : `${Math.round(v / 60)} min`) },
];

let state = null;
let searchTimer = null;

function apply(changes) {
    window.shulgo.set(changes);
}

// ---- place ----------------------------------------------------------------------------------

async function search() {
    const text = $('place').value.trim();
    const box = $('matches');
    box.replaceChildren();
    if (text.length < 2) {
        box.hidden = true;

        return;
    }

    const matches = await window.shulgo.searchPlaces(text);
    if (!matches.length) {
        box.hidden = true;

        return;
    }

    for (const match of matches.slice(0, 6)) {
        const button = document.createElement('button');
        const label = document.createElement('span');
        label.textContent = match.label;
        button.append(label);
        if (match.shuls) {
            const count = document.createElement('span');
            count.className = 'count';
            count.textContent = `${match.shuls} shul${match.shuls === 1 ? '' : 's'}`;
            button.append(count);
        }
        button.addEventListener('click', () => {
            window.shulgo.setPlace(match);
            $('place').value = '';
            box.hidden = true;
        });
        box.append(button);
    }
    box.hidden = false;
}

// ---- the key ---------------------------------------------------------------------------------

async function saveKey(options) {
    const status = $('keyStatus');
    status.className = 'status';
    status.textContent = options?.remove ? 'Removing…' : 'Asking ShulGo…';
    const answer = await window.shulgo.setKey($('apiKey').value, options);
    status.className = `status ${answer.ok ? 'good' : 'bad'}`;
    status.textContent = answer.message;
    if (answer.ok)
        $('apiKey').value = '';
}

// ---- drawing ----------------------------------------------------------------------------------

function render() {
    if (!state)
        return;
    const s = state.settings;

    document.body.className = `glass-${s.glass === 'blur' ? 'frosted' : s.glass}`;

    for (const id of CHOICES) {
        if ($(id).value !== String(s[id]))
            $(id).value = String(s[id]);
    }

    for (const slider of SLIDERS) {
        const input = $(slider.id);
        if (document.activeElement !== input)
            input.value = String(s[slider.id]);
        $(`${slider.id}Out`).textContent = slider.label(Number(input.value));
    }

    $('openAtLogin').checked = Boolean(s.openAtLogin);

    if (document.activeElement !== $('apiBaseUrl'))
        $('apiBaseUrl').value = s.apiBaseUrl;

    // The place name comes from ShulGo, so it goes in as text with the bold part built around it.
    const current = $('current');
    current.replaceChildren();
    if (state.place?.label) {
        const name = document.createElement('b');
        name.textContent = state.place.label;
        current.append('Looking near ', name, '.');
    } else {
        current.textContent = 'No place set yet.';
    }

    $('keyPath').textContent = `Kept in ${s.keyFilePath}`;
    $('removeKey').hidden = !s.hasKey;
    if (!$('keyStatus').textContent)
        $('keyStatus').textContent = s.hasKey ? 'A key is saved.' : 'No key yet.';
}

// ---- wiring -------------------------------------------------------------------------------------

for (const id of CHOICES)
    $(id).addEventListener('change', () => apply({ [id]: $(id).value }));

for (const slider of SLIDERS) {
    const input = $(slider.id);
    input.addEventListener('input', () => {
        $(`${slider.id}Out`).textContent = slider.label(Number(input.value));
    });
    input.addEventListener('change', () => apply({ [slider.id]: Number(input.value) }));
}

$('openAtLogin').addEventListener('change', () => apply({ openAtLogin: $('openAtLogin').checked }));

// 'input' covers typing; 'change' and 'search' cover pasting, autofill and the clear button, which
// don't always raise an input event.
for (const event of ['input', 'change', 'search']) {
    $('place').addEventListener(event, () => {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(() => search(), 300);
    });
}

$('saveKey').addEventListener('click', () => saveKey());
$('removeKey').addEventListener('click', () => saveKey({ remove: true }));
$('apiKey').addEventListener('keydown', (event) => {
    if (event.key === 'Enter')
        saveKey();
});

$('apiBaseUrl').addEventListener('change', () => apply({ apiBaseUrl: $('apiBaseUrl').value.trim() }));
$('resetBase').addEventListener('click', () => {
    $('apiBaseUrl').value = 'https://shulgo.com/api/v1';
    apply({ apiBaseUrl: 'https://shulgo.com/api/v1' });
});

/* Linking this computer (RFC 8628). The handshake itself lives in the main process — this only
 * shows the code and asks how it is going, and never learns the device code or the key. */
let linkTimer = null;

function stopLinking(message) {
    if (linkTimer) {
        clearTimeout(linkTimer);
        linkTimer = null;
    }
    window.shulgo.linkStop();
    if (message !== undefined)
        $('linkStatus').textContent = message;
}

async function askLink() {
    linkTimer = null;
    const answer = await window.shulgo.linkPoll();
    $('linkStatus').textContent = answer.words ?? '';

    if (answer.state === 'pending') {
        linkTimer = setTimeout(askLink, Math.max(1, answer.interval ?? 5) * 1000);

        return;
    }

    $('linkCode').textContent = '';
    if (answer.state === 'done') {
        $('linkWhere').textContent = '';
        $('keyStatus').className = 'status good';
        $('keyStatus').textContent = 'Linked. This computer has its own key now.';
        setTimeout(() => { $('linkBox').hidden = true; }, 2500);
    }
}

$('linkComputer').addEventListener('click', async () => {
    stopLinking();
    $('linkBox').hidden = false;
    $('linkCode').textContent = '';
    $('linkWhere').textContent = '';
    $('linkStatus').textContent = 'Asking ShulGo for a code…';

    const started = await window.shulgo.linkStart();
    if (!started.ok) {
        $('linkStatus').textContent = started.message || 'ShulGo couldn’t be reached.';

        return;
    }

    $('linkWhere').textContent = `On your phone, open ${started.verificationUri} and type this code:`;
    $('linkCode').textContent = started.userCode;
    $('linkStatus').textContent = started.words ?? '';
    linkTimer = setTimeout(askLink, Math.max(1, started.interval ?? 5) * 1000);
});

$('linkCancel').addEventListener('click', () => {
    stopLinking('Stopped.');
    $('linkCode').textContent = '';
    $('linkBox').hidden = true;
});

// A window that goes away mid-linking should not leave one half-done on the other side.
window.addEventListener('beforeunload', () => stopLinking());

$('quit').addEventListener('click', () => window.shulgo.quit());

window.shulgo.onState((next) => {
    state = next;
    render();
});

window.shulgo.getState().then((first) => {
    state = first;
    render();
});
