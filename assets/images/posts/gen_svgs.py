#!/usr/bin/env python3
"""Generate SVG diagrams for IAM & Security blog series."""
import os

D = "/home/lhjnano/me/github_page/assets/images/posts"

# ── Helpers ──────────────────────────────────────────────

def svg(w, h, body):
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" font-family="'Segoe UI','Noto Sans KR',system-ui,sans-serif">
{body}
</svg>'''

def box(x, y, w, h, fill="#f0f4f8", stroke="#4183c4", sw=1.5, r=10):
    return f'  <rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>'

def text(x, y, t, size=13, color="#1a1a1a", weight="normal", anchor="middle"):
    return f'  <text x="{x}" y="{y}" font-size="{size}" fill="{color}" font-weight="{weight}" text-anchor="{anchor}">{t}</text>'

def arrow(x1, y1, x2, y2, color="#666", sw=1.8):
    return f'  <line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{sw}" marker-end="url(#ah)"/>'

def arrow_h(x1, x2, y, color="#666", sw=1.8):
    return arrow(x1, y, x2, y, color, sw)

def arrow_v(x, y1, y2, color="#666", sw=1.8):
    return arrow(x, y1, x, y2, color, sw)

def defs():
    return '''  <defs>
    <marker id="ah" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto" markerUnits="strokeWidth">
      <path d="M0,0 L0,6 L9,3 z" fill="#666"/>
    </marker>
  </defs>'''

def save(name, content):
    path = os.path.join(D, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(content)
    print(f"  ✓ {name}")

# ── Color palette ────────────────────────────────────────

BL = "#4183c4"  # blue
GR = "#3fb950"  # green
RD = "#f85149"  # red
PR = "#bc8cff"  # purple
YL = "#d29922"  # yellow
GY = "#8b949e"  # gray
LB = "#f0f4f8"  # light blue bg
LG = "#f0fff4"  # light green bg
LR = "#fff0f0"  # light red bg
LY = "#fffdf0"  # light yellow bg
LP = "#f8f0ff"  # light purple bg

# ── 1. IAM 3 Elements ───────────────────────────────────

def iam_3_elements():
    w, h = 760, 400
    bw, bh = 200, 130
    gap = 40
    x0 = (w - 3*bw - 2*gap) / 2
    y0 = 50
    colors = [(BL, LB), (PR, LP), (YL, LY)]
    labels = [
        ("인증 (AuthN)", '"너 누구야?"', ["비밀번호", "MFA / SSO", "인증서 (x509)"]),
        ("인가 (AuthZ)", '"뭘 할 수 있어?"', ["RBAC (역할)", "PBAC (정책)", "ABAC (속성)"]),
        ("감사 (Audit)", '"뭘 했어?"', ["접근 로그", "변경 이력", "컴플라이언스"]),
    ]
    body = defs()
    for i, (title, q, items) in enumerate(labels):
        sc, sf = colors[i]
        x = x0 + i*(bw+gap)
        body += box(x, y0, bw, bh, sf, sc)
        body += text(x+bw/2, y0+25, title, 15, sc, "bold")
        body += text(x+bw/2, y0+48, q, 12, GY)
        for j, item in enumerate(items):
            body += text(x+bw/2, y0+78+j*18, item, 11, "#555")
    # Arrows down
    for i in range(3):
        x = x0 + i*(bw+gap) + bw/2
        body += arrow_v(x, y0+bh, y0+bh+40)
    # Identity Store
    isw, ish = 320, 50
    isx = (w - isw) / 2
    isy = y0 + bh + 40
    body += box(isx, isy, isw, ish, "#e8eef3", GY)
    body += text(w/2, isy+30, "Identity Store (AD / LDAP / DB)", 13, "#333", "bold")
    save("iam-overview/01-iam-3-elements.svg", svg(w, h, body))

# ── 2. Access Control Evolution ──────────────────────────

def access_control_evolution():
    w, h = 760, 280
    body = defs()
    eras = [
        ("DAC", "1980년대", "임의 접근 제어", "소유자가 권한 부여", '"파일 주인이 결정"', GY, LB),
        ("MAC", "1980년대", "강제 접근 제어", "시스템이 강제 분류", '"기밀/대외비 분류"', YL, LY),
        ("RBAC", "1990년대", "역할 기반 접근 제어", "역할별 권한 그룹화", '"관리자/사용자"', BL, LB),
        ("PBAC", "2010년대~", "정책 기반 접근 제어", "정책 문서로 세밀 제어", '"AWS IAM 방식"', GR, LG),
    ]
    bw, bh = 160, 180
    gap = 32
    x0 = (w - 4*bw - 3*gap) / 2
    y0 = 40
    for i, (name, era, full, desc, quote, sc, sf) in enumerate(eras):
        x = x0 + i*(bw+gap)
        body += box(x, y0, bw, bh, sf, sc)
        body += text(x+bw/2, y0+30, name, 18, sc, "bold")
        body += text(x+bw/2, y0+50, era, 11, GY)
        body += text(x+bw/2, y0+78, full, 12, "#333", "bold")
        body += text(x+bw/2, y0+100, desc, 11, "#555")
        body += text(x+bw/2, y0+130, quote, 10, sc, "normal")
        if i == 3:
            body += text(x+bw/2, y0+155, "← 현재 표준", 10, GR, "bold")
        if i < 3:
            ax1 = x + bw + 4
            ax2 = x + bw + gap - 4
            body += arrow_h(ax1, ax2, y0+bh/2)
    save("iam-overview/02-access-control-evolution.svg", svg(w, h, body))

# ── 3. RBAC Model ────────────────────────────────────────

def rbac_model():
    w, h = 600, 220
    body = defs()
    # Users
    body += box(40, 70, 120, 80, LB, BL)
    body += text(100, 100, "사용자", 14, BL, "bold")
    body += text(100, 122, "홍길동, 김철수", 11, "#555")
    # Role
    body += box(240, 70, 120, 80, LP, PR)
    body += text(300, 100, "역할 (Role)", 14, PR, "bold")
    body += text(300, 122, "user_admin", 11, "#555")
    # Permissions
    body += box(440, 70, 120, 80, LG, GR)
    body += text(500, 95, "권한", 14, GR, "bold")
    body += text(500, 115, "users:CRUD", 10, "#555")
    body += text(500, 130, "groups:Read", 10, "#555")
    body += text(500, 145, "dashboard:R", 10, "#555")
    # Arrows
    body += arrow_h(164, 236, 110)
    body += arrow_h(364, 436, 110)
    # Bottom note
    body += text(w/2, 190, "역할 수만큼 권한 세트가 고정됨 — 세분화된 제어 불가", 11, RD)
    save("pbac-vs-rbac/01-rbac-model.svg", svg(w, h, body))

# ── 4. PBAC Model ────────────────────────────────────────

def pbac_model():
    w, h = 700, 280
    body = defs()
    # User
    body += box(30, 90, 110, 70, LB, BL)
    body += text(85, 120, "사용자", 13, BL, "bold")
    body += text(85, 140, "+ 그룹", 11, "#555")
    # Policy
    body += box(200, 50, 180, 150, LY, YL)
    body += text(290, 75, "정책 문서 (JSON)", 13, YL, "bold")
    body += text(290, 100, "Effect: Allow", 10, "#555")
    body += text(290, 116, "Action: users:*", 10, "#555")
    body += text(290, 132, "Resource: ou=Sales", 10, "#555")
    body += text(290, 148, "Condition: IP, 시간", 10, "#555")
    body += text(290, 172, "— Deny: users:Delete", 10, RD)
    body += text(290, 188, "  cn=Admin", 10, RD)
    # Evaluation
    body += box(440, 90, 110, 70, LP, PR)
    body += text(495, 115, "정책 평가", 13, PR, "bold")
    body += text(495, 135, "엔진", 11, "#555")
    # Result
    body += box(600, 90, 80, 70, LG, GR)
    body += text(640, 125, "Allow", 14, GR, "bold")
    body += text(640, 145, "또는 Deny", 11, RD)
    # Arrows
    body += arrow_h(144, 196, 125)
    body += arrow_h(384, 436, 125)
    body += arrow_h(554, 596, 125)
    save("pbac-vs-rbac/02-pbac-model.svg", svg(w, h, body))

# ── 5. Evaluation Algorithm ──────────────────────────────

def evaluation_algorithm():
    w, h = 560, 440
    body = defs()
    cx = w/2
    steps = [
        ("1. 정책 수집", "사용자 + 그룹 + 시스템 정책", LB, BL, 60),
        ("2. 기본 결정: DENY", "모든 것은 기본적으로 거부", LR, RD, 130),
        ("3. Statement 평가", "Action 매칭 → Resource 매칭\n→ Condition 확인", LY, YL, 210),
        ("4. Deny 발견?", "Deny가 하나라도 있으면 즉시 DENY", LR, RD, 300),
        ("5. Allow 합산", "Allow가 하나라도 있으면 ALLOW\n없으면 DENY", LG, GR, 370),
    ]
    for title, desc, sf, sc, y in steps:
        body += box(80, y, 400, 55, sf, sc)
        body += text(cx, y+22, title, 13, sc, "bold")
        desc_lines = desc.split('\n')
        for j, dl in enumerate(desc_lines):
            body += text(cx, y+42+j*14, dl, 10, "#555")
    # Arrows between steps
    for i in range(len(steps)-1):
        y1 = steps[i][4] + 55
        y2 = steps[i+1][4]
        body += arrow_v(cx, y1, y2)
    save("pbac-vs-rbac/03-evaluation-algorithm.svg", svg(w, h, body))

# ── 6. OAuth2 Auth Code Flow ─────────────────────────────

def oauth2_flow():
    w, h = 720, 560
    body = defs()
    # Three actors
    actors = [("사용자\n(브라우저)", 80), ("Client\n(앱)", 360), ("Auth Server", 640)]
    for label, x in actors:
        body += box(x-60, 20, 120, 50, LB, BL)
        for j, line in enumerate(label.split('\n')):
            body += text(x, 42+j*16, line, 12, BL, "bold")
        body += f'  <line x1="{x}" y1="70" x2="{x}" y2="{h-30}" stroke="#ddd" stroke-width="1" stroke-dasharray="4,4"/>'
    # Steps
    steps = [
        (80, 360, 90, '"로그인" 클릭', BL),
        (360, 80, 120, '인가 페이지로\n리다이렉트', "#555"),
        (80, 640, 150, '로그인 + 동의', BL),
        (640, 80, 180, '동의 화면 표시', "#555"),
        (80, 640, 220, 'Authorization Code\n발급 (redirect)', BL),
        (360, 640, 270, '코드 → 토큰 교환\nPOST /token', BL),
        (640, 360, 320, 'Access Token\n+ Refresh Token', GR),
        (360, 640, 380, 'API 호출\nAuthorization: Bearer', BL),
        (640, 360, 430, '보호된 데이터 반환', GR),
    ]
    for x1, x2, y, label, color in steps:
        # Arrow
        mid_y = y
        body += arrow_h(x1+(10 if x1<x2 else -10), x2+(-10 if x1<x2 else 10), mid_y, color, 1.5)
        # Label
        mid_x = (x1+x2)/2
        for j, line in enumerate(label.split('\n')):
            body += text(mid_x, mid_y-8+j*13, line, 9, color)
    save("oauth2-oidc/01-auth-code-flow.svg", svg(w, h, body))

# ── 7. MFA 3 Factors ─────────────────────────────────────

def mfa_3_factors():
    w, h = 600, 260
    body = defs()
    factors = [
        ("Something You KNOW", "아는 것", ["비밀번호", "PIN 번호", "패턴"], BL, LB),
        ("Something You HAVE", "가진 것", ["스마트폰", "OTP 토큰", "스마트카드"], GR, LG),
        ("Something You ARE", "생체", ["지문", "얼굴", "홍채"], PR, LP),
    ]
    bw, bh = 160, 160
    gap = 50
    x0 = (w - 3*bw - 2*gap) / 2
    y0 = 50
    for i, (title, sub, items, sc, sf) in enumerate(factors):
        x = x0 + i*(bw+gap)
        body += box(x, y0, bw, bh, sf, sc, 1.5, 80)
        body += text(x+bw/2, y0+30, title, 11, sc, "bold")
        body += text(x+bw/2, y0+50, sub, 13, "#333", "bold")
        for j, item in enumerate(items):
            body += text(x+bw/2, y0+85+j*20, item, 11, "#555")
    body += text(w/2, y0+bh+30, "MFA = 2가지 이상 조합", 14, "#333", "bold")
    save("mfa-totp/01-3-factors.svg", svg(w, h, body))

# ── 8. TOTP Principle ────────────────────────────────────

def totp_principle():
    w, h = 560, 280
    body = defs()
    # Server
    body += box(40, 40, 180, 130, LB, BL)
    body += text(130, 70, "서버", 14, BL, "bold")
    body += text(130, 95, "비밀키 K (동일)", 11, "#555")
    body += text(130, 113, "시간 T (동일)", 11, "#555")
    body += box(75, 130, 110, 30, LG, GR)
    body += text(130, 150, "847 291", 16, GR, "bold")
    # Phone
    body += box(340, 40, 180, 130, LP, PR)
    body += text(430, 70, "스마트폰", 14, PR, "bold")
    body += text(430, 95, "비밀키 K (동일)", 11, "#555")
    body += text(430, 113, "시간 T (동일)", 11, "#555")
    body += box(375, 130, 110, 30, LG, GR)
    body += text(430, 150, "847 291", 16, GR, "bold")
    # Connection
    body += text(280, 100, "같은 비밀키 + 같은 시간", 12, "#333", "bold")
    body += text(280, 118, "= 같은 코드", 12, GR, "bold")
    body += text(280, 140, "30초마다 변경", 11, GY)
    # Bottom
    body += text(w/2, 220, "통신 불필요 — 완전히 오프라인", 13, BL, "bold")
    body += text(w/2, 245, "Google Authenticator, Microsoft Authenticator 호환", 11, GY)
    save("mfa-totp/02-totp-principle.svg", svg(w, h, body))

# ── 9. Kerberos 3-Stage Flow ─────────────────────────────

def kerberos_flow():
    w, h = 680, 520
    body = defs()
    actors = [("클라이언트\n(사용자 PC)", 100), ("KDC\n(AD DC)", 340), ("서비스\n(웹 관리)", 580)]
    for label, x in actors:
        body += box(x-65, 20, 130, 50, LB, BL)
        for j, line in enumerate(label.split('\n')):
            body += text(x, 42+j*16, line, 12, BL, "bold")
        body += f'  <line x1="{x}" y1="70" x2="{x}" y2="{h-20}" stroke="#ddd" stroke-width="1" stroke-dasharray="4,4"/>'
    # Stage labels
    stages = [
        ("단계 1: AS Exchange", 80, BL),
        ("단계 2: TGS Exchange", 220, PR),
        ("단계 3: Client-Server", 360, GR),
    ]
    for label, y, color in stages:
        body += text(w/2, y-5, label, 12, color, "bold")
    # Steps
    steps = [
        (100, 340, 100, '"TGT 주세요"', BL),
        (340, 100, 130, 'TGT 발급\n(KDC 비밀키로 암호화)', GR),
        (100, 340, 240, 'TGT로 서비스\n티켓 요청', BL),
        (340, 100, 270, '서비스 티켓 발급', GR),
        (100, 580, 380, '서비스 티켓 제시', BL),
        (580, 100, 410, '티켓 검증\n→ 인증 성공!', GR),
    ]
    for x1, x2, y, label, color in steps:
        body += arrow_h(x1+(10 if x1<x2 else -10), x2+(-10 if x1<x2 else 10), y, color, 1.5)
        mid_x = (x1+x2)/2
        for j, line in enumerate(label.split('\n')):
            body += text(mid_x, y-8+j*12, line, 9, color)
    # Key insight
    body += text(w/2, h-30, "비밀번호는 네트워크로 절대 전송되지 않음", 12, RD, "bold")
    save("kerberos-sso/01-3-stage-flow.svg", svg(w, h, body))

# ── 10. SPNEGO Flow ──────────────────────────────────────

def spnego_flow():
    w, h = 560, 380
    body = defs()
    actors = [("브라우저", 120), ("웹 서버", 440)]
    for label, x in actors:
        body += box(x-60, 20, 120, 45, LB, BL)
        body += text(x, 47, label, 13, BL, "bold")
        body += f'  <line x1="{x}" y1="65" x2="{x}" y2="{h-20}" stroke="#ddd" stroke-width="1" stroke-dasharray="4,4"/>'
    steps = [
        (120, 440, 100, 'GET /dashboard', "#555"),
        (440, 120, 140, '401 Unauthorized\nWWW-Authenticate: Negotiate', RD),
        (120, 440, 200, 'KDC에 서비스 티켓 요청', BL),
        (120, 440, 250, 'GET /dashboard\nAuthorization: Negotiate <ticket>', BL),
        (440, 120, 310, '200 OK + JWT\n(티켓 검증 성공 → 자동 로그인)', GR),
    ]
    for x1, x2, y, label, color in steps:
        body += arrow_h(x1+(10 if x1<x2 else -10), x2+(-10 if x1<x2 else 10), y, color, 1.5)
        mid_x = (x1+x2)/2
        for j, line in enumerate(label.split('\n')):
            body += text(mid_x, y-8+j*13, line, 9, color)
    save("kerberos-sso/02-spnego-flow.svg", svg(w, h, body))

# ── 11. JWT Structure ────────────────────────────────────

def jwt_structure():
    w, h = 700, 200
    body = defs()
    parts = [
        ("Header", "eyJhbGciOi...", "토큰 타입\n서명 알고리즘", RD, LR, 80),
        ("Payload", "eyJzdWIiOi...", "사용자 정보\n권한, 만료 시간", PR, LP, 280),
        ("Signature", "IEMU52xs...", "변조 방지\n(HMAC-SHA256)", GR, LG, 480),
    ]
    for title, example, desc, sc, sf, x in parts:
        body += box(x, 50, 160, 100, sf, sc)
        body += text(x+80, 75, title, 14, sc, "bold")
        body += text(x+80, 97, example, 9, GY, "normal")
        for j, line in enumerate(desc.split('\n')):
            body += text(x+80, 122+j*14, line, 10, "#555")
    # Dots
    body += text(250, 100, ".", 20, "#333", "bold")
    body += text(450, 100, ".", 20, "#333", "bold")
    # Bottom
    body += text(w/2, 180, "점(.)으로 구분된 3개 부분", 12, "#333", "bold")
    save("jwt-tokens/01-jwt-structure.svg", svg(w, h, body))

# ── 12. JWT Auth Flow ────────────────────────────────────

def jwt_auth_flow():
    w, h = 560, 400
    body = defs()
    actors = [("클라이언트", 120), ("서버", 440)]
    for label, x in actors:
        body += box(x-60, 20, 120, 45, LB, BL)
        body += text(x, 47, label, 13, BL, "bold")
        body += f'  <line x1="{x}" y1="65" x2="{x}" y2="{h-20}" stroke="#ddd" stroke-width="1" stroke-dasharray="4,4"/>'
    steps = [
        (120, 440, 100, 'POST /auth/login\n{username, password}', BL),
        (440, 120, 160, 'LDAP 인증 →\nJWT 생성 (서명)', "#555"),
        (440, 120, 200, 'JWT 반환', GR),
        (120, 440, 260, 'API 호출\nAuthorization: Bearer <JWT>', BL),
        (440, 120, 320, 'JWT 검증 (서명, 만료)\n+ 권한 확인 (PBAC)\n→ 200 OK', GR),
    ]
    for x1, x2, y, label, color in steps:
        body += arrow_h(x1+(10 if x1<x2 else -10), x2+(-10 if x1<x2 else 10), y, color, 1.5)
        mid_x = (x1+x2)/2
        for j, line in enumerate(label.split('\n')):
            body += text(mid_x, y-8+j*13, line, 9, color)
    save("jwt-tokens/02-auth-flow.svg", svg(w, h, body))

# ── Generate All ─────────────────────────────────────────

print("Generating SVGs...")
iam_3_elements()
access_control_evolution()
rbac_model()
pbac_model()
evaluation_algorithm()
oauth2_flow()
mfa_3_factors()
totp_principle()
kerberos_flow()
spnego_flow()
jwt_structure()
jwt_auth_flow()
print("Done! 12 SVGs generated.")
