# -*- coding: utf-8 -*-
"""realty.daangn.com 2026-10 개편(realty-web v93, TanStack Start) 대응 — SSR 데이터 추출.

개편 전에는 `window.RELAY_STORE = "<JSON 문자열>"` 로 Relay 캐시가 내려왔지만,
개편 후에는 `<script class="$tsr" id="$tsr-stream-barrier">` 안에 seroval 방식의
JS 식(`$R[12]={...}` 대입 + `$R[12]` 역참조, `!0/!1`, 따옴표 없는 키 등)으로 들어온다.
JSON 이 아니므로 작은 파서를 직접 돌려 파이썬 dict 로 바꾸고, 그 안에서
`client:root` 키를 가진 Relay 스토어 dict 를 찾아 돌려준다. 결과 모양(__ref/__refs/__typename)은
예전 RELAY_STORE 와 같아서 기존 파싱 코드를 그대로 쓸 수 있다.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

_RELAY_OLD = re.compile(r'window\.RELAY_STORE\s*=\s*"(.*?)";</script>', re.S)
_TSR_SCRIPT = re.compile(r'<script[^>]*id="\$tsr-stream-barrier"[^>]*>(.*?)</script>', re.S)
_NUM = re.compile(r'-?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?')
_IDENT = re.compile(r'[A-Za-z_$][A-Za-z0-9_$]*')
_REF = re.compile(r'\$R\[(\d+)\]')


class _Undefined:
    def __repr__(self):
        return "undefined"


UNDEFINED = _Undefined()


class JsLiteralParser:
    """seroval/TanStack 가 내보내는 JS 데이터 식 한 개를 파이썬 객체로 바꾼다."""

    def __init__(self, src: str, pos: int = 0):
        self.s = src
        self.i = pos
        self.n = len(src)
        self.refs: Dict[int, Any] = {}

    # ---- helpers
    def _ws(self):
        while self.i < self.n and self.s[self.i] in " \t\r\n":
            self.i += 1

    def _peek(self, k: int = 1) -> str:
        return self.s[self.i:self.i + k]

    def _expect(self, ch: str):
        self._ws()
        if not self.s.startswith(ch, self.i):
            raise ValueError(f"expected {ch!r} at {self.i}: {self.s[self.i:self.i+40]!r}")
        self.i += len(ch)

    def _skip_balanced(self, open_ch: str, close_ch: str):
        """괄호 균형을 맞춰 건너뛴다(문자열 안의 괄호는 무시). 알 수 없는 호출식 등에 사용."""
        depth = 0
        while self.i < self.n:
            c = self.s[self.i]
            if c == '"' or c == "'":
                self._string()
                continue
            if c == open_ch:
                depth += 1
            elif c == close_ch:
                depth -= 1
                if depth == 0:
                    self.i += 1
                    return
            self.i += 1

    # ---- primitives
    def _string(self) -> str:
        q = self.s[self.i]
        self.i += 1
        out: List[str] = []
        s = self.s
        while self.i < self.n:
            c = s[self.i]
            if c == q:
                self.i += 1
                return "".join(out)
            if c == "\\":
                self.i += 1
                e = s[self.i]
                self.i += 1
                if e == "n":
                    out.append("\n")
                elif e == "r":
                    out.append("\r")
                elif e == "t":
                    out.append("\t")
                elif e == "b":
                    out.append("\b")
                elif e == "f":
                    out.append("\f")
                elif e == "v":
                    out.append("\v")
                elif e == "0" and not (self.i < self.n and s[self.i].isdigit()):
                    out.append("\0")
                elif e == "x":
                    out.append(chr(int(s[self.i:self.i + 2], 16)))
                    self.i += 2
                elif e == "u":
                    if s[self.i] == "{":
                        j = s.index("}", self.i)
                        out.append(chr(int(s[self.i + 1:j], 16)))
                        self.i = j + 1
                    else:
                        cp = int(s[self.i:self.i + 4], 16)
                        self.i += 4
                        # 서로게이트 쌍 결합
                        if 0xD800 <= cp <= 0xDBFF and s.startswith("\\u", self.i):
                            lo = int(s[self.i + 2:self.i + 6], 16)
                            if 0xDC00 <= lo <= 0xDFFF:
                                cp = 0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00)
                                self.i += 6
                        out.append(chr(cp))
                elif e in "\r\n":
                    if e == "\r" and s[self.i:self.i + 1] == "\n":
                        self.i += 1
                else:
                    out.append(e)
                continue
            out.append(c)
            self.i += 1
        raise ValueError("unterminated string")

    def _key(self) -> str:
        self._ws()
        c = self.s[self.i]
        if c == '"' or c == "'":
            return self._string()
        if c == "[":
            # 계산된 키 [expr] — 값을 파싱해 문자열화
            self.i += 1
            v = self.value()
            self._expect("]")
            return str(v)
        m = _NUM.match(self.s, self.i)
        if m and (c.isdigit() or c in "-."):
            self.i = m.end()
            return m.group(0)
        m = _IDENT.match(self.s, self.i)
        if not m:
            raise ValueError(f"bad key at {self.i}: {self.s[self.i:self.i+40]!r}")
        self.i = m.end()
        return m.group(0)

    # ---- composite
    def _object(self) -> Dict[str, Any]:
        self._expect("{")
        d: Dict[str, Any] = {}
        while True:
            self._ws()
            if self._peek() == "}":
                self.i += 1
                return d
            k = self._key()
            self._expect(":")
            d[k] = self.value()
            self._ws()
            if self._peek() == ",":
                self.i += 1
                continue
            if self._peek() == "}":
                self.i += 1
                return d
            raise ValueError(f"bad object at {self.i}: {self.s[self.i:self.i+40]!r}")

    def _array(self) -> List[Any]:
        self._expect("[")
        a: List[Any] = []
        while True:
            self._ws()
            c = self._peek()
            if c == "]":
                self.i += 1
                return a
            if c == ",":  # 구멍(hole)
                self.i += 1
                a.append(None)
                continue
            a.append(self.value())
            self._ws()
            if self._peek() == ",":
                self.i += 1
                self._ws()
                if self._peek() == "]":
                    self.i += 1
                    return a
                continue
            if self._peek() == "]":
                self.i += 1
                return a
            raise ValueError(f"bad array at {self.i}: {self.s[self.i:self.i+40]!r}")

    def _call_args(self) -> List[Any]:
        self._expect("(")
        args: List[Any] = []
        while True:
            self._ws()
            if self._peek() == ")":
                self.i += 1
                return args
            args.append(self.value())
            self._ws()
            if self._peek() == ",":
                self.i += 1
                continue
            self._expect(")")
            return args

    def value(self) -> Any:
        self._ws()
        s, i = self.s, self.i
        c = s[i]
        # $R[n]=value  /  $R[n]
        m = _REF.match(s, i)
        if m:
            idx = int(m.group(1))
            self.i = m.end()
            self._ws()
            if self._peek() == "=" and self._peek(2) not in ("==", "=>"):
                self.i += 1
                # 순환 참조 대비: 컨테이너는 먼저 등록
                self._ws()
                if self._peek() == "{":
                    holder: Dict[str, Any] = {}
                    self.refs[idx] = holder
                    holder.update(self._object())
                    return holder
                if self._peek() == "[":
                    lst: List[Any] = []
                    self.refs[idx] = lst
                    lst.extend(self._array())
                    return lst
                v = self.value()
                self.refs[idx] = v
                return v
            return self.refs.get(idx)
        if c == '"' or c == "'":
            return self._string()
        if c == "{":
            return self._object()
        if c == "[":
            return self._array()
        if c == "!":
            # !0 → true, !1 → false
            self.i += 1
            m = _NUM.match(s, self.i)
            if not m:
                raise ValueError(f"bad ! at {i}")
            self.i = m.end()
            return float(m.group(0)) == 0.0
        if c == "-" or c.isdigit() or c == ".":
            m = _NUM.match(s, i)
            if m:
                self.i = m.end()
                txt = m.group(0)
                # 1/0, -1/0, 0/0 → Infinity/NaN
                self._ws()
                if self._peek() == "/":
                    self.i += 1
                    m2 = _NUM.match(s, self.i)
                    if m2:
                        self.i = m2.end()
                    num = float(txt)
                    return float("nan") if num == 0 else (float("inf") if num > 0 else float("-inf"))
                try:
                    return int(txt) if re.fullmatch(r"-?\d+", txt) else float(txt)
                except ValueError:
                    return float(txt)
        if c == "(":
            # (expr) 괄호식 — 안의 값 하나
            self.i += 1
            v = self.value()
            self._ws()
            if self._peek() == ")":
                self.i += 1
            else:
                self._skip_balanced("(", ")")  # 모르는 식
            return v
        m = _IDENT.match(s, i)
        if m:
            word = m.group(0)
            self.i = m.end()
            if word == "null":
                return None
            if word == "undefined":
                return UNDEFINED
            if word == "true":
                return True
            if word == "false":
                return False
            if word == "NaN":
                return float("nan")
            if word == "Infinity":
                return float("inf")
            if word == "void":
                self._ws()
                self.value()
                return UNDEFINED
            if word == "new":
                self._ws()
                m2 = _IDENT.match(s, self.i)
                name = m2.group(0) if m2 else ""
                self.i = m2.end() if m2 else self.i
                # new Date("..."), new Map([...]), new Set([...]) 등 → 첫 인자
                self._ws()
                args = self._call_args() if self._peek() == "(" else []
                if name == "Map" and args and isinstance(args[0], list):
                    return {str(k): v for k, v in (p for p in args[0] if isinstance(p, list) and len(p) == 2)}
                return args[0] if args else None
            if word == "Object":
                # Object.assign(Object.create(null),{...}) → {...}
                self._ws()
                if s.startswith(".assign", self.i):
                    self.i += len(".assign")
                    args = self._call_args()
                    merged: Dict[str, Any] = {}
                    for a in args:
                        if isinstance(a, dict):
                            merged.update(a)
                    return merged
                if s.startswith(".create", self.i):
                    self.i += len(".create")
                    self._call_args()
                    return {}
            # 그 밖의 식별자(Symbol.for(...), 함수 등) — 뒤따르는 .x / (...) 를 통째로 건너뜀
            while self.i < self.n:
                self._ws()
                if self._peek() == ".":
                    self.i += 1
                    m3 = _IDENT.match(s, self.i)
                    self.i = m3.end() if m3 else self.i
                    continue
                if self._peek() == "(":
                    self._skip_balanced("(", ")")
                    continue
                if self._peek(2) == "=>":
                    self.i += 2
                    self._ws()
                    if self._peek() == "{":
                        self._skip_balanced("{", "}")
                    else:
                        self.value()
                    continue
                break
            return UNDEFINED
        raise ValueError(f"unexpected char {c!r} at {i}: {s[i:i+40]!r}")


def _find_relay_store(obj: Any, depth: int = 0) -> Optional[Dict[str, Any]]:
    """파싱된 트리에서 'client:root' 키를 가진 dict(Relay 스토어)를 찾는다."""
    if depth > 60:
        return None
    if isinstance(obj, dict):
        if "client:root" in obj:
            return obj
        for v in obj.values():
            r = _find_relay_store(v, depth + 1)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _find_relay_store(v, depth + 1)
            if r is not None:
                return r
    return None


def parse_tsr_script(body: str) -> Any:
    """$tsr-stream-barrier 스크립트 본문에서 데이터 식을 파싱한다. `($R=>` 뒤의 식 하나."""
    k = body.find("$R=>")
    if k < 0:
        raise ValueError("no $R=> in tsr script")
    p = JsLiteralParser(body, k + 4)
    return p.value()


def extract_relay_store(html: str) -> Optional[Dict[str, Any]]:
    """HTML 에서 Relay 스토어 dict 를 꺼낸다. 구 형식(window.RELAY_STORE) → 신 형식($tsr) 순으로 시도."""
    m = _RELAY_OLD.search(html)
    if m:
        try:
            return json.loads(json.loads('"' + m.group(1) + '"'))
        except Exception:
            pass
    m = _TSR_SCRIPT.search(html)
    if not m:
        return None
    try:
        tree = parse_tsr_script(m.group(1))
    except Exception:
        return None
    return _find_relay_store(tree)
