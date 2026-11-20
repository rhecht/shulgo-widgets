"""Flag constructs that Python 2.5 does not have, before the interpreter has to.

Not a substitute for running the real 2.5 — it cannot see a missing builtin behind a getattr, and
the Gutsy container is the only thing that proves a file actually runs. It is here because finding
these one per container round-trip is slow, and because every one of them is a traceback at startup
on a machine whose owner cannot read a traceback.

Everything in this list was hit for real while porting, except where marked.
"""

import ast
import io
import re
import sys

# name -> what to do instead
MISSING_BUILTINS = {
    'next': 'next() is 2.6; use a for loop with break, or it.next()',
    'format': 'str.format is 2.6; use %',
    'bin': 'bin() is 2.6',
    'memoryview': 'memoryview is 2.7',
}
MISSING_ATTRS = {
    'math.isnan': 'math.isnan is 2.6; NaN is the value that != itself',
    'math.isinf': 'math.isinf is 2.6; compare against float("1e400")',
    'os.replace': 'os.replace is 3.3; os.rename is atomic on POSIX',
    'decimal.Decimal.scaleb': 'scaleb is 2.6',
    'subprocess.check_output': 'check_output is 2.7; use Popen().communicate()',
    'json.loads': 'the json module is 2.6; import simplejson as json',
    'collections.OrderedDict': 'OrderedDict is 2.7',
    'itertools.combinations': 'combinations is 2.6',
}
PATTERNS = (
    (re.compile(r"(?<![\w'\"])b['\"]"), "b'' literals are 2.6"),
    (re.compile(r'\bexcept\s+[^:]*\s+as\s+\w+\s*:'), "`except X as e` is 2.6; use `except X, e`"),
    (re.compile(r'\bnonlocal\b'), 'nonlocal is Python 3'),
    (re.compile(r'''(?<![\w'"])[fF]['"]'''), 'f-strings are Python 3.6'),
    (re.compile(r'\bunicode_literals\b'), 'unicode_literals is 2.6; prefix each literal instead'),
    (re.compile(r'\bopen\([^)]*encoding\s*='), "open(encoding=) is Python 3; use codecs.open"),
    (re.compile(r'\{[^{}]*\bfor\b[^{}]*\}'), 'dict and set comprehensions are 2.7 (check by eye)'),
)


def check(path):
    text = io.open(path, encoding='utf-8').read()
    found = []

    # Over the whole text, not line by line. The first dict comprehension this missed spanned two
    # lines, which is how most of them are written once they are long enough to matter.
    stripped = re.sub(r'(?m)#.*$', '', text)
    for pattern, why in PATTERNS:
        for match in pattern.finditer(stripped):
            number = stripped.count('\n', 0, match.start()) + 1
            found.append((number, why, match.group(0).replace('\n', ' ')[:70]))

    try:
        tree = ast.parse(text, path)
    except SyntaxError:
        return found                      # the 2.5 run will say so far better than this can

    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            if node.id in MISSING_BUILTINS:
                found.append((node.lineno, MISSING_BUILTINS[node.id], node.id))
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            dotted = '%s.%s' % (node.value.id, node.attr)
            if dotted in MISSING_ATTRS:
                found.append((node.lineno, MISSING_ATTRS[dotted], dotted))

    return found


if __name__ == '__main__':
    bad = 0
    for path in sys.argv[1:]:
        for number, why, snippet in sorted(check(path)):
            print('%s:%d  %s\n        %s' % (path, number, why, snippet))
            bad += 1
    print('  %d flagged' % bad)
    sys.exit(1 if bad else 0)
