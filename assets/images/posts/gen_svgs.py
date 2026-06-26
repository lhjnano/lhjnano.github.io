#!/usr/bin/env python3
"""Generate SVG diagrams for IAM & Security blog series (v2 - improved spacing)."""
import os

D = "/home/lhjnano/me/github_page/assets/images/posts"

# ── Helpers ──────────────────────────────────────────────

def svg(w, h, body):
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" font-family="'Segoe UI','Noto Sans KR',system-ui,sans-serif">
{body}
</svg>'''

def box(x, y, w, h, fill="#f0f4f8", stroke="#4183c4", sw=1.5, r=10):
    return f'  <rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>\n'

def text(x, y, t, size=13, color="#1a1a1a", weight="normal", anchor="middle"):
    safe_t = t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f'  <text x="{x}" y="{y}" font-size="{size}" fill="{color}" font-weight="{weight}" text-anchor="{anchor}">{safe_t}</text>\n'

def arrow(x1, y1, x2, y2, color="#666", sw=1.8):
    return f'  <line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{sw}" marker-end="url(#ah)"/>\n'

def arrow_h(x1, x2, y, color="#666", sw=1.8):
    return arrow(x1, y, x2, y, color, sw)

def arrow_v(x, y1, y2, color="#666", sw=1.8):
    return arrow(x, y1, x, y2, color, sw)

def defs():
    return '''  <defs>
    <marker id="ah" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto" markerUnits="strokeWidth">
      <path d="M0,0 L0,6 L9,3 z" fill="#666"/>
    </marker>
  </defs>\n'''

def vline(x, y1, y2, color="#ddd", sw=1, dash="4,4"):
    return f'  <line x1="{x}" y1="{y1}" x2="{x}" y2="{y2}" stroke="{color}" stroke-width="{sw}" stroke-dasharray="{dash}"/>\n'

def save(name, content):
    path = os.path.join(D, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(content)
    print(f"  OK {name}")

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
    w, h = 800, 420
    bw, bh = 210, 160
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
    for i, (title_t, q, items) in enumerate(labels):
        sc, sf = colors[i]
        x = x0 + i*(bw+gap)
        cx = x + bw/2
        body += box(x, y0, bw, bh, sf, sc)
        body += text(cx, y0+30, title_t, 15, sc, "bold")
        body += text(cx, y0+55, q, 12, GY)
        for j, item in enumerate(items):
            body += text(cx, y0+90+j*22, item, 12, "#555")
    # Arrows down
    for i in range(3):
        x = x0 + i*(bw+gap) + bw/2
        body += arrow_v(x, y0+bh, y0+bh+35)
    # Identity Store
    isw, ish = 340, 50
    isx = (w - isw) / 2
    isy = y0 + bh + 35
    body += box(isx, isy, isw, ish, "#e8eef3", GY)
    body += text(w/2, isy+31, "Identity Store (AD / LDAP / DB)", 13, "#333", "bold")
    save("iam-overview/01-iam-3-elements.svg", svg(w, h, body))

# ── 2. Access Control Evolution ──────────────────────────

def access_control_evolution():
    w, h = 800, 300
    body = defs()
    eras = [
        ("DAC", "1980년대", "임의 접근 제어", "소유자가 권한 부여", '"파일 주인이 결정"', GY, LB),
        ("MAC", "1980년대", "강제 접근 제어", "시스템이 강제 분류", '"기밀/대외비 분류"', YL, LY),
        ("RBAC", "1990년대", "역할 기반 접근 제어", "역할별 권한 그룹화", '"관리자/사용자"', BL, LB),
        ("PBAC", "2010년대~", "정책 기반 접근 제어", "정책 문서로 세밀 제어", '"AWS IAM 방식"', GR, LG),
    ]
    bw, bh = 165, 200
    gap = 32
    x0 = (w - 4*bw - 3*gap) / 2
    y0 = 40
    for i, (name, era, full, desc, quote, sc, sf) in enumerate(eras):
        x = x0 + i*(bw+gap)
        cx = x + bw/2
        body += box(x, y0, bw, bh, sf, sc)
        body += text(cx, y0+32, name, 18, sc, "bold")
        body += text(cx, y0+55, era, 11, GY)
        body += text(cx, y0+88, full, 12, "#333", "bold")
        body += text(cx, y0+112, desc, 11, "#555")
        body += text(cx, y0+145, quote, 10, sc, "normal")
        if i == 3:
            body += text(cx, y0+175, "<- 현재 표준", 10, GR, "bold")
        if i < 3:
            ax1 = x + bw + 4
            ax2 = x + bw + gap - 4
            body += arrow_h(ax1, ax2, y0+bh/2)
    save("iam-overview/02-access-control-evolution.svg", svg(w, h, body))

# ── 3. RBAC Model ────────────────────────────────────────

def rbac_model():
    w, h = 620, 240
    body = defs()
    bw, bh = 140, 100
    y0 = 60
    # Users
    body += box(30, y0, bw, bh, LB, BL)
    body += text(30+bw/2, y0+32, "사용자", 14, BL, "bold")
    body += text(30+bw/2, y0+58, "홍길동", 12, "#555")
    body += text(30+bw/2, y0+78, "김철수", 12, "#555")
    # Role
    rx = 240
    body += box(rx, y0, bw, bh, LP, PR)
    body += text(rx+bw/2, y0+32, "역할 (Role)", 14, PR, "bold")
    body += text(rx+bw/2, y0+58, "user_admin", 12, "#555")
    # Permissions
    px = 450
    body += box(px, y0, bw, bh, LG, GR)
    body += text(px+bw/2, y0+28, "권한", 14, GR, "bold")
    body += text(px+bw/2, y0+50, "users:CRUD", 11, "#555")
    body += text(px+bw/2, y0+68, "groups:Read", 11, "#555")
    body += text(px+bw/2, y0+86, "dashboard:R", 11, "#555")
    # Arrows
    midy = y0 + bh/2
    body += arrow_h(30+bw+4, rx-4, midy)
    body += arrow_h(rx+bw+4, px-4, midy)
    # Bottom note
    body += text(w/2, 205, "역할 수만큼 권한 세트가 고정됨, 세분화된 제어 불가", 11, RD)
    save("pbac-vs-rbac/01-rbac-model.svg", svg(w, h, body))

# ── 4. PBAC Model ────────────────────────────────────────

def pbac_model():
    w, h = 720, 300
    body = defs()
    ymid = 110
    # User
    body += box(20, ymid-30, 120, 80, LB, BL)
    body += text(80, ymid, "사용자", 13, BL, "bold")
    body += text(80, ymid+22, "+ 그룹", 11, "#555")
    # Policy
    pw_box, ph_box = 190, 170
    px = 180
    py = 55
    body += box(px, py, pw_box, ph_box, LY, YL)
    body += text(px+pw_box/2, py+25, "정책 문서 (JSON)", 13, YL, "bold")
    body += text(px+pw_box/2, py+55, "Effect: Allow", 11, "#555")
    body += text(px+pw_box/2, py+75, "Action: users:*", 11, "#555")
    body += text(px+pw_box/2, py+95, "Resource: ou=Sales", 11, "#555")
    body += text(px+pw_box/2, py+115, "Condition: IP, 시간", 11, "#555")
    body += text(px+pw_box/2, py+145, "Deny: users:Delete", 11, RD)
    body += text(px+pw_box/2, py+160, "cn=Admin", 11, RD)
    # Evaluation
    body += box(430, ymid-30, 120, 80, LP, PR)
    body += text(490, ymid, "정책 평가", 13, PR, "bold")
    body += text(490, ymid+22, "엔진", 11, "#555")
    # Result
    body += box(600, ymid-30, 90, 80, LG, GR)
    body += text(645, ymid+5, "Allow", 14, GR, "bold")
    body += text(645, ymid+28, "또는", 10, GY)
    body += text(645, ymid+45, "Deny", 14, RD, "bold")
    # Arrows
    body += arrow_h(144, 176, ymid+10)
    body += arrow_h(374, 426, ymid+10)
    body += arrow_h(554, 596, ymid+10)
    save("pbac-vs-rbac/02-pbac-model.svg", svg(w, h, body))

# ── 5. Evaluation Algorithm ──────────────────────────────

def evaluation_algorithm():
    w, h = 560, 480
    body = defs()
    cx = w/2
    bw_s = 420
    steps = [
        ("1. 정책 수집", "사용자 + 그룹 + 시스템 정책 수집", LB, BL, 60),
        ("2. 기본 결정: DENY", "명시적으로 허용하지 않으면 모두 거부", LR, RD, 150),
        ("3. Statement 평가", "Action 매칭 -> Resource 매칭 -> Condition 확인", LY, YL, 240),
        ("4. Deny 발견?", "Deny가 하나라도 있으면 즉시 DENY 반환", LR, RD, 330),
        ("5. Allow 합산", "Allow가 있으면 ALLOW, 없으면 DENY", LG, GR, 420),
    ]
    for title_t, desc, sf, sc, y in steps:
        body += box(cx-bw_s/2, y, bw_s, 60, sf, sc)
        body += text(cx, y+25, title_t, 14, sc, "bold")
        body += text(cx, y+47, desc, 11, "#555")
    # Arrows between steps
    for i in range(len(steps)-1):
        y1 = steps[i][4] + 60
        y2 = steps[i+1][4]
        body += arrow_v(cx, y1, y2)
    save("pbac-vs-rbac/03-evaluation-algorithm.svg", svg(w, h, body))

# ── 6. OAuth2 Auth Code Flow ─────────────────────────────

def oauth2_flow():
    w, h = 740, 680
    body = defs()
    # Three actors (x positions)
    ax = [100, 370, 640]
    actor_labels = [("사용자", "(브라우저)"), ("Client", "(앱)"), ("Auth Server", "")]
    for i, x in enumerate(ax):
        body += box(x-65, 15, 130, 55, LB, BL)
        body += text(x, 38, actor_labels[i][0], 13, BL, "bold")
        if actor_labels[i][1]:
            body += text(x, 56, actor_labels[i][1], 11, "#666")
        body += vline(x, 70, h-25)
    # Steps: (x1_idx, x2_idx, y, label_lines, color)
    steps = [
        (0, 1, 110, ['"로그인" 클릭'], BL),
        (1, 0, 160, ['인가 페이지로', '리다이렉트'], "#555"),
        (0, 2, 215, ['인가 페이지로 이동'], "#555"),
        (2, 0, 265, ['동의 화면 표시'], "#555"),
        (0, 2, 315, ['로그인 + 동의'], BL),
        (2, 0, 365, ['Authorization Code', '발급 (redirect)'], BL),
        (1, 2, 420, ['코드로 토큰 교환', 'POST /token'], BL),
        (2, 1, 475, ['Access Token', '+ Refresh Token'], GR),
        (1, 2, 530, ['API 호출', 'Authorization: Bearer'], BL),
        (2, 1, 585, ['보호된 데이터 반환'], GR),
    ]
    for x1i, x2i, y, lines, color in steps:
        x1, x2 = ax[x1i], ax[x2i]
        direction = 1 if x1 < x2 else -1
        body += arrow_h(x1+(12*direction), x2-(12*direction), y, color, 1.5)
        mid_x = (x1+x2)/2
        # Place label centered, lines above the arrow
        total_lines = len(lines)
        start_y = y - 6 - (total_lines-1)*14
        for j, line in enumerate(lines):
            body += text(mid_x, start_y + j*14, line, 10, color)
    # Bottom note
    body += text(w/2, h-10, "프론트채널(브라우저 경유)과 백채널(서버 직접)의 분리가 핵심", 11, GY)
    save("oauth2-oidc/01-auth-code-flow.svg", svg(w, h, body))

# ── 7. MFA 3 Factors ─────────────────────────────────────

def mfa_3_factors():
    w, h = 640, 290
    body = defs()
    factors = [
        ("Something You KNOW", "아는 것", ["비밀번호", "PIN 번호", "패턴"], BL, LB),
        ("Something You HAVE", "가진 것", ["스마트폰", "OTP 토큰", "스마트카드"], GR, LG),
        ("Something You ARE", "생체", ["지문", "얼굴", "홍채"], PR, LP),
    ]
    bw, bh = 170, 175
    gap = 55
    x0 = (w - 3*bw - 2*gap) / 2
    y0 = 45
    for i, (title_t, sub, items, sc, sf) in enumerate(factors):
        x = x0 + i*(bw+gap)
        cx = x + bw/2
        body += box(x, y0, bw, bh, sf, sc, 1.5, 85)
        body += text(cx, y0+32, title_t, 11, sc, "bold")
        body += text(cx, y0+58, sub, 14, "#333", "bold")
        for j, item in enumerate(items):
            body += text(cx, y0+95+j*22, item, 12, "#555")
    body += text(w/2, y0+bh+35, "MFA = 서로 다른 종류의 요소를 2개 이상 조합", 14, "#333", "bold")
    save("mfa-totp/01-3-factors.svg", svg(w, h, body))

# ── 8. TOTP Principle ────────────────────────────────────

def totp_principle():
    w, h = 600, 310
    body = defs()
    bw, bh = 190, 145
    # Server
    sx = 30
    body += box(sx, 35, bw, bh, LB, BL)
    body += text(sx+bw/2, 65, "서버", 14, BL, "bold")
    body += text(sx+bw/2, 90, "비밀키 K (동일)", 11, "#555")
    body += text(sx+bw/2, 108, "시간 T (동일)", 11, "#555")
    body += box(sx+35, 125, bw-70, 35, LG, GR)
    body += text(sx+bw/2, 148, "847 291", 17, GR, "bold")
    # Phone
    px = 380
    body += box(px, 35, bw, bh, LP, PR)
    body += text(px+bw/2, 65, "스마트폰", 14, PR, "bold")
    body += text(px+bw/2, 90, "비밀키 K (동일)", 11, "#555")
    body += text(px+bw/2, 108, "시간 T (동일)", 11, "#555")
    body += box(px+35, 125, bw-70, 35, LG, GR)
    body += text(px+bw/2, 148, "847 291", 17, GR, "bold")
    # Center text
    cx = w/2
    body += text(cx, 80, "같은 비밀키", 12, "#333", "bold")
    body += text(cx, 98, "+ 같은 시간", 12, "#333", "bold")
    body += text(cx, 118, "= 같은 코드", 12, GR, "bold")
    body += text(cx, 140, "30초마다 변경", 11, GY)
    # Bottom
    body += text(w/2, 225, "통신 불필요, 완전히 오프라인 작동", 13, BL, "bold")
    body += text(w/2, 250, "Google Authenticator, Microsoft Authenticator 호환", 11, GY)
    body += text(w/2, 275, "에어갭 환경에서 작동하는 유일한 소프트웨어 MFA", 11, GY)
    save("mfa-totp/02-totp-principle.svg", svg(w, h, body))

# ── 9. Kerberos 3-Stage Flow ─────────────────────────────

def kerberos_flow():
    w, h = 700, 620
    body = defs()
    ax = [110, 350, 590]
    actor_labels = [("클라이언트", "(사용자 PC)"), ("KDC", "(AD DC)"), ("서비스", "(웹 관리)")]
    for i, x in enumerate(ax):
        body += box(x-70, 15, 140, 55, LB, BL)
        body += text(x, 38, actor_labels[i][0], 13, BL, "bold")
        if actor_labels[i][1]:
            body += text(x, 56, actor_labels[i][1], 11, "#666")
        body += vline(x, 70, h-30)
    # Stage labels
    stages = [
        ("단계 1: AS Exchange", 95, BL),
        ("단계 2: TGS Exchange", 250, PR),
        ("단계 3: Client-Server", 405, GR),
    ]
    for label, y, color in stages:
        body += text(w/2, y, label, 12, color, "bold")
    # Steps
    steps = [
        (0, 1, 120, ['"TGT 주세요"'], BL),
        (1, 0, 165, ['TGT 발급', '(KDC 비밀키로 암호화)'], GR),
        (0, 1, 280, ['TGT로 서비스', '티켓 요청'], BL),
        (1, 0, 325, ['서비스 티켓 발급', '(서비스 비밀키로 암호화)'], GR),
        (0, 2, 435, ['서비스 티켓 제시'], BL),
        (2, 0, 480, ['티켓 검증', '-> 인증 성공!'], GR),
    ]
    for x1i, x2i, y, lines, color in steps:
        x1, x2 = ax[x1i], ax[x2i]
        direction = 1 if x1 < x2 else -1
        body += arrow_h(x1+(12*direction), x2-(12*direction), y, color, 1.5)
        mid_x = (x1+x2)/2
        start_y = y - 6 - (len(lines)-1)*14
        for j, line in enumerate(lines):
            body += text(mid_x, start_y + j*14, line, 10, color)
    # Key insight
    body += text(w/2, h-12, "비밀번호는 네트워크로 절대 전송되지 않음", 12, RD, "bold")
    save("kerberos-sso/01-3-stage-flow.svg", svg(w, h, body))

# ── 10. SPNEGO Flow ──────────────────────────────────────

def spnego_flow():
    w, h = 580, 460
    body = defs()
    ax = [130, 450]
    actor_labels = ["브라우저", "웹 서버"]
    for i, x in enumerate(ax):
        body += box(x-65, 15, 130, 50, LB, BL)
        body += text(x, 45, actor_labels[i], 13, BL, "bold")
        body += vline(x, 65, h-25)
    steps = [
        (0, 1, 110, ['GET /dashboard'], "#555"),
        (1, 0, 160, ['401 Unauthorized', 'WWW-Authenticate: Negotiate'], RD),
        (0, 0, 215, ['KDC에 서비스 티켓 요청', '(별도 채널)'], BL),
        (0, 1, 275, ['GET /dashboard', 'Authorization: Negotiate <ticket>'], BL),
        (1, 0, 340, ['200 OK + JWT', '(티켓 검증 성공, 자동 로그인)'], GR),
        (0, 1, 400, ['로그인 완료!', '비밀번호 입력 없음'], "#333"),
    ]
    for idx, (x1i, x2i, y, lines, color) in enumerate(steps):
        if x1i == x2i:
            # Self-loop (KDC request)
            x = ax[x1i]
            body += text(x, y-10, lines[0], 10, color)
            if len(lines) > 1:
                body += text(x, y+5, lines[1], 10, color)
        else:
            x1, x2 = ax[x1i], ax[x2i]
            direction = 1 if x1 < x2 else -1
            body += arrow_h(x1+(12*direction), x2-(12*direction), y, color, 1.5)
            mid_x = (x1+x2)/2
            start_y = y - 6 - (len(lines)-1)*14
            for j, line in enumerate(lines):
                body += text(mid_x, start_y + j*14, line, 10, color)
    save("kerberos-sso/02-spnego-flow.svg", svg(w, h, body))

# ── 11. JWT Structure ────────────────────────────────────

def jwt_structure():
    w, h = 720, 220
    body = defs()
    parts = [
        ("Header", "eyJhbGciOi...", ["토큰 타입", "서명 알고리즘"], RD, LR),
        ("Payload", "eyJzdWIiOi...", ["사용자 정보", "권한, 만료 시간"], PR, LP),
        ("Signature", "IEMU52xs...", ["변조 방지", "(HMAC-SHA256)"], GR, LG),
    ]
    bw_p = 170
    gap_p = 40
    total = 3*bw_p + 2*gap_p
    x0 = (w - total) / 2
    y0 = 45
    for i, (title_t, example, desc_lines, sc, sf) in enumerate(parts):
        x = x0 + i*(bw_p+gap_p)
        cx = x + bw_p/2
        body += box(x, y0, bw_p, 120, sf, sc)
        body += text(cx, y0+28, title_t, 15, sc, "bold")
        body += text(cx, y0+52, example, 10, GY)
        for j, dl in enumerate(desc_lines):
            body += text(cx, y0+82+j*18, dl, 11, "#555")
    # Dots between parts
    dot_y = y0 + 60
    for i in range(2):
        dx = x0 + (i+1)*bw_p + i*gap_p + gap_p/2
        body += text(dx, dot_y, ".", 22, "#333", "bold")
    # Bottom
    body += text(w/2, 200, "점(.)으로 구분된 3개 부분", 12, "#333", "bold")
    save("jwt-tokens/01-jwt-structure.svg", svg(w, h, body))

# ── 12. JWT Auth Flow ────────────────────────────────────

def jwt_auth_flow():
    w, h = 580, 480
    body = defs()
    ax = [130, 450]
    actor_labels = ["클라이언트", "서버"]
    for i, x in enumerate(ax):
        body += box(x-65, 15, 130, 50, LB, BL)
        body += text(x, 45, actor_labels[i], 13, BL, "bold")
        body += vline(x, 65, h-25)
    steps = [
        (0, 1, 110, ['POST /auth/login', '{username, password}'], BL),
        (1, 0, 170, ['LDAP 인증 + JWT 생성', '(secret_key로 서명)'], "#555"),
        (1, 0, 230, ['JWT 반환'], GR),
        (0, 1, 295, ['API 호출', 'Authorization: Bearer <JWT>'], BL),
        (1, 0, 365, ['JWT 검증 (서명, 만료)', '+ 권한 확인 (PBAC)', '-> 200 OK'], GR),
        (1, 0, 430, ['데이터 반환'], "#555"),
    ]
    for x1i, x2i, y, lines, color in steps:
        x1, x2 = ax[x1i], ax[x2i]
        direction = 1 if x1 < x2 else -1
        body += arrow_h(x1+(12*direction), x2-(12*direction), y, color, 1.5)
        mid_x = (x1+x2)/2
        start_y = y - 6 - (len(lines)-1)*14
        for j, line in enumerate(lines):
            body += text(mid_x, start_y + j*14, line, 10, color)
    save("jwt-tokens/02-auth-flow.svg", svg(w, h, body))

# ── Generate All ─────────────────────────────────────────

print("Generating SVGs (v2 - improved spacing)...")
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
print("Done! 12 SVGs regenerated.")
