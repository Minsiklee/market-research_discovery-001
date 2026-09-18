# -*- coding: utf-8 -*-
"""settings.txt 에서 레딧 접속 정보를 읽는다 — 환경변수를 못 쓰는 환경용.

회사 정책으로 PowerShell 이 막혀 있으면 `$env:...` 로 값을 넣을 수 없다.
그래서 저장소 맨 위의 settings.txt 를 메모장으로 열어 적는 길을 연다.

우선순위: 환경변수 > settings.txt. 환경변수가 이미 있으면 그쪽이 이긴다.
"""
import os

KEYS = ("REDDIT_USER_AGENT", "REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET",
        "REDDIT_USERNAME", "REDDIT_PASSWORD")
# 값에 # 이 들어갈 수 없는 키 — 줄 끝 주석을 걷어낸다
NO_HASH = ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET", "REDDIT_USERNAME")

TEMPLATE = """\
# 레딧 접속 정보 — 이 파일을 메모장으로 열어 값만 채우고 저장하세요.
# = 앞뒤에 공백이 있어도 됩니다. # 으로 시작하는 줄은 무시합니다.

# [필수] 레딧에 "누가 접속하는지" 밝히는 이름표.
#        이게 없으면 레딧이 차단합니다. 레딧 계정이 없으면 아무 이름이나 넣어도 됩니다.
REDDIT_USER_AGENT = python:genesis-research:v1.0 (by /u/여기에_레딧아이디)

# [선택] 있으면 4배 빨라집니다 (20~40분 -> 5~10분). 없어도 그냥 돌아갑니다.
#
#   https://www.reddit.com/prefs/apps 에서 create app -> 종류는 반드시 script
#   만든 뒤 앱을 펼치면 두 문자열이 보입니다. 헷갈리기 쉬우니 잘 보세요.
#
#     앱 이름 바로 아래, "personal use script" 라는 글자 위의 짧은 문자열  -> CLIENT_ID
#     "secret" 이라고 적힌 칸 옆의 긴 문자열                              -> CLIENT_SECRET
#
#   "personal use script" 라는 글자 자체를 넣으면 401 이 납니다.
#   401 이 나도 수집은 계속됩니다 — 느려질 뿐입니다. 그때는 이 두 줄을 비우세요.
REDDIT_CLIENT_ID =
REDDIT_CLIENT_SECRET =

# [선택의 선택] 위 둘로 401 이 계속 나면, 레딧 계정으로 인증하는 방법도 있습니다.
#              2단계 인증(2FA)을 켠 계정은 이 방법이 안 됩니다.
#              쓰지 않을 거면 두 줄 모두 비워 두세요.
REDDIT_USERNAME =
REDDIT_PASSWORD =
"""


def path(root=None):
    root = root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, "settings.txt")


def _read(p):
    for enc in ("utf-8-sig", "cp949", "latin-1"):       # 메모장은 BOM 을 붙이거나 ANSI 로 저장한다
        try:
            with open(p, encoding=enc) as f:
                return f.read()
        except (UnicodeDecodeError, LookupError):
            continue
    return ""


def load(root=None):
    """settings.txt 값을 환경변수에 채운다. (파일경로, 읽어들인 값) 을 돌려준다."""
    p = path(root)
    if not os.path.exists(p):
        return p, {}
    vals = {}
    for line in _read(p).splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip().upper(), v.strip()
        if k in NO_HASH and "#" in v:
            v = v.split("#", 1)[0].strip()
        v = v.strip('"').strip("'").strip()
        # 예시 문구를 그대로 둔 경우는 안 채운 것으로 본다
        if k in KEYS and v and "여기에_" not in v:
            vals[k] = v
    for k, v in vals.items():
        os.environ.setdefault(k, v)
    return p, vals


def ensure(root=None):
    """없으면 빈 양식을 만들어 준다. (경로, 새로 만들었는가)"""
    p = path(root)
    if os.path.exists(p):
        return p, False
    with open(p, "w", encoding="utf-8") as f:
        f.write(TEMPLATE)
    return p, True
