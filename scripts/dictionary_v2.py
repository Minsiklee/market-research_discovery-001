# -*- coding: utf-8 -*-
"""키워드 사전 v2 — keyword_dictionary_v1 §1·§2-2(US) + 1차 배치 역도출분.

사전 §0-3: 경쟁 세트는 상식이 아니라 담론에서 역도출한다(P5).
v2 신규 항목은 전부 scripts/mine_candidates.py 로 말뭉치에서 캐낸 뒤
스레드 빈도를 붙여 채택했다. obs= 는 1차 배치(reddit US 367스레드)의 관측 스레드 수다.
관측 0인 후보는 넣지 않고 PROBE 에 남겨 다음 배치에서 다시 잰다.

v1 대비 규칙 변경 셋
  1. 한 글자 + 숫자 코드(A4·X3·i5·Q5·K5)는 공백을 허용하지 않는다.
     "a 4 door" 같은 영어 구가 Audi A4 로 잡혔다(5 → 1).
  2. 렉서스 ES·IS 는 숫자 동반에 더해 "대문자 ES/IS + Lexus 근접"을 인정한다.
     맨 소문자 es/is 는 197스레드로 거의 전부 영어 단어다. 대소문자를 살려야 갈린다.
  3. 구분자가 전부 선택적인 패턴은 붙여쓴 단어에 걸린다. v1 의 Model S
     (\bmodel\s?-?\s?s\b)는 복수형 "models" 를 그대로 잡아 30스레드로 부풀었다
     — 테슬라 동반은 5건뿐이었고 앞 토큰은 "12·specific·2026·ten" 이었다.
     구분자를 강제해 2스레드(둘 다 테슬라 동반)로 바로잡았다.
     같은 꼴인 LS·RX·NX·iX 는 점검 결과 브랜드 동반 100%로 문제 없었다.
  4. 뜻이 겹치는 토큰은 브랜드 동반을 요구한다. 이 말뭉치에서
     charger 는 EV 충전기, golf 는 골프, pilot 은 오토파일럿, air 는 공기,
     crown·atlas·blazer·explorer 는 일반명사로 먼저 읽힌다.
"""
from collections import namedtuple

M = namedtuple("M", "code marque canonical pattern cs obs")
B = namedtuple("B", "brand pattern obs")


def m(code, marque, canonical, pattern, cs=False, obs=None):
    return M(code, marque, canonical, pattern, cs, obs)


MODELS = [
    # ================= §1 제네시스 모델 · 파워트레인 변형 (v1 유지) =================
    m("eG80",       "Genesis", "G80",  r"(?:electrified\s+g[-\s]?80|\beg80\b|\bg[-\s]?80\s+(?:ev|electric)\b)"),
    m("eGV70",      "Genesis", "GV70", r"(?:electrified\s+gv[-\s]?70|\begv70\b|\bgv70e\b|\bgv[-\s]?70\s+(?:ev|electric)\b)"),
    m("GV70 EREV",  "Genesis", "GV70", r"(?:\bgv[-\s]?70\s+erev\b|\bgv[-\s]?70\s+range\s+extender\b|extended[-\s]range\s+gv[-\s]?70)"),
    m("GV70 HEV",   "Genesis", "GV70", r"(?:\bgv[-\s]?70\s+hybrid\b|\bgenesis\s+hybrid\b|\brwd\s+hybrid\b)"),
    m("GV80 Coupe", "Genesis", "GV80", r"(?:\bgv[-\s]?80\s?coupe\b|\bgv[-\s]?80c\b)"),
    m("G70",        "Genesis", "G70",  r"\bg[-\s]?70\b"),
    m("G80",        "Genesis", "G80",  r"\bg[-\s]?80\b"),
    m("G90",        "Genesis", "G90",  r"\bg[-\s]?90\b"),
    m("GV60",       "Genesis", "GV60", r"\bgv[-\s]?60\b"),
    m("GV70",       "Genesis", "GV70", r"\bgv[-\s]?70\b"),
    m("GV80",       "Genesis", "GV80", r"\bgv[-\s]?80\b"),
    m("GV90",       "Genesis", "GV90", r"(?:\bgv[-\s]?90\b|\bneolun\b)"),
    # v1 §1 GV60 행의 "마그마 [가설]" → 1차 배치에서 [관측]. 모델이 아니라 변형이므로 canonical 은 GV60.
    m("Magma",      "Genesis", "GV60", r"\bmagma\b", obs=44),

    # ================= §2-2 US · I-H 현대기아 (v1 유지 + 역도출 추가) =================
    m("Palisade",   "Hyundai", "Palisade", r"\bpalisade\b"),
    m("Santa Fe",   "Hyundai", "Santa Fe", r"\bsanta\s?fe\b"),
    m("Ioniq 5 N",  "Hyundai", "Ioniq 5",  r"\bioniq\s?-?\s?5\s?n\b"),
    m("Ioniq 5",    "Hyundai", "Ioniq 5",  r"\bioniq\s?-?\s?5\b"),
    m("Ioniq 6",    "Hyundai", "Ioniq 6",  r"\bioniq\s?-?\s?6\b"),
    m("Sonata",     "Hyundai", "Sonata",   r"\bsonata\b",  obs=12),
    m("Tucson",     "Hyundai", "Tucson",   r"\btucson\b",  obs=9),
    m("Elantra",    "Hyundai", "Elantra",  r"\belantra\b", obs=6),
    m("Kona",       "Hyundai", "Kona",     r"\bkona\b",    obs=4),
    m("Azera/Equus", "Hyundai", "Azera/Equus", r"\b(?:azera|equus)\b", obs=4),
    m("Telluride",  "Kia", "Telluride", r"\btelluride\b"),
    m("Sportage",   "Kia", "Sportage",  r"\bsportage\b"),
    m("Seltos",     "Kia", "Seltos",    r"\bseltos\b"),
    m("EV6",        "Kia", "EV6",       r"\bev\s?-?\s?6\b"),
    m("EV9",        "Kia", "EV9",       r"\bev\s?-?\s?9\b"),
    m("Stinger",    "Kia", "Stinger",   r"\bstinger\b"),
    m("K5",         "Kia", "K5",        r"\bk-?5\b",       obs=6),
    m("K900",       "Kia", "K900",      r"\bk-?900\b",     obs=2),
    m("Carnival",   "Kia", "Carnival",  r"\bcarnival\b",   obs=7),
    m("Niro",       "Kia", "Niro",      r"\bniro\b",       obs=5),

    # ================= §2-2 B 독일 (v1 유지 + 역도출 추가) =================
    m("M340i",     "BMW", "M340i",    r"\bm340i\b"),
    m("3 Series",  "BMW", "3 Series", r"\b3\s?-?\s?series\b"),
    m("5 Series",  "BMW", "5 Series", r"\b5\s?-?\s?series\b"),
    m("7 Series",  "BMW", "7 Series", r"\b7\s?-?\s?series\b", obs=17),
    m("X3",        "BMW", "X3",  r"\bx-?3\b"),
    m("X5",        "BMW", "X5",  r"\bx-?5\b"),
    m("X7",        "BMW", "X7",  r"\bx-?7\b", obs=2),
    m("X1",        "BMW", "X1",  r"\bx-?1\b", obs=2),
    m("i4",        "BMW", "i4",  r"\bi-?4\b"),
    m("i5",        "BMW", "i5",  r"\bi-?5\b"),
    m("i7",        "BMW", "i7",  r"\bi-?7\b", obs=4),
    m("iX",        "BMW", "iX",  r"\bix\b"),
    m("M5",        "BMW", "M5",  r"\bm5\b", obs=6),
    m("5시리즈 트림", "BMW", "5 Series", r"\b(?:530i|540i|550i|m550i)\b", obs=12),
    m("3시리즈 트림", "BMW", "3 Series", r"\b(?:320i|328i|330i|335i)\b", obs=4),
    m("C300",      "Mercedes", "C300",    r"\bc-?300\b"),
    m("E-Class",   "Mercedes", "E-Class", r"\be[-\s]?class\b"),
    m("E-Class 트림", "Mercedes", "E-Class", r"\be-?(?:350|450|53|63)\b", obs=9),
    m("S-Class",   "Mercedes", "S-Class", r"\bs[-\s]?class\b", obs=21),
    m("S-Class 트림", "Mercedes", "S-Class", r"\bs-?(?:500|550|580|63)\b", obs=5),
    m("CLS",       "Mercedes", "CLS", r"\bcls\b", obs=4),
    m("GLC",       "Mercedes", "GLC", r"\bglc\b"),
    m("GLE",       "Mercedes", "GLE", r"\bgle\b"),
    m("GLS",       "Mercedes", "GLS", r"\bgls\b", obs=2),
    m("EQE",       "Mercedes", "EQE", r"\beqe\b"),
    m("EQS",       "Mercedes", "EQS", r"\beqs\b", obs=6),
    m("EQB/EQC",   "Mercedes", "EQB/EQC", r"\beq[bc]\b", obs=7),
    m("A4",        "Audi", "A4", r"\ba-?4\b", obs=14),
    m("A6",        "Audi", "A6", r"\ba-?6\b"),
    m("A7",        "Audi", "A7", r"\ba-?7\b", obs=12),
    m("A8",        "Audi", "A8", r"\ba-?8\b", obs=10),
    m("Q5",        "Audi", "Q5", r"\bq-?5\b"),
    m("Q7",        "Audi", "Q7", r"\bq-?7\b"),
    m("Q8",        "Audi", "Q8", r"\bq-?8\b", obs=3),
    m("Q8 e-tron", "Audi", "Q8 e-tron", r"\bq-?8\s?e-?tron\b"),
    m("e-tron",    "Audi", "e-tron", r"\be-?tron\b", obs=6),

    # ================= §2-2 B 일본 (v1 유지 + 역도출 추가) =================
    m("NX350",  "Lexus", "NX", r"\bnx\s?-?\s?350\b"),
    m("NX",     "Lexus", "NX", r"\bnx\b", obs=6),
    m("RX",     "Lexus", "RX", r"\brx\s?-?\s?(?:350h?|450h|500h)?\b"),
    m("LS",     "Lexus", "LS", r"\bls\s?-?\s?(?:400|430|460|500h?)?\b", obs=19),
    m("GS",     "Lexus", "GS", r"\bgs\s?-?\s?(?:300|350|450h?|f)\b", obs=3),
    # ES·IS: 숫자 동반(v1) 또는 대문자 + Lexus 근접(v2). 맨 소문자는 영어 단어다(197스레드).
    m("ES",     "Lexus", "ES", r"\bes\s?-?\s?(?:250|300h?|330|350)\b"),
    m("IS",     "Lexus", "IS", r"\bis\s?-?\s?(?:200t?|250|300|350|500)\b"),
    m("ES(대문자)", "Lexus", "ES",
      r"(?:Lexus[^.?!]{0,60}\bES\b|\bES\b[^.?!]{0,60}Lexus)", cs=True, obs=4),
    m("IS(대문자)", "Lexus", "IS",
      r"(?:Lexus[^.?!]{0,60}\bIS\b|\bIS\b[^.?!]{0,60}Lexus)", cs=True, obs=4),
    m("RDX",  "Acura", "RDX", r"\brdx\b"),
    m("MDX",  "Acura", "MDX", r"\bmdx\b"),
    m("TLX",  "Acura", "TLX", r"\btlx\b"),
    m("Integra", "Acura", "Integra", r"\bintegra\b", obs=2),
    m("QX60",   "Infiniti", "QX60", r"\bqx\s?-?\s?60\b"),
    m("Q50/Q60", "Infiniti", "Q50/Q60", r"\bq-?[56]0\b", obs=5),
    m("Accord", "Honda", "Accord", r"\baccord\b", obs=13),
    m("Civic",  "Honda", "Civic",  r"\bcivic\b",  obs=13),
    m("CR-V",   "Honda", "CR-V",   r"\bcr-?v\b",  obs=2),
    m("Pilot",  "Honda", "Pilot",  r"\bhonda\s+pilot\b|\bpilot\s+(?:trim|touring|elite)\b", obs=12),
    m("Camry",  "Toyota", "Camry",  r"\bcamry\b",  obs=13),
    m("Corolla", "Toyota", "Corolla", r"\bcorolla\b", obs=8),
    m("RAV4",   "Toyota", "RAV4",   r"\brav\s?-?\s?4\b", obs=5),
    m("Crown",  "Toyota", "Crown",  r"\btoyota\s+crown\b|\bcrown\s+signia\b", obs=4),
    m("Highlander", "Toyota", "Highlander", r"\bhighlander\b", obs=2),
    m("Sienna", "Toyota", "Sienna", r"\bsienna\b", obs=2),
    m("Supra",  "Toyota", "Supra",  r"\bsupra\b",  obs=2),
    m("Altima/Maxima", "Nissan", "Altima/Maxima", r"\b(?:altima|maxima)\b", obs=7),
    m("CX-5/50/90", "Mazda", "CX", r"\bcx-?(?:5|50|70|90)\b", obs=8),
    m("Mazda3/6",   "Mazda", "Mazda3/6", r"\bmazda-?[36]\b", obs=4),

    # ================= §2-2 B 미국 (v1 유지 + 역도출 추가) =================
    m("Escalade",  "Cadillac", "Escalade", r"\bescalade\b"),
    m("XT5",       "Cadillac", "XT5",   r"\bxt-?5\b"),
    m("CT5",       "Cadillac", "CT5",   r"\bct-?5\b", obs=11),
    m("CT4/CT6",   "Cadillac", "CT4/CT6", r"\bct-?[46]\b", obs=6),
    m("Lyriq",     "Cadillac", "Lyriq", r"\blyriq\b"),
    m("Navigator", "Lincoln", "Navigator", r"\bnavigator\b"),
    m("Aviator",   "Lincoln", "Aviator",   r"\baviator\b"),
    m("Nautilus",  "Lincoln", "Nautilus",  r"\bnautilus\b"),
    # Continental: Bentley Continental GT 와 갈린다. GT·bentley 동반은 Bentley 쪽으로 보낸다.
    m("Continental", "Lincoln", "Continental",
      r"\bcontinental\b(?!\s*gt)(?<!bentley continental)", obs=9),
    m("Continental GT", "Bentley", "Continental GT",
      r"\bcontinental\s?gt\b|\bbentley\s+continental\b"),
    m("Corvette", "Chevrolet", "Corvette", r"\bcorvette\b", obs=9),
    m("Camaro",   "Chevrolet", "Camaro",   r"\bcamaro\b",   obs=6),
    m("Blazer",   "Chevrolet", "Blazer",   r"\b(?:chevy|chevrolet)\s+blazer\b|\bblazer\s+ev\b"),
    m("Mustang",  "Ford", "Mustang",  r"\bmustang\b",  obs=11),
    m("F-150",    "Ford", "F-150",    r"\bf-?150\b",  obs=7),
    # Charger: 이 말뭉치에서 charger 는 EV 충전기다. 브랜드 동반을 요구한다.
    m("Charger",     "Dodge", "Charger",     r"\bdodge\s+charger\b|\bcharger\s+(?:rt|scat|hellcat|daytona)\b"),
    m("Challenger",  "Dodge", "Challenger",  r"\bdodge\s+challenger\b|\bchallenger\s+(?:rt|scat|hellcat)\b"),

    # ================= §2-2 B EV (v1 유지 + 역도출 추가) =================
    m("Model 3",  "Tesla", "Model 3", r"\bmodel[\s-]*3\b"),
    m("Model Y",  "Tesla", "Model Y", r"\bmodel[\s-]*y\b"),
    m("Model S",  "Tesla", "Model S", r"\bmodel[\s-]+s\b", obs=2),
    m("Model X",  "Tesla", "Model X", r"\bmodel[\s-]*x\b", obs=2),
    m("Polestar 2",   "Polestar", "Polestar 2", r"\bpolestar\s?-?\s?2\b"),
    m("Polestar 3/4", "Polestar", "Polestar 3/4", r"\bpolestar\s?-?\s?[34]\b", obs=2),
    m("R1S",      "Rivian", "R1S", r"\br1s\b"),
    m("Lucid Air", "Lucid", "Lucid Air", r"\blucid\s+(?:air|gravity)\b|\blucid\b", obs=10),

    # ================= §2-2 B 기타 (v1 유지 + 역도출 추가) =================
    m("XC60", "Volvo", "XC60", r"\bxc-?60\b"),
    m("XC90", "Volvo", "XC90", r"\bxc-?90\b"),
    m("EX90", "Volvo", "EX90", r"\bex-?90\b"),
    m("S60/S90", "Volvo", "S60/S90", r"\bs-?[69]0\b", obs=4),
    m("XC40", "Volvo", "XC40", r"\bxc-?40\b"),
    m("Macan",    "Porsche", "Macan",    r"\bmacan\b",    obs=8),
    m("Cayenne",  "Porsche", "Cayenne",  r"\bcayenne\b",  obs=8),
    m("Panamera", "Porsche", "Panamera", r"\bpanamera\b", obs=8),
    m("Taycan",   "Porsche", "Taycan",   r"\btaycan\b",   obs=5),
    m("911",      "Porsche", "911",      r"\bporsche[^.?!]{0,40}911\b|\b911\s?(?:carrera|turbo|gt3|gts)\b", obs=3),
    m("Range Rover", "Land Rover", "Range Rover", r"\brange\s?rover\b", obs=7),
    m("F-Pace",      "Jaguar", "F-Pace", r"\bf-?pace\b"),
    # Golf: 이 말뭉치에서 golf 는 골프다(사전 §3 장면 해시태그 #골프). 브랜드·GTI 동반만.
    m("Golf/GTI", "Volkswagen", "Golf", r"\b(?:vw|volkswagen)\s+golf\b|\bgolf\s?(?:gti|r)\b|\bgti\b", obs=12),
    m("Arteon",   "Volkswagen", "Arteon", r"\barteon\b", obs=4),
    m("Atlas",    "Volkswagen", "Atlas",  r"\b(?:vw|volkswagen)\s+atlas\b|\batlas\s+cross\s?sport\b"),
]

BRANDS = [
    B("Genesis",  r"\bgenesis\b", None),
    B("Hyundai",  r"\bhyundai\b", None),
    B("Kia",      r"\bkia\b", None),
    B("BMW",      r"\bbmw\b", None),
    B("Mercedes", r"(?:\bmercedes\b|\bbenz\b|\bmerc\b|\bamg\b)", 12),
    B("Audi",     r"\baudi\b", None),
    B("Lexus",    r"\blexus\b", None),
    B("Acura",    r"\bacura\b", None),
    B("Infiniti", r"\binfiniti\b", None),
    B("Cadillac", r"(?:\bcadillac\b|\bcaddy\b)", None),
    B("Lincoln",  r"\blincoln\b", None),
    B("Tesla",    r"\btesla\b", None),
    B("Polestar", r"\bpolestar\b", None),
    B("Rivian",   r"\brivian\b", None),
    B("Volvo",    r"\bvolvo\b", None),
    B("Toyota",   r"\btoyota\b", None),
    # --- v2 역도출 신규 브랜드 ---
    B("Honda",       r"\bhonda\b",       26),
    B("Porsche",     r"\bporsche\b",     25),
    B("Ford",        r"\bford\b",        20),
    B("Nissan",      r"\bnissan\b",      13),
    B("Mazda",       r"\bmazda\b",       13),
    B("Volkswagen",  r"\b(?:volkswagen|vw)\b", 14),
    B("Bentley",     r"\bbentley\b",     12),
    B("Chevrolet",   r"\b(?:chevrolet|chevy)\b", 8),
    B("Lucid",       r"\blucid\b",       10),
    B("Jaguar",      r"\bjaguar\b",      11),
    B("Land Rover",  r"\b(?:land\s?rover|range\s?rover)\b", 7),
    B("Maserati",    r"\bmaserati\b",    6),
    B("Dodge",       r"\bdodge\b",       None),
]

# 1차 배치 관측 0 — 채택하지 않고 다음 배치에서 다시 잰다.
PROBE = [
    ("Lincoln Corsair", r"\bcorsair\b"),
    ("Ioniq 9",         r"\bioniq\s?-?\s?9\b"),
    ("VW ID.4",         r"\bid\.?\s?4\b"),
    ("Genesis X Gran",  r"\bx\s?gran\b"),
    ("Rivian R1T",      r"\br1t\b"),
    ("Cadillac Celestiq", r"\bcelestiq\b"),
    ("Ford Explorer",   r"\bexplorer\b"),
]
