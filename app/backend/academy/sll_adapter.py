"""A node adapter for a small subset of Symbolic Lab Language (SLL) pipetting.

Emerald Cloud Lab drives its instruments with SLL, and GEMSTONE's TROVE translates its
AMBER representation into SLL first. This adapter reads only the shape of SLL unit
operations, `Transfer[Source -> "stock", Destination -> "A1", Amount -> 100 Microliter]`,
optionally wrapped in `ExperimentRoboticSamplePreparation[{...}]`, and turns each transfer
into the teaching model's pipetting steps with a fresh tip. The result is checked under
the same rules as any Opentrons plan.

It is written after SLL's published syntax, not checked against ECL's own parser, and it
parses text without evaluating anything. Locations are the teaching model's stock and
A1–A3; any other operation, option or location is reported, never guessed.
"""

import math
import re

MAX_LENGTH = 20_000
WELLS = {"stock", "A1", "A2", "A3"}
WRAPPERS = {"ExperimentRoboticSamplePreparation", "ExperimentSamplePreparation"}
UNITS = {"Microliter": 1.0, "Microliters": 1.0, "Milliliter": 1000.0, "Milliliters": 1000.0}
TOKEN = re.compile(
    r"\s*(?:(?P<string>\"(?:[^\"\\]|\\.)*\")|(?P<number>-?\d+(?:\.\d+)?(?:\*\^-?\d+)?)"
    r"|(?P<symbol>[A-Za-z$][A-Za-z0-9$]*)|(?P<rule>->)|(?P<punct>[\[\]{},;]))"
)


class SllError(ValueError):
    def __init__(self, message, position=None):
        super().__init__(message)
        self.position = position


def tokens(text):
    position, found = 0, []
    # Blank out SLL comments, keeping their length and line breaks so positions hold.
    text = re.sub(
        r"\(\*.*?\*\)",
        lambda m: re.sub(r"[^\n]", " ", m.group()),
        text,
        flags=re.S,
    )
    while position < len(text):
        if text[position:].strip() == "":
            break
        match = TOKEN.match(text, position)
        if not match:
            raise SllError(f"Cannot read SLL near {text[position : position + 20]!r}", position)
        kind = match.lastgroup
        found.append((kind, match.group(kind), match.start(kind)))
        position = match.end()
    return found


def parse(text):
    """SLL expressions as nested tuples: ("call", head, args), ("list", items), ("rule", k, v)."""
    if len(text) > MAX_LENGTH:
        raise SllError(f"Keep the program under {MAX_LENGTH:,} characters")
    items, at = tokens(text), 0

    def peek(value=None):
        return at < len(items) and (value is None or items[at][1] == value)

    def take(value):
        nonlocal at
        if at >= len(items):
            raise SllError("The program ends early")
        if not peek(value):
            where = items[at][2] if at < len(items) else None
            raise SllError(f"Expected {value!r}", where)
        at += 1

    def sequence(close):
        found = []
        while not peek(close):
            found.append(expression())
            if not peek(close):
                take(",")
        take(close)
        return found

    def expression():
        nonlocal at
        if at >= len(items):
            raise SllError("The program ends early")
        kind, value, where = items[at]
        at += 1
        if value == "{":
            node = ("list", sequence("}"))
        elif kind == "symbol" and peek("["):
            at += 1
            node = ("call", value, sequence("]"))
        elif kind == "number":
            number = float(value.replace("*^", "e"))
            if not math.isfinite(number):
                raise SllError(f"{value} is too large a number", where)
            if at < len(items) and items[at][0] == "symbol" and items[at][1] in UNITS:
                number *= UNITS[items[at][1]]
                at += 1
                node = ("volume", number)
            elif at < len(items) and items[at][0] == "symbol":
                raise SllError(f"Use Microliter or Milliliter, not {items[at][1]}", items[at][2])
            else:
                node = ("number", number)
        elif kind == "string":
            node = ("string", value[1:-1])
        elif kind == "symbol":
            node = ("symbol", value)
        else:
            raise SllError(f"Unexpected {value!r}", where)
        if peek("->"):
            at += 1
            node = ("rule", node, expression())
        return node

    # Top-level expressions, each optionally ended by a semicolon.
    found = []
    while at < len(items):
        found.append(expression())
        if peek(";"):
            take(";")
        elif at < len(items):
            raise SllError(f"Unexpected {items[at][1]!r}", items[at][2])
    if not found:
        raise SllError("The program is empty")
    return found


def operations(program):
    """The unit operations of a program, unwrapping one sample-preparation experiment."""
    found = []
    for node in parse(program):
        if node[0] == "call" and node[1] in WRAPPERS:
            if len(node[2]) != 1 or node[2][0][0] != "list":
                raise SllError(f"{node[1]} takes a list of unit operations")
            found.extend(node[2][0][1])
        elif node[0] == "list":
            found.extend(node[1])
        else:
            found.append(node)
    return found


def location(node, option):
    if node[0] != "string" or node[1] not in WELLS:
        shown = node[1] if node[0] in {"string", "symbol"} else None
        if node[0] == "call":
            raise SllError(
                f"{option} {node[1]}[...] is not a teaching-model location; use stock, A1, A2 or A3"
            )
        raise SllError(f"{option} {shown!r} is not stock, A1, A2 or A3 in the teaching model")
    return node[1]


def translate(program):
    """Teaching-model pipetting actions, with each unit operation and what it became."""
    actions, units, unsupported = [], [], []
    for index, node in enumerate(operations(program), 1):
        if node[0] != "call":
            unsupported.append({"unit": index, "message": "Not a unit operation"})
            continue
        head, args = node[1], node[2]
        if head != "Transfer":
            unsupported.append({"unit": index, "message": f"{head} is not in this adapter yet"})
            continue
        options = {}
        for arg in args:
            if arg[0] != "rule" or arg[1][0] != "symbol":
                raise SllError(f"Transfer {index}: give options as Name -> value")
            if arg[1][1] in options:
                raise SllError(f"Transfer {index} gives {arg[1][1]} twice")
            options[arg[1][1]] = arg[2]
        extra = sorted(set(options) - {"Source", "Destination", "Amount"})
        if extra:
            unsupported.append(
                {"unit": index, "message": f"Options not modelled and ignored: {', '.join(extra)}"}
            )
        missing = [o for o in ("Source", "Destination", "Amount") if o not in options]
        if missing:
            raise SllError(f"Transfer {index} needs {', '.join(missing)}")
        source = location(options["Source"], "Source")
        target = location(options["Destination"], "Destination")
        amount = options["Amount"]
        if amount[0] != "volume" or not amount[1] > 0:
            raise SllError(f"Transfer {index}: give Amount as a volume, e.g. 100 Microliter")
        units.append(
            {"unit": index, "source": source, "destination": target, "volume_ul": amount[1]}
        )
        actions += [
            {"kind": "pickup", "well": "stock", "volume": 100},
            {"kind": "aspirate", "well": source, "volume": amount[1]},
            {"kind": "dispense", "well": target, "volume": amount[1]},
            {"kind": "drop", "well": "stock", "volume": 100},
        ]
    return units, actions, unsupported
