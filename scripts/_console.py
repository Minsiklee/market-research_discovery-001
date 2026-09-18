# -*- coding: utf-8 -*-
"""윈도우 콘솔에서 한글·기호 출력이 깨지거나 멈추지 않게 한다.

윈도우 파이썬은 콘솔에 직접 찍을 때는 유니코드를 잘 쓰지만, 출력을 파일이나
파이프로 넘기면 시스템 코드페이지(한국어 윈도우면 cp949)로 인코딩한다.
cp949 에 없는 기호가 하나라도 있으면 UnicodeEncodeError 로 **프로그램이 죽는다.**
수집이 20분 돌다가 로그 한 줄 때문에 죽는 일을 막는다.
"""
import sys


def setup():
    for name in ("stdout", "stderr"):
        f = getattr(sys, name, None)
        if f is None or not hasattr(f, "reconfigure"):
            continue
        try:
            if f.isatty():
                f.reconfigure(errors="replace")          # 콘솔은 그대로 두고 안전망만
            else:
                f.reconfigure(encoding="utf-8", errors="replace")   # 파일·파이프는 UTF-8
        except Exception:
            pass


def _ok(ch):
    enc = getattr(sys.stdout, "encoding", None) or "ascii"
    try:
        ch.encode(enc)
        return True
    except Exception:
        return False


def marks():
    """(통과, 실패, 주의) 표시. 콘솔이 못 그리는 기호면 ASCII 로 떨어진다."""
    if _ok("✅"):
        return "  ✅", "  ❌", "  ⚠️ "
    return "  [OK]", "  [실패]", "  [주의]"
