# -*- coding: utf-8 -*-
"""keyword_dictionary_v1 §1·§2-2(US) 를 정규식으로 옮긴 것.

원칙(사전 §0): 사전은 넣는 문이지 거르는 문이 아니다.
여기서는 점수 계산용 매칭만 한다. 무관 필터(§5 문맥어)는 적용하지 않는다.

canonical: 파워트레인 변형·바디 변형을 기본 차명으로 접는다.
  점수 조항 "모델 2개 이상"에서 eG80 과 G80 을 두 대로 세지 않기 위한 것.
  표시용 models 열에는 변형 코드를 그대로 남긴다.
marque: "모델+브랜드" 조항의 교차 마크 판정에 쓴다.
"""

# (code, marque, canonical, pattern)
MODELS = [
    # ---- §1 제네시스 모델 · 파워트레인 변형 ----
    ("eG80",       "Genesis", "G80",   r"(?:electrified\s+g[-\s]?80|\beg80\b|\bg[-\s]?80\s+(?:ev|electric)\b)"),
    ("eGV70",      "Genesis", "GV70",  r"(?:electrified\s+gv[-\s]?70|\begv70\b|\bgv70e\b|\bgv[-\s]?70\s+(?:ev|electric)\b)"),
    ("GV70 EREV",  "Genesis", "GV70",  r"(?:\bgv[-\s]?70\s+erev\b|\bgv[-\s]?70\s+range\s+extender\b|extended[-\s]range\s+gv[-\s]?70)"),
    ("GV70 HEV",   "Genesis", "GV70",  r"(?:\bgv[-\s]?70\s+hybrid\b|\bgenesis\s+hybrid\b|\brwd\s+hybrid\b)"),
    ("GV80 Coupe", "Genesis", "GV80",  r"(?:\bgv[-\s]?80\s?coupe\b|\bgv[-\s]?80c\b)"),
    ("G70",        "Genesis", "G70",   r"\bg[-\s]?70\b"),
    ("G80",        "Genesis", "G80",   r"\bg[-\s]?80\b"),
    ("G90",        "Genesis", "G90",   r"\bg[-\s]?90\b"),
    ("GV60",       "Genesis", "GV60",  r"\bgv[-\s]?60\b"),
    ("GV70",       "Genesis", "GV70",  r"\bgv[-\s]?70\b"),
    ("GV80",       "Genesis", "GV80",  r"\bgv[-\s]?80\b"),
    ("GV90",       "Genesis", "GV90",  r"(?:\bgv[-\s]?90\b|\bneolun\b)"),
    # ---- §2-2 미국 US · I-H 현대기아 ----
    ("Palisade",   "Hyundai", "Palisade", r"\bpalisade\b"),
    ("Santa Fe",   "Hyundai", "Santa Fe", r"\bsanta\s?fe\b"),
    ("Ioniq 5 N",  "Hyundai", "Ioniq 5",  r"\bioniq\s?-?\s?5\s?n\b"),
    ("Ioniq 5",    "Hyundai", "Ioniq 5",  r"\bioniq\s?-?\s?5\b"),
    ("Ioniq 6",    "Hyundai", "Ioniq 6",  r"\bioniq\s?-?\s?6\b"),
    ("Telluride",  "Kia", "Telluride", r"\btelluride\b"),
    ("Sportage",   "Kia", "Sportage",  r"\bsportage\b"),
    ("Seltos",     "Kia", "Seltos",    r"\bseltos\b"),
    ("EV6",        "Kia", "EV6",       r"\bev\s?-?\s?6\b"),
    ("EV9",        "Kia", "EV9",       r"\bev\s?-?\s?9\b"),
    ("Stinger",    "Kia", "Stinger",   r"\bstinger\b"),
    # ---- §2-2 B 독일 ----
    ("M340i",      "BMW", "M340i",     r"\bm340i\b"),
    ("3 Series",   "BMW", "3 Series",  r"\b3\s?-?\s?series\b"),
    ("5 Series",   "BMW", "5 Series",  r"\b5\s?-?\s?series\b"),
    ("X3",         "BMW", "X3",        r"\bx\s?-?\s?3\b"),
    ("X5",         "BMW", "X5",        r"\bx\s?-?\s?5\b"),
    ("i4",         "BMW", "i4",        r"\bi\s?-?\s?4\b"),
    ("i5",         "BMW", "i5",        r"\bi\s?-?\s?5\b"),
    ("iX",         "BMW", "iX",        r"\bix\b"),
    ("C300",       "Mercedes", "C300",    r"\bc\s?-?\s?300\b"),
    ("E-Class",    "Mercedes", "E-Class", r"\be[-\s]?class\b"),
    ("GLC",        "Mercedes", "GLC",     r"\bglc\b"),
    ("GLE",        "Mercedes", "GLE",     r"\bgle\b"),
    ("EQE",        "Mercedes", "EQE",     r"\beqe\b"),
    ("A6",         "Audi", "A6",  r"\ba\s?-?\s?6\b"),
    ("Q5",         "Audi", "Q5",  r"\bq\s?-?\s?5\b"),
    ("Q7",         "Audi", "Q7",  r"\bq\s?-?\s?7\b"),
    ("Q8 e-tron",  "Audi", "Q8 e-tron", r"\bq\s?-?\s?8\s?e-?tron\b"),
    # ---- §2-2 B 일본 ----
    # IS·ES 는 영어 단어(is/es)와 겹친다 → 숫자 동반만 인정 (사양 명시)
    ("NX350",      "Lexus", "NX350", r"\bnx\s?-?\s?350\b"),
    ("RX",         "Lexus", "RX",    r"\brx\s?-?\s?(?:350h?|450h|500h)?\b"),
    ("ES",         "Lexus", "ES",    r"\bes\s?-?\s?(?:250|300h?|330|350)\b"),
    ("IS",         "Lexus", "IS",    r"\bis\s?-?\s?(?:200t?|250|300|350|500)\b"),
    ("RDX",        "Acura", "RDX",   r"\brdx\b"),
    ("MDX",        "Acura", "MDX",   r"\bmdx\b"),
    ("TLX",        "Acura", "TLX",   r"\btlx\b"),
    ("QX60",       "Infiniti", "QX60", r"\bqx\s?-?\s?60\b"),
    # ---- §2-2 B 미국 ----
    ("Escalade",   "Cadillac", "Escalade", r"\bescalade\b"),
    ("XT5",        "Cadillac", "XT5",      r"\bxt\s?-?\s?5\b"),
    ("Lyriq",      "Cadillac", "Lyriq",    r"\blyriq\b"),
    ("Navigator",  "Lincoln", "Navigator", r"\bnavigator\b"),
    ("Aviator",    "Lincoln", "Aviator",   r"\baviator\b"),
    ("Nautilus",   "Lincoln", "Nautilus",  r"\bnautilus\b"),
    # ---- §2-2 B EV ----
    ("Model 3",    "Tesla", "Model 3", r"\bmodel\s?-?\s?3\b"),
    ("Model Y",    "Tesla", "Model Y", r"\bmodel\s?-?\s?y\b"),
    ("Model S",    "Tesla", "Model S", r"\bmodel\s?-?\s?s\b"),
    ("Polestar 2", "Polestar", "Polestar 2", r"\bpolestar\s?-?\s?2\b"),
    ("R1S",        "Rivian", "R1S", r"\br1s\b"),
    # ---- §2-2 B 기타 ----
    ("XC60",       "Volvo", "XC60", r"\bxc\s?-?\s?60\b"),
    ("XC90",       "Volvo", "XC90", r"\bxc\s?-?\s?90\b"),
    ("EX90",       "Volvo", "EX90", r"\bex\s?-?\s?90\b"),
]

# (brand, pattern) — §1 브랜드 단독 + §2-2 제조사
BRANDS = [
    ("Genesis",  r"\bgenesis\b"),
    ("Hyundai",  r"\bhyundai\b"),
    ("Kia",      r"\bkia\b"),
    ("BMW",      r"\bbmw\b"),
    ("Mercedes", r"(?:\bmercedes\b|\bbenz\b|\bmerc\b)"),
    ("Audi",     r"\baudi\b"),
    ("Lexus",    r"\blexus\b"),
    ("Acura",    r"\bacura\b"),
    ("Infiniti", r"\binfiniti\b"),
    ("Cadillac", r"(?:\bcadillac\b|\bcaddy\b)"),
    ("Lincoln",  r"\blincoln\b"),
    ("Tesla",    r"\btesla\b"),
    ("Polestar", r"\bpolestar\b"),
    ("Rivian",   r"\brivian\b"),
    ("Volvo",    r"\bvolvo\b"),
    ("Toyota",   r"\btoyota\b"),
]

# 사전 v2 후보 — 점수에 쓰지 않는다. manifest 진단용으로만 센다.
# §2-2 US 목록에 없으나 G90·G80 담론에서 상대로 등장할 법한 차명.
V2_PROBE = [
    ("S-Class",  r"\bs[-\s]?class\b"),
    ("7 Series", r"\b7\s?-?\s?series\b"),
    ("i7",       r"\bi\s?-?\s?7\b"),
    ("A8",       r"\ba\s?-?\s?8\b"),
    ("LS 500",   r"\bls\s?-?\s?500h?\b"),
    ("EQS",      r"\beqs\b"),
    ("X7",       r"\bx\s?-?\s?7\b"),
    ("GLS",      r"\bgls\b"),
    ("Model X",  r"\bmodel\s?-?\s?x\b"),
    ("Continental", r"\bcontinental\b"),
]
