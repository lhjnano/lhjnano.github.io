---
layout: post
title: Cloudflare 스택으로 월 $0 웹서비스 만들기
categories: [Cloudflare, DevOps]
description: Cloudflare Pages + Workers + D1 + R2 무료 티어 조합으로 웹서비스를 구축하는 방법을 정리합니다. 호스팅 비교부터 이메일 발송, CI/CD까지 실전 가이드입니다.
keywords: [Cloudflare, Workers, D1, Pages, 무료호스팅, DevOps]
toc: true
toc_sticky: true
---

월 $0로 하루 10만 요청 API, 5GB 데이터베이스, 무제한 대역폭 웹호스팅을 무료로 만들었습니다. Cloudflare 스택 하나면 MVP부터 중규모 서비스까지 비용 걱정 없이 운영할 수 있습니다.

## TL;DR

- **Cloudflare Pages + Workers + D1 + R2** 조합으로 풀스택 웹서비스를 $0에 구축합니다
- **무제한 대역폭**과 한국 PoP로 트래픽 증가에도 추가 비용이 없습니다
- **Email Sending** 바인딩으로 API 키 없이 이메일 발송이 가능합니다
- **Cron Triggers**로 주기적 데이터 수집·분석을 서버리스로 처리합니다
- **GitHub Actions** 연동으로 CI/CD 파이프라인까지 무료 구성합니다

## 어떤 문제를 해결하나요?

트래픽이 조금만 늘어도 호스팅 비용이 폭발하는 경험 있으신가요? Vercel은 대역폭 100GB, Render는 15분 유휴 시 슬립, Firebase는 하루 360MB 제한입니다. MVP 단계에서 비용 걱정 없이 운영할 수 있는 플랫폼이 필요했습니다.

Cloudflare 스택으로 이 문제를 해결했습니다.

```
┌──────────┐     ┌──────────┐     ┌───────────┐     ┌──────────┐
│  Browser  │────▶│  Pages   │────▶│  Workers  │────▶│  D1 / R2 │
│  (사용자) │     │ (Next.js)│     │  (API)    │     │ (DB/파일) │
└──────────┘     └──────────┘     └───────────┘     └──────────┘
                      │                  │
                      │    ┌─────────────┘
                      ▼    ▼
                 ┌──────────────┐
                 │ Email Sending │
                 │   (이메일)    │
                 └──────────────┘
```

## 1단계: 호스팅 플랜 선택 — 10개 플랜 비교

무료 호스팅 후보 10개를 비교했습니다. 핵심 5개만 표로 정리합니다.

| 플랫폼 | 비용 | 대역폭 | DB | Next.js | 백엔드 |
|---|---|---|---|---|---|
| **Vercel** | $0 | 100 GB/월 | 외부 연결 | 최적 (1st party) | Serverless Functions |
| **Netlify** | $0 | 300 크레딧 | Netlify DB | 지원 | Netlify Functions |
| **Cloudflare** | $0 | **무제한** | D1/KV/R2 | 지원 (`@opennextjs/cloudflare`) | **Workers** |
| **Render** | $0 | 5 GB/월 | PostgreSQL (30일) | 지원 | Web Services |
| **Firebase** | $0 | 360 MB/일 | Firestore (내장) | App Hosting | Cloud Functions |

**추천 조합:**

| 상황 | 추천 |
|---|---|
| 빠른 시작 + 검증된 조합 | Vercel + Supabase |
| 최대 비용 절감 + 한국 성능 | **Cloudflare Pages + Workers + D1** |
| 한국 리전 백엔드 필수 | GCP Cloud Run + Firebase |

## 2단계: Cloudflare Pages에 Next.js 올리기

기존 `@cloudflare/next-on-pages`는 **deprecated** 되었습니다. `@opennextjs/cloudflare`를 사용합니다.

```bash
npm create cloudflare@latest -- my-next-app --framework=next
```

**wrangler.jsonc:**

```jsonc
{
  "main": ".open-next/worker.js",
  "name": "my-app",
  "compatibility_date": "2026-06-02",
  "compatibility_flags": ["nodejs_compat"],
  "assets": {
    "directory": ".open-next/assets",
    "binding": "ASSETS"
  }
}
```

**package.json scripts:**

```json
{
  "preview": "opennextjs-cloudflare build && opennextjs-cloudflare preview",
  "deploy": "opennextjs-cloudflare build && opennextjs-cloudflare deploy"
}
```

**Pages 무료 티어:**

| 항목 | Free | Pro |
|---|---|---|
| 월 빌드 수 | 500 | 5,000 |
| 빌드 타임아웃 | 20분 | 20분 |
| 커스텀 도메인 | 100/프로젝트 | 250 |
| Preview 배포 | 무제한 | 무제한 |

`npm run dev`는 Node.js 런타임, `npm run preview`는 workerd 런타임에서 실행됩니다. 배포 전 로컬에서 실제 환경과 동일하게 테스트해보세요.

## 3단계: Workers로 API 만들기

[Hono](https://hono.dev/)는 Workers에 최적화된 경량 프레임워크입니다. 익스프레스와 비슷한 문법으로 빠르게 API를 작성할 수 있습니다.

```ts
import { Hono } from 'hono'
import { cors } from 'hono/cors'

const app = new Hono()

app.use('/api/*', cors({
  origin: ['https://example.com'],
  allowMethods: ['GET', 'POST', 'PUT', 'DELETE'],
}))

app.get('/api/users', async (c) => {
  const results = await c.env.DB.prepare('SELECT * FROM users').all()
  return c.json(results)
})

app.post('/api/users', async (c) => {
  const { name, email } = await c.req.json()
  await c.env.DB.prepare(
    'INSERT INTO users (name, email) VALUES (?, ?)'
  ).bind(name, email).run()
  return c.json({ success: true }, 201)
})

export default app
```

### 크론 트리거 (스케줄링)

주기적 데이터 수집이나 리포트 생성에 크론 트리거를 활용합니다. 별도 서버 없이 Workers 하나로 스케줄링이 가능합니다.

**wrangler.jsonc:**

```jsonc
{
  "triggers": {
    "crons": ["0 */6 * * *", "0 9 * * mon-fri"]
  }
}
```

**Worker 코드:**

```ts
export default {
  async scheduled(controller, env, ctx) {
    const data = await fetchDataFromAPI(env.API_KEY)
    await storeData(env.DB, data)
  },
  async fetch(request, env, ctx) {
    return new Response('OK')
  }
}
```

<details>
<summary>📖 크론 로컬 테스트 명령어 보기</summary>

```bash
curl "http://localhost:8787/cdn-cgi/handler/scheduled?cron=0+*/6+*+*+*"
```

로컬 개발 서버(`wrangler dev`) 실행 후 위 명령어로 크론 핸들러를 직접 호출할 수 있습니다.

</details>

| 항목 | Free | Paid |
|---|---|---|
| 크론 트리거 | 5/계정 | 250/계정 |
| CPU 시간 | 10 ms | 30초 |
| Wall time | 15분 | 15분 |

무료 플랜은 **CPU 10ms 제한**이 있습니다. 무겁지 않은 API와 캐싱 전략으로 극복해야 합니다.

## 4단계: D1 데이터베이스 + Drizzle ORM

D1은 Cloudflare의 SQLite 기반 데이터베이스입니다. Workers와 네이티브로 연결되어 별도 커넥션 풀 없이 사용할 수 있습니다.

### DB 생성 및 마이그레이션

```bash
npx wrangler d1 create my-database
npx wrangler d1 migrations create my-database init_schema
npx wrangler d1 migrations apply my-database --remote
```

**스키마 예시 (Drizzle ORM):**

```ts
import { sqliteTable, text, integer } from 'drizzle-orm/sqlite-core'

export const users = sqliteTable('users', {
  id: integer('id').primaryKey({ autoIncrement: true }),
  name: text('name').notNull(),
  email: text('email').notNull().unique(),
  createdAt: text('created_at').default(sql`(datetime('now'))`),
})
```

**Worker에서 Drizzle 사용:**

```ts
import { drizzle } from 'drizzle-orm/d1'
import * as schema from './schema'

export default {
  async fetch(request, env) {
    const db = drizzle(env.DB, { schema })
    const allUsers = await db.select().from(schema.users).all()
    return Response.json(allUsers)
  }
}
```

<details>
<summary>📖 마이그레이션 SQL 전체 보기</summary>

```sql
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  email TEXT UNIQUE NOT NULL,
  created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX idx_users_email ON users(email);
```

인덱스 생성이 필수입니다. D1은 싱글스레드이므로 평균 쿼리 1ms 기준 약 1,000 QPS입니다. 인덱스 없으면 급격히 느려집니다.

</details>

## 5단계: R2 파일 스토리지

R2는 S3 호환 객체 스토리지입니다. 핵심 차이는 **Egress가 무료**라는 점입니다.

```bash
npx wrangler r2 bucket create my-assets
```

**업로드/조회 코드:**

```ts
await env.BUCKET.put('images/photo.jpg', fileBody)

const obj = await env.BUCKET.get('images/photo.jpg')
return new Response(obj.body, {
  headers: { 'Content-Type': obj.httpMetadata.contentType }
})
```

| 항목 | 무료 | 유료 |
|---|---|---|
| 스토리지 | 10 GB/월 | $0.015/GB |
| 쓰기 (Class A) | 100만/월 | $4.50/백만 |
| 읽기 (Class B) | 1,000만/월 | $0.36/백만 |
| **Egress** | **무료** | **무료** |

S3는 데이터 전송량별로 과금되지만, R2는 아웃바운드가 무료입니다. 이미지 호스팅에 최적입니다. 커스텀 도메인 연결 시 CDN 캐싱 + 무료 egress가 함께 적용됩니다.

## 6단계: 이메일 발송 (API 키 없이)

Cloudflare Email Sending을 사용하면 외부 서비스 API 키 없이 Workers에서 직접 이메일을 발송할 수 있습니다. SendGrid나 Mailgun 계정이 필요 없습니다.

### 설정 3단계

1. **Email Sending 활성화**: Dashboard → Compute → Email Service → Email Sending → 도메인 Onboard
2. **Email Routing 활성화**: Dashboard → 도메인 → Email → Email Routing 활성화
3. **wrangler.toml 설정**: `[[send_email]]` 바인딩 추가

**wrangler.toml:**

```toml
name = "my-worker"
main = "src/index.ts"
compatibility_date = "2026-06-02"
compatibility_flags = ["nodejs_compat"]

[[send_email]]
name = "EMAIL"

[triggers]
crons = ["0 0 * * *"]
```

핵심은 `[[send_email]]` 바인딩입니다. 이 설정만 있으면 Workers 코드에서 `env.EMAIL.send()`로 이메일을 발송할 수 있습니다.

**발송 코드:**

```ts
async function sendEmail(emailBinding, toEmail, subject, html) {
  await emailBinding.send({
    to: toEmail,
    from: { email: 'noreply@example.com', name: 'My Service' },
    subject,
    html,
    text: '알림',
  })
}
```

발송 대상 이메일은 **미리 인증**해야 합니다. Dashboard에서 관리하거나 API로 인증 이메일을 발송합니다. 새 구독자가 늘어나면 Dashboard에서 한 번에 관리할 수 있습니다.

### 트러블슈팅

| 증상 | 원인 | 해결 |
|---|---|---|
| 이메일이 안 옴 | 발송 대상 미인증 | Email Routing에서 대상 주소 인증 |
| 스팸함에 들어감 | SPF/DKIM 전파 대기 | 최대 48시간 후 정상화 |
| Internal Server Error | Email Sending 미활성화 | Dashboard에서 도메인 Onboard |
| destination not verified | 발송 대상 미인증 | 인증 이메일 재발송 |
| 빈 이메일 수신 | HTML 본문 누락 | `html` 파라미터 확인 |

## 7단계: CI/CD 파이프라인

GitHub Actions로 main 브랜치 푸시 시 자동 배포합니다. 별도 CI 서버 없이 GitHub 무료 티어로 충분합니다.

```yaml
name: Deploy to Cloudflare
on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 20
      - run: npm ci
      - run: npx wrangler deploy
        env:
          CLOUDFLARE_API_TOKEN: ${{ secrets.CLOUDFLARE_API_TOKEN }}
```

<details>
<summary>📖 D1 마이그레이션 포함 전체 워크플로우 보기</summary>

```yaml
name: Deploy to Cloudflare
on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 20
      - run: npm ci
      - name: Run D1 Migrations
        run: npx wrangler d1 migrations apply my-database --remote
        env:
          CLOUDFLARE_API_TOKEN: ${{ secrets.CLOUDFLARE_API_TOKEN }}
      - name: Build & Deploy
        run: npx wrangler deploy
        env:
          CLOUDFLARE_API_TOKEN: ${{ secrets.CLOUDFLARE_API_TOKEN }}
```

API Token은 Dashboard → My Profile → API Tokens에서 `Edit Cloudflare Workers` 템플릿으로 생성합니다. 생성한 토큰을 GitHub 저장소 Settings → Secrets에 `CLOUDFLARE_API_TOKEN` 이름으로 등록합니다.

</details>

**PR 미리보기**: Pages 프로젝트는 PR 생성 시 자동으로 `<hash>.<project>.pages.dev` URL이 생성됩니다. 별도 설정 없이 무제한 preview 배포가 가능합니다.

## 무료 티어 전체 한도

| 서비스 | 무료 한도 | 비고 |
|---|---|---|
| **Workers** | 10만 요청/일, CPU 10ms | 정적 에셋은 무제한 무료 |
| **Pages** | 500 빌드/월, 무제한 Preview | **무제한 대역폭** |
| **D1** | 500만 읽기/일, 10만 쓰기/일, 5GB | 인덱스 필수 |
| **R2** | 10GB, 100만 쓰기/월 | **Egress 무료** |
| **KV** | 10만 읽기/일, 1천 쓰기/일 | 캐싱용으로 충분 |
| **Cron** | 5개/계정 | 스케줄 작업용 |

월 $5 유료 전환 시 요청 무제한, CPU 30초/요청, D1 250억 읽기/월이 포함됩니다. 대규모 트래픽이 발생하면 유료 전환만으로 확장할 수 있습니다.

## Result

| 항목 | 기존 (Vercel + Supabase) | Cloudflare 스택 |
|---|---|---|
| 월 호스팅 비용 | $0 (제한 내) | **$0 (무제한 대역폭)** |
| 대역폭 제한 | 100 GB/월 | **무제한** |
| DB 용량 | PostgreSQL 500MB | SQLite 5GB |
| 이메일 발송 | 외부 API 키 필요 | **내장 Email Sending** |
| 스케줄링 | Vercel Cron | **Cron Triggers (5개)** |
| 한국 CDN | 글로벌만 | **한국 PoP** |

## Takeaway

1. **무제한 대역폭이 핵심입니다** — Cloudflare만이 무료로 무제한 대역폭을 제공합니다. 트래픽 증가를 걱정하지 않아도 됩니다
2. **Email Sending으로 외부 의존성을 줄입니다** — `send_email` 바인딩만으로 Workers에서 이메일 발송이 가능합니다. API 키 관리 부담이 없습니다
3. **CPU 10ms 제한을 반드시 인지해야 합니다** — 무료지만 CPU 시간 제한이 있습니다. 가벼운 API와 캐싱 전략으로 극복합니다
