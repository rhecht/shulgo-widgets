"""Put a u prefix on every string literal in a file, and a coding line at the top.

Python 2.5 has no `from __future__ import unicode_literals` — that arrived in 2.6 — so the only way
to have unicode strings throughout is to write the prefix on each one. And without a PEP 263 coding
line, a non-ASCII byte anywhere in the source is a SyntaxError rather than a character.

Doing this by eye over four thousand lines is how an em dash gets missed, so the tokenizer finds the
literals. But the edit is a splice at the token's own position, NOT tokenize.untokenize(), which
rewrites the whole file's spacing and turns `n = _num(value)` into `n =_num (value )`. These files
are meant to be read on a machine where reading them is the only debugger anyone has.

Run under Python 3 here; the result is for Python 2.5.
"""

import io
import sys
import tokenize


def unicodeify(path):
    with open(path, 'rb') as fh:
        tokens = [t for t in tokenize.tokenize(fh.readline) if t.type == tokenize.STRING]

    lines = io.open(path, encoding='utf-8').read().split('\n')

    # Last first, so an earlier splice never shifts a later token's column.
    done = 0
    for tok in reversed(tokens):
        row, col = tok.start
        text = tok.string
        prefix = text[:len(text) - len(text.lstrip('uUbBrRfF'))]
        if 'u' in prefix.lower() or 'b' in prefix.lower():
            continue
        line = lines[row - 1]
        lines[row - 1] = line[:col] + 'u' + line[col:]
        done += 1

    body = '\n'.join(lines)
    if 'coding:' not in '\n'.join(body.split('\n', 2)[:2]):
        body = '# -*- coding: utf-8 -*-\n' + body

    io.open(path, 'w', encoding='utf-8').write(body)

    return done, len(tokens)


if __name__ == '__main__':
    for path in sys.argv[1:]:
        added, total = unicodeify(path)
        print('  %s: %d of %d literals prefixed' % (path, added, total))
