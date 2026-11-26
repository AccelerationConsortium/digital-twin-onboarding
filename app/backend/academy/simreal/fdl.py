"""Read SiLA 2 Feature Definitions and check command arguments against them.

A connector states its own commands, parameter types and limits in these documents, so
they are the vocabulary a Sim–Real workflow is written in. Arguments are the plain JSON a
SiLA client sends: an object by parameter identifier, structures as objects by element
identifier, lists as arrays.
"""

import hashlib
import math
import re
from xml.etree import ElementTree as ET

NS = {"s": "http://www.sila-standard.org"}
NUMERIC = ("MinimalInclusive", "MaximalInclusive", "MinimalExclusive", "MaximalExclusive")
COUNTS = (
    "Length",
    "MinimalLength",
    "MaximalLength",
    "ElementCount",
    "MinimalElementCount",
    "MaximalElementCount",
)


class FeatureError(ValueError):
    """The document is not a Feature Definition this reader understands."""


def digest(xml):
    """The identity of a Feature Definition: the SHA-256 of the text the server returned."""
    return hashlib.sha256(xml.encode()).hexdigest()


def _text(node, tag):
    return (node.findtext(f"s:{tag}", namespaces=NS) or "").strip()


def _type(node):
    """A DataType element as plain data."""
    kind = next(iter(node), None)
    if kind is None:
        raise FeatureError("Empty DataType")
    tag = kind.tag.rsplit("}", 1)[-1]
    if tag == "Basic":
        return {"kind": "basic", "basic": kind.text.strip()}
    if tag == "DataTypeIdentifier":
        return {"kind": "ref", "id": kind.text.strip()}
    if tag == "List":
        return {"kind": "list", "item": _type(kind.find("s:DataType", NS))}
    if tag == "Structure":
        return {
            "kind": "structure",
            "fields": [
                {"name": _text(e, "Identifier"), "type": _type(e.find("s:DataType", NS))}
                for e in kind.findall("s:Element", NS)
            ],
        }
    if tag == "Constrained":
        rules = {}
        for rule in kind.find("s:Constraints", NS):
            name = rule.tag.rsplit("}", 1)[-1]
            if name in NUMERIC or name in COUNTS:
                rules[name] = rule.text.strip()
            elif name == "Pattern":
                rules[name] = rule.text or ""
            elif name == "Set":
                rules[name] = [v.text or "" for v in rule.findall("s:Value", NS)]
            elif name == "Unit":
                rules[name] = _text(rule, "Label")
            # Content type, schema and allowed-type rules describe payloads; not checked here.
        return {
            "kind": "constrained",
            "base": _type(kind.find("s:DataType", NS)),
            "constraints": rules,
        }
    raise FeatureError(f"Unknown data type {tag}")


def _fields(node, tag):
    return [
        {
            "name": _text(e, "Identifier"),
            "description": _text(e, "Description"),
            "type": _type(e.find("s:DataType", NS)),
        }
        for e in node.findall(f"s:{tag}", NS)
    ]


def parse(xml):
    """A Feature Definition as plain data, with its fully qualified identifier and digest."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise FeatureError(f"Not XML: {exc}") from exc
    if root.tag != f"{{{NS['s']}}}Feature":
        raise FeatureError("Not a SiLA 2 Feature Definition")
    identifier = _text(root, "Identifier")
    major = root.get("FeatureVersion", "1.0").split(".")[0]
    return {
        "id": f"{root.get('Originator')}/{root.get('Category')}/{identifier}/v{major}",
        "identifier": identifier,
        "name": _text(root, "DisplayName"),
        "description": _text(root, "Description"),
        "version": root.get("FeatureVersion", ""),
        "maturity": root.get("MaturityLevel", ""),
        "sha256": digest(xml),
        "commands": {
            _text(c, "Identifier"): {
                "description": _text(c, "Description"),
                "observable": _text(c, "Observable") == "Yes",
                "parameters": _fields(c, "Parameter"),
                "responses": _fields(c, "Response"),
                "errors": [
                    e.text.strip() for e in c.findall("s:DefinedExecutionErrors/s:Identifier", NS)
                ],
            }
            for c in root.findall("s:Command", NS)
        },
        "properties": {
            _text(p, "Identifier"): {
                "description": _text(p, "Description"),
                "observable": _text(p, "Observable") == "Yes",
                "type": _type(p.find("s:DataType", NS)),
            }
            for p in root.findall("s:Property", NS)
        },
        "errors": {
            _text(e, "Identifier"): _text(e, "Description")
            for e in root.findall("s:DefinedExecutionError", NS)
        },
        "types": {
            _text(t, "Identifier"): _type(t.find("s:DataType", NS))
            for t in root.findall("s:DataTypeDefinition", NS)
        },
    }


def _number(text):
    try:
        return float(text)
    except ValueError:
        return None


def _matches(pattern, value):
    try:
        return re.fullmatch(pattern, value) is not None
    except re.error:
        return True  # an XML Schema expression Python cannot read is left to the server


def _basic(basic, value):
    if basic == "Boolean":
        return isinstance(value, bool)
    if basic == "Integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if basic == "Real":
        return (
            isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
        )
    if basic == "Any":
        return True
    # String, Binary (base64), Date, Time and Timestamp travel as text.
    return isinstance(value, str)


def _check(kind, value, types, where):
    """Problems with one value against one data type, each naming where it is."""
    if kind["kind"] == "ref":
        target = types.get(kind["id"])
        return _check(target, value, types, where) if target else []
    if kind["kind"] == "basic":
        basic = kind["basic"]
        return [] if _basic(basic, value) else [f"{where} must be {basic.lower()}"]
    if kind["kind"] == "list":
        if not isinstance(value, list):
            return [f"{where} must be a list"]
        return [
            problem
            for index, item in enumerate(value)
            for problem in _check(kind["item"], item, types, f"{where}[{index}]")
        ]
    if kind["kind"] == "structure":
        if not isinstance(value, dict):
            return [f"{where} must be an object"]
        names = [f["name"] for f in kind["fields"]]
        problems = [f"{where} has no element {k}" for k in value if k not in names]
        for field in kind["fields"]:
            if field["name"] not in value:
                problems.append(f"{where} needs {field['name']}")
            else:
                problems += _check(
                    field["type"], value[field["name"]], types, f"{where}.{field['name']}"
                )
        return problems
    problems = _check(kind["base"], value, types, where)
    if problems:
        return problems
    rules = kind["constraints"]
    unit = f" {rules['Unit']}" if rules.get("Unit") else ""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        for name, ok, word in (
            ("MinimalInclusive", lambda v, b: v >= b, "at least"),
            ("MaximalInclusive", lambda v, b: v <= b, "at most"),
            ("MinimalExclusive", lambda v, b: v > b, "more than"),
            ("MaximalExclusive", lambda v, b: v < b, "less than"),
        ):
            bound = _number(rules[name]) if name in rules else None
            if bound is not None and not ok(value, bound):
                problems.append(f"{where} must be {word} {bound:g}{unit}; got {value:g}")
    if isinstance(value, (str, list)):
        size, noun = len(value), "characters" if isinstance(value, str) else "items"
        exact, low, high = (
            ("Length", "MinimalLength", "MaximalLength")
            if isinstance(value, str)
            else ("ElementCount", "MinimalElementCount", "MaximalElementCount")
        )
        if exact in rules and size != int(rules[exact]):
            problems.append(f"{where} must have exactly {rules[exact]} {noun}")
        if low in rules and size < int(rules[low]):
            problems.append(f"{where} must have at least {rules[low]} {noun}")
        if high in rules and size > int(rules[high]):
            problems.append(f"{where} must have at most {rules[high]} {noun}")
    if isinstance(value, str):
        if "Pattern" in rules and not _matches(rules["Pattern"], value):
            problems.append(f"{where} must match {rules['Pattern']}")
        if "Set" in rules and value not in rules["Set"]:
            problems.append(f"{where} must be one of {', '.join(rules['Set'])}")
    if "Set" in rules and isinstance(value, (int, float)) and not isinstance(value, bool):
        allowed = [_number(v) for v in rules["Set"]]
        if value not in allowed:
            problems.append(f"{where} must be one of {', '.join(rules['Set'])}")
    return problems


def check_arguments(feature, command, arguments):
    """Why a SiLA server would refuse this call before running it; empty when it would not."""
    found = feature["commands"].get(command)
    if found is None:
        return [f"{feature['identifier']} has no command {command}"]
    if not isinstance(arguments, dict):
        return [f"{command} takes an object of parameters"]
    names = [p["name"] for p in found["parameters"]]
    problems = [f"{command} has no parameter {k}" for k in arguments if k not in names]
    for parameter in found["parameters"]:
        if parameter["name"] not in arguments:
            problems.append(f"{command} needs {parameter['name']}")
        else:
            problems += _check(
                parameter["type"],
                arguments[parameter["name"]],
                feature["types"],
                parameter["name"],
            )
    return problems


def summary(kind, types=None):
    """One line describing a data type, for catalogs and messages."""
    types = types or {}
    if kind["kind"] == "basic":
        return kind["basic"]
    if kind["kind"] == "ref":
        return kind["id"]
    if kind["kind"] == "list":
        return f"list of {summary(kind['item'], types)}"
    if kind["kind"] == "structure":
        return "{" + ", ".join(f["name"] for f in kind["fields"]) + "}"
    rules = kind["constraints"]
    parts = []
    low = rules.get("MinimalInclusive", rules.get("MinimalExclusive"))
    high = rules.get("MaximalInclusive", rules.get("MaximalExclusive"))
    if low is not None or high is not None:
        parts.append(f"{low if low is not None else '…'}–{high if high is not None else '…'}")
    if rules.get("Unit"):
        parts.append(rules["Unit"])
    if "Set" in rules:
        parts.append(" | ".join(rules["Set"]))
    if "Pattern" in rules:
        parts.append(f"/{rules['Pattern']}/")
    base = summary(kind["base"], types)
    return f"{base} ({' '.join(parts)})" if parts else base
