#!/usr/bin/env python3
"""Generate 9 SVG diagrams for S3 Data Sharing Services post.
Follows BLOG_GOVERNANCE.md section 3.5 SVG rules."""

import os

OUT = os.path.join(os.path.dirname(__file__), "s3-data-sharing-services")
os.makedirs(OUT, exist_ok=True)

FONT = "'Segoe UI','Noto Sans KR',system-ui,sans-serif"

# Colors from governance 3.5.2
C_CLIENT_FILL = "#dbeafe"
C_CLIENT_STROKE = "#2563eb"
C_CLIENT_TEXT = "#2563eb"
C_SERVER_FILL = "#dcfce7"
C_SERVER_STROKE = "#16a34a"
C_SERVER_TEXT = "#16a34a"
C_NEUTRAL_FILL = "#f0f4f8"
C_NEUTRAL_STROKE = "#666666"
C_NEUTRAL_TEXT = "#666666"
C_WARN_FILL = "#fef2f2"
C_WARN_STROKE = "#dc2626"
C_WARN_TEXT = "#dc2626"
C_INFO_FILL = "#fef3c7"
C_INFO_STROKE = "#fbbf24"
C_INFO_TEXT = "#92400e"
C_BG_BLUE = "#eff6ff"
C_BG_GREEN = "#f0fdf4"
C_BODY = "#2c3e50"
C_SUBTLE = "#8b949e"

def box(x, y, w, h, text, sub=None, fill=C_NEUTRAL_FILL, stroke=C_NEUTRAL_STROKE,
        text_color=None, rx=10, font_size=13, sub_size=10):
    tc = text_color or stroke
    lines = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" stroke="{stroke}" stroke-width="2"/>']
    ty = y + h // 2 - (5 if sub else 0)
    lines.append(f'<text x="{x+w//2}" y="{ty}" font-size="{font_size}" font-weight="700" fill="{tc}" text-anchor="middle">{text}</text>')
    if sub:
        lines.append(f'<text x="{x+w//2}" y="{ty+16}" font-size="{sub_size}" fill="{C_SUBTLE}" text-anchor="middle">{sub}</text>')
    return "\n".join(lines)

def arrow_h(x1, x2, y, color="#666", label=None, label_above=True, sw=1.5):
    lines = [f'<line x1="{x1}" y1="{y}" x2="{x2}" y2="{y}" stroke="{color}" stroke-width="{sw}" marker-end="url(#ah-{color.lstrip("#")})"/>']
    if label:
        ly = y - 7 if label_above else y + 14
        lines.append(f'<text x="{(x1+x2)//2}" y="{ly}" font-size="10" fill="{color}" text-anchor="middle">{label}</text>')
    return "\n".join(lines)

def arrow_v(x, y1, y2, color="#666", label=None, sw=1.5):
    lines = [f'<line x1="{x}" y1="{y1}" x2="{x}" y2="{y2}" stroke="{color}" stroke-width="{sw}" marker-end="url(#ah-{color.lstrip("#")})"/>']
    if label:
        lx = x + 10
        ly = (y1+y2)//2
        lines.append(f'<text x="{lx}" y="{ly}" font-size="10" fill="{color}" text-anchor="start">{label}</text>')
    return "\n".join(lines)

def markers(colors):
    defs = []
    for c in colors:
        cid = "ah-" + c.lstrip("#")
        defs.append(f'<marker id="{cid}" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L0,6 L9,3 z" fill="{c}"/></marker>')
    return "\n".join(defs)

def wrap_svg(w, h, content, extra_defs=""):
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" font-family="{FONT}">
  <defs>
{extra_defs}
  </defs>
{content}
</svg>'''


# ============================================================
# 01: Registry of Open Data Architecture
# ============================================================
def svg_01():
    defs = markers(["#666", "#2563eb", "#16a34a"])
    c = []
    # Title
    c.append(f'<text x="410" y="28" font-size="15" font-weight="700" fill="{C_BODY}" text-anchor="middle">Registry of Open Data: 데이터 흐름</text>')

    # Top: data providers
    providers = [("NASA Landsat", 80), ("NOAA Weather", 330), ("Common Crawl", 580)]
    for name, x in providers:
        c.append(box(x, 50, 160, 50, name, fill=C_CLIENT_FILL, stroke=C_CLIENT_STROKE, font_size=11))

    # Arrows down to S3
    for _, x in providers:
        c.append(f'<line x1="{x+80}" y1="100" x2="{x+80}" y2="140" stroke="#666" stroke-width="1.5" marker-end="url(#ah-666)"/>')

    # S3 public buckets
    c.append(box(80, 145, 660, 70, "Amazon S3 (공개 버킷)", sub="s3://sentinel-s2-l1c/  ·  s3://landsat-pds/  ·  s3://commoncrawl/", fill=C_SERVER_FILL, stroke=C_SERVER_STROKE, font_size=13, sub_size=10))

    # Arrows down to consumers
    for _, x in providers:
        c.append(f'<line x1="{x+80}" y1="215" x2="{x+80}" y2="255" stroke="#666" stroke-width="1.5" marker-end="url(#ah-666)"/>')

    # Bottom: consumers
    consumers = [("연구자", 80), ("기업", 330), ("개발자", 580)]
    for name, x in consumers:
        c.append(box(x, 260, 160, 45, name, fill=C_NEUTRAL_FILL, stroke=C_NEUTRAL_STROKE, font_size=11))

    # Note
    c.append(f'<text x="410" y="330" font-size="10" fill="{C_SUBTLE}" text-anchor="middle" font-style="italic">인증 불필요 (--no-sign-request), 400+ 데이터셋, 무료 접근</text>')

    return wrap_svg(820, 345, "\n".join(c), defs)

# ============================================================
# 02: Traditional Copy vs Data Exchange In-place
# ============================================================
def svg_02():
    defs = markers(["#dc2626", "#16a34a"])
    c = []
    c.append(f'<text x="410" y="28" font-size="15" font-weight="700" fill="{C_BODY}" text-anchor="middle">전통적 복사 vs Data Exchange 직접 접근</text>')

    # Top: Traditional (red)
    c.append(box(30, 55, 150, 50, "제공자 S3", fill=C_WARN_FILL, stroke=C_WARN_STROKE, font_size=12))
    c.append(arrow_h(180, 290, 80, "#dc2626", "복사"))
    c.append(box(290, 55, 150, 50, "구독자 S3", fill=C_WARN_FILL, stroke=C_WARN_STROKE, font_size=12))
    c.append(arrow_h(440, 550, 80, "#dc2626", "분석"))
    c.append(box(550, 55, 180, 50, "분석 환경", fill=C_WARN_FILL, stroke=C_WARN_STROKE, font_size=12))
    c.append(f'<text x="745" y="83" font-size="11" fill="{C_WARN_TEXT}" font-weight="600">❌ 중복·비용·동기화</text>')

    # Bottom: Data Exchange (green)
    c.append(box(30, 140, 150, 50, "제공자 S3", fill=C_SERVER_FILL, stroke=C_SERVER_STROKE, font_size=12))
    c.append(arrow_h(180, 550, 165, "#16a34a", "직접 접근 (In-place)"))
    c.append(box(550, 140, 180, 50, "구독자 분석 환경", fill=C_SERVER_FILL, stroke=C_SERVER_STROKE, font_size=12))
    c.append(f'<text x="745" y="168" font-size="11" fill="{C_SERVER_TEXT}" font-weight="600">✅ 복사 없음·최신 데이터</text>')

    return wrap_svg(820, 210, "\n".join(c), defs)

# ============================================================
# 03: Data Exchange Working Flow
# ============================================================
def svg_03():
    defs = markers(["#666", "#2563eb"])
    c = []
    c.append(f'<text x="410" y="28" font-size="15" font-weight="700" fill="{C_BODY}" text-anchor="middle">AWS Data Exchange: 작동 흐름</text>')

    # Left: Provider
    c.append(box(20, 55, 180, 100, "데이터 제공자", sub="S3 버킷\ndataset/\ndata.parquet", fill=C_CLIENT_FILL, stroke=C_CLIENT_STROKE, font_size=12, sub_size=9))

    # Center: Data Exchange
    c.append(box(260, 50, 280, 110, "AWS Data Exchange", sub="구독 관리 · 라이선스 · 결제 · 권한", fill=C_INFO_FILL, stroke=C_INFO_STROKE, text_color=C_INFO_TEXT, font_size=13, sub_size=10))

    # Right: Subscriber
    c.append(box(600, 55, 180, 100, "데이터 구독자", sub="Athena · EMR\nSageMaker", fill=C_SERVER_FILL, stroke=C_SERVER_STROKE, font_size=12, sub_size=9))

    # Arrows
    c.append(arrow_h(200, 255, 80, "#666"))
    c.append(arrow_h(540, 595, 80, "#666"))
    c.append(arrow_h(595, 540, 110, "#666"))
    c.append(arrow_h(255, 200, 110, "#666"))

    # Bottom: Marketplace
    c.append(arrow_v(400, 160, 195, "#fbbf24"))
    c.append(box(260, 200, 280, 55, "AWS Marketplace", sub="3,500+ 데이터셋 카탈로그", fill=C_INFO_FILL, stroke=C_INFO_STROKE, text_color=C_INFO_TEXT, font_size=12, sub_size=10))

    return wrap_svg(820, 275, "\n".join(c), defs)

# ============================================================
# 04: Subscription Lifecycle
# ============================================================
def svg_04():
    defs = markers(["#2563eb", "#16a34a"])
    c = []
    c.append(f'<text x="410" y="28" font-size="15" font-weight="700" fill="{C_BODY}" text-anchor="middle">구독 라이프사이클</text>')

    steps = [
        ("1. 검색", "Marketplace", C_CLIENT_FILL, C_CLIENT_STROKE),
        ("2. 구독 신청", "요금제 선택", C_CLIENT_FILL, C_CLIENT_STROKE),
        ("3. 승인 대기", "제공자 승인", C_INFO_FILL, C_INFO_STROKE),
        ("4. 접근 활성", "S3 API 접근", C_SERVER_FILL, C_SERVER_STROKE),
        ("5. 갱신/만료", "자동 권한 회수", C_NEUTRAL_FILL, C_NEUTRAL_STROKE),
    ]

    bw = 140
    gap = 25
    total = len(steps) * bw + (len(steps)-1) * gap
    start_x = (820 - total) // 2

    for i, (title, sub, fill, stroke) in enumerate(steps):
        x = start_x + i * (bw + gap)
        c.append(box(x, 55, bw, 60, title, sub=sub, fill=fill, stroke=stroke, font_size=11, sub_size=9))
        if i < len(steps) - 1:
            ax1 = x + bw
            ax2 = ax1 + gap
            c.append(arrow_h(ax1, ax2, 85, "#666"))

    c.append(f'<text x="410" y="145" font-size="10" fill="{C_SUBTLE}" text-anchor="middle" font-style="italic">구독 → 승인 → 접근 → 갱신/만료의 전 주기 관리</text>')

    return wrap_svg(820, 160, "\n".join(c), defs)

# ============================================================
# 05: Why Access Points (Before/After)
# ============================================================
def svg_05():
    defs = markers(["#dc2626", "#16a34a"])
    c = []
    c.append(f'<text x="410" y="28" font-size="15" font-weight="700" fill="{C_BODY}" text-anchor="middle">왜 Access Points가 필요한가?</text>')

    # Left: Before (bloated policy)
    c.append(f'<text x="195" y="55" font-size="12" font-weight="700" fill="{C_WARN_TEXT}" text-anchor="middle">기존: 단일 버킷 정책</text>')
    policy_lines = [
        "IF 사용자 == TeamA → /team-a/",
        "IF 사용자 == TeamB → /team-b/",
        "IF 사용자 == Public → /public/",
        "IF VPC == prod → 쓰기 허용",
        "... (규칙 계속 증가)",
    ]
    py = 65
    for i, line in enumerate(policy_lines):
        c.append(f'<rect x="20" y="{py}" width="350" height="22" rx="4" fill="{C_WARN_FILL}" stroke="{C_WARN_STROKE}" stroke-width="1" opacity="{0.9 - i*0.1}"/>')
        c.append(f'<text x="35" y="{py+15}" font-size="9" fill="{C_WARN_TEXT}">{line}</text>')
        py += 26
    c.append(f'<text x="195" y="{py+15}" font-size="11" fill="{C_WARN_TEXT}" font-weight="600" text-anchor="middle">❌ 관리 어려움, 실수 위험</text>')

    # Arrow
    c.append(f'<text x="410" y="120" font-size="20" fill="{C_SERVER_TEXT}" text-anchor="middle">→</text>')
    c.append(f'<text x="410" y="140" font-size="10" fill="{C_SERVER_TEXT}" text-anchor="middle" font-weight="600">개선</text>')

    # Right: After (AP policies)
    c.append(f'<text x="615" y="55" font-size="12" font-weight="700" fill="{C_SERVER_TEXT}" text-anchor="middle">Access Points: 정책 분산</text>')
    aps = [("AP 정책 A", "TeamA용"), ("AP 정책 B", "TeamB용"), ("AP 정책 C", "Public용")]
    for i, (title, sub) in enumerate(aps):
        ay = 65 + i * 80
        c.append(box(450, ay, 160, 65, title, sub=f"{sub}\n깔끔! ✅", fill=C_SERVER_FILL, stroke=C_SERVER_STROKE, font_size=12, sub_size=9))

    return wrap_svg(820, 320, "\n".join(c), defs)

# ============================================================
# 06: Access Points Architecture
# ============================================================
def svg_06():
    defs = markers(["#666", "#2563eb", "#16a34a"])
    c = []
    c.append(f'<text x="410" y="28" font-size="15" font-weight="700" fill="{C_BODY}" text-anchor="middle">S3 Access Points 아키텍처</text>')

    # Top: S3 Bucket
    c.append(box(180, 50, 460, 55, "S3 버킷: shared-data", sub="/team-a/  ·  /team-b/  ·  /public/", fill=C_SERVER_FILL, stroke=C_SERVER_STROKE, font_size=13, sub_size=10))

    # Arrows down
    xs = [260, 410, 560]
    labels = ["/team-a/", "/team-b/", "/public/"]
    for x, label in zip(xs, labels):
        c.append(f'<line x1="{x}" y1="105" x2="{x}" y2="145" stroke="#666" stroke-width="1.5" marker-end="url(#ah-666)"/>')
        c.append(f'<text x="{x+10}" y="128" font-size="9" fill="{C_SUBTLE}">{label}</text>')

    # Middle: Access Points
    ap_data = [
        (260, "team-a-ap", "권한: 읽기/쓰기\nVPC: vpc-a", C_CLIENT_FILL, C_CLIENT_STROKE),
        (410, "team-b-ap", "권한: 읽기만\nVPC: vpc-b", C_CLIENT_FILL, C_CLIENT_STROKE),
        (560, "public-ap", "권한: 공개 읽기\nVPC: 제한없음", C_NEUTRAL_FILL, C_NEUTRAL_STROKE),
    ]
    for x, name, perm, fill, stroke in ap_data:
        c.append(box(x-75, 150, 150, 60, name, sub=perm, fill=fill, stroke=stroke, font_size=11, sub_size=9))

    # Arrows down to teams
    teams = [(260, "Team A\n애플리케이션"), (410, "Team B\n데이터 분석"), (560, "전 세계\n사용자")]
    for x, _ in teams:
        c.append(f'<line x1="{x}" y1="210" x2="{x}" y2="245" stroke="#666" stroke-width="1.5" marker-end="url(#ah-666)"/>')

    for x, name in teams:
        c.append(box(x-75, 250, 150, 50, name.replace("\n", " "), fill=C_NEUTRAL_FILL, stroke=C_NEUTRAL_STROKE, font_size=10))

    c.append(f'<text x="410" y="320" font-size="10" fill="{C_SUBTLE}" text-anchor="middle" font-style="italic">하나의 버킷, 세 개의 접근 지점, 각각 다른 정책</text>')

    return wrap_svg(820, 335, "\n".join(c), defs)

# ============================================================
# 07: Dual Policy Evaluation Flow
# ============================================================
def svg_07():
    defs = markers(["#666", "#dc2626", "#16a34a"])
    c = []
    c.append(f'<text x="410" y="28" font-size="15" font-weight="700" fill="{C_BODY}" text-anchor="middle">이중 정책 평가 흐름</text>')

    # Request
    c.append(box(300, 50, 220, 40, "요청 수신", fill=C_NEUTRAL_FILL, stroke=C_NEUTRAL_STROKE, font_size=12))
    c.append(arrow_v(410, 90, 115, "#666"))

    # Step 1: AP Policy
    c.append(box(250, 120, 320, 55, "1. Access Point 정책 평가", fill=C_CLIENT_FILL, stroke=C_CLIENT_STROKE, font_size=12))
    c.append(f'<text x="590" y="140" font-size="10" fill="{C_WARN_TEXT}">Deny? ──YES──► ❌ 거부</text>')
    c.append(f'<text x="590" y="158" font-size="10" fill="{C_SERVER_TEXT}">No (Allow) ↓</text>')
    c.append(arrow_v(410, 175, 200, "#666"))

    # Step 2: Bucket Policy
    c.append(box(250, 205, 320, 55, "2. 버킷 정책 평가", fill=C_SERVER_FILL, stroke=C_SERVER_STROKE, font_size=12))
    c.append(f'<text x="590" y="225" font-size="10" fill="{C_WARN_TEXT}">Deny? ──YES──► ❌ 거부</text>')
    c.append(f'<text x="590" y="243" font-size="10" fill="{C_SERVER_TEXT}">No (Allow) ↓</text>')
    c.append(arrow_v(410, 260, 285, "#666"))

    # Allow
    c.append(box(320, 290, 180, 40, "✅ 허용", fill=C_SERVER_FILL, stroke=C_SERVER_STROKE, text_color=C_SERVER_TEXT, font_size=13))

    c.append(f'<text x="410" y="350" font-size="10" fill="{C_SUBTLE}" text-anchor="middle" font-style="italic">두 정책이 모두 Allow여야 최종 허용</text>')

    return wrap_svg(820, 365, "\n".join(c), defs)

# ============================================================
# 08: VPC Access Point (Allow/Deny)
# ============================================================
def svg_08():
    defs = markers(["#16a34a", "#dc2626"])
    c = []
    c.append(f'<text x="410" y="28" font-size="15" font-weight="700" fill="{C_BODY}" text-anchor="middle">VPC 제한 Access Point</text>')

    # Top row: Internal VPC (allowed)
    c.append(box(30, 55, 180, 50, "사내 VPC", sub="vpc-0abc...", fill=C_SERVER_FILL, stroke=C_SERVER_STROKE, font_size=12, sub_size=9))
    c.append(arrow_h(210, 320, 80, "#16a34a", "✅"))
    c.append(box(320, 55, 180, 50, "Access Point", sub='"internal-ap"', fill=C_CLIENT_FILL, stroke=C_CLIENT_STROKE, font_size=12, sub_size=9))
    c.append(arrow_h(500, 610, 80, "#16a34a"))
    c.append(box(610, 55, 160, 50, "S3 버킷", fill=C_SERVER_FILL, stroke=C_SERVER_STROKE, font_size=12))
    c.append(f'<text x="700" y="125" font-size="11" fill="{C_SERVER_TEXT}" font-weight="600" text-anchor="middle">접근 허용</text>')

    # Divider
    c.append(f'<line x1="20" y1="145" x2="800" y2="145" stroke="#eee" stroke-width="2" stroke-dasharray="6,4"/>')

    # Bottom row: External (blocked)
    c.append(box(30, 165, 180, 50, "외부 인터넷", sub="(다른 VPC)", fill=C_WARN_FILL, stroke=C_WARN_STROKE, font_size=12, sub_size=9))
    c.append(arrow_h(210, 320, 190, "#dc2626", "❌"))
    c.append(box(320, 165, 180, 50, "Access Point", sub='"internal-ap"', fill=C_CLIENT_FILL, stroke=C_CLIENT_STROKE, font_size=12, sub_size=9))
    c.append(f'<text x="600" y="195" font-size="11" fill="{C_WARN_TEXT}" font-weight="600">접근 거부!</text>')

    return wrap_svg(820, 235, "\n".join(c), defs)

# ============================================================
# 09: Decision Tree
# ============================================================
def svg_09():
    defs = markers(["#666", "#2563eb", "#16a34a"])
    c = []
    c.append(f'<text x="410" y="28" font-size="15" font-weight="700" fill="{C_BODY}" text-anchor="middle">데이터 공유 방식 선택 가이드</text>')

    # Decision diamonds + results
    decisions = [
        (100, "상업적 판매?", "Data Exchange", C_INFO_FILL, C_INFO_STROKE, C_INFO_TEXT),
        (175, "다수 구독자?", "Data Exchange", C_INFO_FILL, C_INFO_STROKE, C_INFO_TEXT),
        (250, "공개 데이터?", "Registry", C_CLIENT_FILL, C_CLIENT_STROKE, C_CLIENT_TEXT),
        (325, "내부 다수 팀?", "Access Points", C_SERVER_FILL, C_SERVER_STROKE, C_SERVER_TEXT),
    ]

    # Vertical flow
    for i, (y, q, result, fill, stroke, tc) in enumerate(decisions):
        # Diamond
        c.append(f'<polygon points="250,{y} 350,{y+25} 250,{y+50} 150,{y+25}" fill="{C_NEUTRAL_FILL}" stroke="{C_NEUTRAL_STROKE}" stroke-width="1.5"/>')
        c.append(f'<text x="250" y="{y+29}" font-size="11" fill="{C_NEUTRAL_TEXT}" text-anchor="middle">{q}</text>')

        # YES arrow right
        c.append(arrow_h(350, 470, y+25, "#666", "YES"))
        c.append(box(470, y, 200, 50, result, fill=fill, stroke=stroke, text_color=tc, font_size=12))

        # NO arrow down
        if i < len(decisions) - 1:
            c.append(f'<line x1="250" y1="{y+50}" x2="250" y2="{y+70}" stroke="#666" stroke-width="1.5" marker-end="url(#ah-666)"/>')
            c.append(f'<text x="265" y="{y+64}" font-size="9" fill="{C_SUBTLE}">NO</text>')
        else:
            c.append(f'<text x="250" y="{y+70}" font-size="10" fill="{C_SUBTLE}" text-anchor="middle">NO → 요구사항 재검토</text>')

    return wrap_svg(820, 420, "\n".join(c), defs)


# ============================================================
# Generate all
# ============================================================
svgs = {
    "03-01-registry-architecture.svg": svg_01,
    "03-02-copy-vs-inplace.svg": svg_02,
    "03-03-data-exchange-flow.svg": svg_03,
    "03-04-subscription-lifecycle.svg": svg_04,
    "03-05-why-access-points.svg": svg_05,
    "03-06-access-points-architecture.svg": svg_06,
    "03-07-dual-policy-evaluation.svg": svg_07,
    "03-08-vpc-access-point.svg": svg_08,
    "03-09-decision-tree.svg": svg_09,
}

for fname, func in svgs.items():
    path = os.path.join(OUT, fname)
    with open(path, "w") as f:
        f.write(func())
    print(f"Generated: {fname}")
