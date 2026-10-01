"""Read and write data/ YAML files without changing their formatting.

Every data file is plain block YAML (as written by the collectors), sometimes under a few
leading "# ..." comment lines. read_doc() refuses a file that a rewrite would reformat, so a
tool never makes a noisy diff in a hand-edited file; that file has to be updated by hand.
"""

from __future__ import annotations

from pathlib import Path

import yaml


class _Dumper(yaml.SafeDumper):
    pass


_Dumper.add_representer(type(None), lambda d, _: d.represent_scalar("tag:yaml.org,2002:null", "null"))


class NotRoundTrip(ValueError):
    """The file isn't in the standard generated format; edit it by hand instead."""


def to_yaml(doc) -> str:
    return yaml.dump(doc, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=10000)


def read_doc(path: Path) -> tuple[str, object]:
    """(leading comment header, parsed document). Raises NotRoundTrip for hand-formatted files."""
    text = path.read_text(encoding="utf-8")
    header = ""
    for line in text.splitlines(keepends=True):
        if not line.startswith("#"):
            break
        header += line
    doc = yaml.safe_load(text)
    if to_yaml(doc) != text[len(header):]:
        raise NotRoundTrip(f"{path}: not in the standard generated format; update it by hand")
    return header, doc


def write_doc(path: Path, header: str, doc) -> None:
    path.write_text(header + to_yaml(doc), encoding="utf-8", newline="\n")
