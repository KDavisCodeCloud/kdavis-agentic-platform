"""
PROPRIETARY AND CONFIDENTIAL
Copyright (c) 2026 THD Agentic Systems LLC. All rights reserved.

Minimal Terraform edits for fix PRs (G16, Break-It Lab run 2).

Agent 08 used to commit the LLM's "corrected content" over the whole IaC
file. In the lab that replaced a 189-line aws/main.tf (and a 242-line
azure/main.tf) with a malformed JSON dump of one resource. Now:

  - the LLM returns ONE resource block and its address;
  - replace_resource_block() swaps exactly that block in the real file,
    leaving every other byte as it was;
  - anything that isn't exactly one `resource "<type>" "<name>" { ... }`
    block with the same address (JSON, two blocks, a renamed resource,
    an unbalanced brace) is refused.

The scanner understands enough HCL to find top-level block boundaries:
quoted strings, `#` / `//` / `/* */` comments, and `<<EOF` / `<<-EOF`
heredocs. Braces inside any of those never count. Whether the result is
valid Terraform is the terraform gate's job (core/terraform_gate.py), which
runs before any PR is opened.
"""

import difflib
import re
from dataclasses import dataclass
from typing import Optional

_ADDRESS = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*)\.([A-Za-z_][A-Za-z0-9_-]*)$")
_HEADER = re.compile(r'^\s*([A-Za-z_][\w-]*)((?:\s+"(?:[^"\\]|\\.)*"|\s+[A-Za-z_][\w-]*)*)\s*\{\s*$')
_LABEL = re.compile(r'"((?:[^"\\]|\\.)*)"|([A-Za-z_][\w-]*)')
_HEREDOC = re.compile(r"<<-?([A-Za-z_][A-Za-z0-9_]*)[ \t]*\n")


class HclEditError(ValueError):
    """The edit can't be made safely; the message says why (shown on the incident)."""


@dataclass(frozen=True)
class Block:
    kind: str            # "resource", "variable", ...
    labels: tuple        # ("aws_security_group", "web")
    start: int           # offset of the first char of the header line
    end: int             # offset just past the closing brace's line (incl. newline)

    @property
    def address(self) -> Optional[str]:
        if self.kind == "resource" and len(self.labels) == 2:
            return f"{self.labels[0]}.{self.labels[1]}"
        return None


def top_level_blocks(text: str) -> list[Block]:
    """Every top-level block in `text`. Raises HclEditError on unbalanced braces
    or an unterminated string, comment or heredoc."""
    blocks: list[Block] = []
    depth = 0
    open_at = -1
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == '"':
            i = _skip_string(text, i)
            continue
        if c == "#" or text.startswith("//", i):
            nl = text.find("\n", i)
            i = n if nl == -1 else nl
            continue
        if text.startswith("/*", i):
            close = text.find("*/", i + 2)
            if close == -1:
                raise HclEditError("unterminated /* comment")
            i = close + 2
            continue
        if text.startswith("<<", i):
            m = _HEREDOC.match(text, i)
            if m:
                i = _skip_heredoc(text, m)
                continue
        if c == "{":
            if depth == 0:
                open_at = i
            depth += 1
        elif c == "}":
            depth -= 1
            if depth < 0:
                raise HclEditError("unbalanced '}'")
            if depth == 0:
                blocks.append(_block(text, open_at, i))
        i += 1
    if depth != 0:
        raise HclEditError("unbalanced '{' -- a block never closes")
    return blocks


def resource_addresses(text: str) -> list[str]:
    return [b.address for b in top_level_blocks(text) if b.address]


def replace_resource_block(original: str, address: str, new_block: str) -> str:
    """`original` with the one resource block at `address` replaced by
    `new_block`. Every byte outside that block is unchanged."""
    if not _ADDRESS.match(address or ""):
        raise HclEditError(f"not a resource address: {address!r} (expected type.name)")

    matches = [b for b in top_level_blocks(original) if b.address == address]
    if not matches:
        raise HclEditError(f"resource {address} is not defined in this file")
    if len(matches) > 1:
        raise HclEditError(f"resource {address} is defined more than once in this file")
    target = matches[0]

    replacement = _single_block(new_block, address)
    return original[:target.start] + replacement + original[target.end:]


def resource_block_text(text: str, address: str) -> Optional[str]:
    """The current text of the block at `address`, or None."""
    for b in top_level_blocks(text):
        if b.address == address:
            return text[b.start:b.end]
    return None


def unified_diff(path: str, before: str, after: str) -> str:
    return "".join(difflib.unified_diff(
        before.splitlines(keepends=True), after.splitlines(keepends=True),
        fromfile=f"a/{path}", tofile=f"b/{path}",
    ))


# ── internals ────────────────────────────────────────────────────────────────

def _single_block(new_block: str, address: str) -> str:
    text = (new_block or "").strip("\n")
    if not text.strip():
        raise HclEditError("the proposed block is empty")
    if text.lstrip().startswith(("{", "[")):
        raise HclEditError("the proposed change is JSON, not HCL")
    blocks = top_level_blocks(text + "\n")
    if len(blocks) != 1:
        raise HclEditError(f"the proposed change must be exactly one resource block, got {len(blocks)}")
    block = blocks[0]
    if block.address != address:
        raise HclEditError(f"the proposed block is {block.address or block.kind}, not {address} "
                           "(renaming or replacing a resource isn't a minimal fix)")
    outside = (text + "\n")[:block.start] + (text + "\n")[block.end:]
    if _strip_comments(outside).strip():
        raise HclEditError("the proposed change has content outside the resource block")
    return text + "\n"


def _block(text: str, open_at: int, close_at: int) -> Block:
    line_start = text.rfind("\n", 0, open_at) + 1
    header = text[line_start:open_at + 1]
    m = _HEADER.match(header)
    if not m:
        raise HclEditError(f"unrecognized top-level block header: {header.strip()[:80]!r}")
    labels = tuple(a if a is not None else b for a, b in _LABEL.findall(m.group(2)))
    nl = text.find("\n", close_at)
    end = len(text) if nl == -1 else nl + 1
    if _strip_comments(text[close_at + 1:end]).strip():
        raise HclEditError("content after a block's closing brace on the same line")
    return Block(kind=m.group(1), labels=labels, start=line_start, end=end)


def _skip_string(text: str, i: int) -> int:
    j = i + 1
    while j < len(text):
        if text[j] == "\\":
            j += 2
            continue
        if text[j] == '"':
            return j + 1
        if text[j] == "\n":
            raise HclEditError("unterminated string")
        j += 1
    raise HclEditError("unterminated string")


def _skip_heredoc(text: str, m: re.Match) -> int:
    tag = m.group(1)
    pos = m.end()
    while pos < len(text):
        nl = text.find("\n", pos)
        line = text[pos:] if nl == -1 else text[pos:nl]
        if line.strip() == tag:
            return pos + len(line)
        if nl == -1:
            break
        pos = nl + 1
    raise HclEditError(f"unterminated heredoc <<{tag}")


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"(#|//)[^\n]*", "", text)
