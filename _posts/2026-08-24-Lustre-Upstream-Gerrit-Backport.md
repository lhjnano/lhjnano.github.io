---
layout: post
title: "Lustre 업스트림 기여 가이드: Gerrit과 Jira를 통과하는 법"
categories: [OpenSource, Storage]
description: Lustre는 GitHub PR을 받지 않습니다. Gerrit 승인 관문과 Jira 에티켓까지, 실제 백포트 제출로 익힌 기여 절차 전체입니다.
keywords: [Lustre, Gerrit, Jira, 백포트, 업스트림 기여, whamcloud]
toc: true
toc_sticky: true
---

Lustre에 패치를 올리려면 GitHub이 아니라 Gerrit과 Jira를 지나야 합니다. 이 글은 그 두 시스템을 실제로 통과하며 익힌 기여 절차의 전체 지도입니다.

2026-08, 운영 중인 2.15 기반 시스템에서 발견한 쿼터 교착(LU-17115)이 이미 upstream master에 수정돼 있음을 확인하고, 그 백포트를 Gerrit change 68270으로 직접 제출한 과정을 예시로 사용합니다. 이슈 자체의 분석보다 **어떻게 확인하고, 어떻게 제출하고, 어떻게 대화하는가**가 이 글의 목적입니다.

## TL;DR

- 제출 창구는 **Gerrit(review.whamcloud.com, 포트 29418)**뿐입니다. GitHub 저장소는 읽기 전용 미러입니다.
- 패치를 쓰기 전에 **"upstream이 이미 고쳤는가"를 6단계로 확인**합니다. 이미 고쳐졌다면 백포트가 가장 싼 기여입니다.
- 첫 push는 `Upload denied`로 거부됩니다. **설정 오류가 아니라 승인 관문**이며, info@whamcloud.com에 메일 한 통으로 뚫립니다.
- 백포트 커밋은 **원저자 유지 + Lustre-change/Lustre-commit 트레일러**가 관례입니다.
- 재제출은 새 change가 아니라 **amend 후 같은 refspec으로 patchset 추가**입니다.

## 절차 전체 그림

확인부터 Jira 코멘트까지 다섯 단계입니다. 2단계 승인 관문만 빨간색입니다. 나머지는 준비된 절차입니다.

<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 840 540" font-family="'Segoe UI','Noto Sans KR',system-ui,sans-serif" role="img" aria-label="Lustre 백포트 기여 절차 5단계 세로 플로우: 업스트림 확인 6단계, 승인 관문, 백포트 커밋, refs/for push, Jira 코멘트와 patchset">
  <defs>
    <marker id="lu-flow-arrow" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto" markerUnits="strokeWidth">
      <path d="M0,0 L0,6 L9,3 z" fill="#666666"/>
    </marker>
    <marker id="lu-flow-arrow-red" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto" markerUnits="strokeWidth">
      <path d="M0,0 L0,6 L9,3 z" fill="#dc2626"/>
    </marker>
  </defs>
  <text x="420" y="28" text-anchor="middle" font-size="15" font-weight="700" fill="#2c3e50">Lustre 업스트림 기여, 다섯 단계의 관문</text>

  <line x1="400" y1="120" x2="400" y2="148" stroke="#dc2626" stroke-width="1.5" stroke-dasharray="4,3" opacity="0.6" marker-end="url(#lu-flow-arrow-red)"/>
  <line x1="400" y1="218" x2="400" y2="246" stroke="#666666" stroke-width="1.5" stroke-dasharray="4,3" opacity="0.5" marker-end="url(#lu-flow-arrow)"/>
  <line x1="400" y1="316" x2="400" y2="344" stroke="#666666" stroke-width="1.5" stroke-dasharray="4,3" opacity="0.5" marker-end="url(#lu-flow-arrow)"/>
  <line x1="400" y1="414" x2="400" y2="442" stroke="#666666" stroke-width="1.5" stroke-dasharray="4,3" opacity="0.5" marker-end="url(#lu-flow-arrow)"/>

  <rect x="130" y="52" width="540" height="68" rx="8" fill="#fef3c7" stroke="#fbbf24" stroke-width="1.5"/>
  <circle cx="165" cy="86" r="13" fill="#fbbf24"/>
  <text x="165" y="90" text-anchor="middle" font-size="11" font-weight="700" fill="white">1</text>
  <text x="192" y="81" font-size="13" font-weight="700" fill="#92400e">1단계: 업스트림 확인 6단계</text>
  <text x="192" y="102" font-size="11" fill="#2c3e50">.gitreview → 상위 브랜치 대조 → Gerrit change → 우리 브랜치 반영 여부</text>

  <rect x="130" y="150" width="540" height="68" rx="8" fill="#fef2f2" stroke="#dc2626" stroke-width="1.7"/>
  <circle cx="165" cy="184" r="13" fill="#dc2626"/>
  <text x="165" y="188" text-anchor="middle" font-size="11" font-weight="700" fill="white">2</text>
  <text x="192" y="179" font-size="13" font-weight="700" fill="#dc2626">2단계: 승인 관문</text>
  <text x="192" y="200" font-size="11" fill="#2c3e50">Upload denied → info@whamcloud.com 메일 요청 → external-users 등록</text>

  <rect x="130" y="248" width="540" height="68" rx="8" fill="#f0f4f8" stroke="#666666" stroke-width="1.5"/>
  <circle cx="165" cy="282" r="13" fill="#666666"/>
  <text x="165" y="286" text-anchor="middle" font-size="11" font-weight="700" fill="white">3</text>
  <text x="192" y="277" font-size="13" font-weight="700" fill="#666666">3단계: 백포트 커밋</text>
  <text x="192" y="298" font-size="11" fill="#2c3e50">원저자 유지 + Lustre-change/Lustre-commit 트레일러</text>

  <rect x="130" y="346" width="540" height="68" rx="8" fill="#ede9fe" stroke="#7c3aed" stroke-width="1.5"/>
  <circle cx="165" cy="380" r="13" fill="#7c3aed"/>
  <text x="165" y="384" text-anchor="middle" font-size="11" font-weight="700" fill="white">4</text>
  <text x="192" y="375" font-size="13" font-weight="700" fill="#7c3aed">4단계: refs/for push</text>
  <text x="192" y="396" font-size="11" fill="#2c3e50">refs/for/b2_15 push → change 68270, MAINTAINERS 기반 리뷰어 자동 지정</text>

  <rect x="130" y="444" width="540" height="68" rx="8" fill="#dcfce7" stroke="#16a34a" stroke-width="1.5"/>
  <circle cx="165" cy="478" r="13" fill="#16a34a"/>
  <text x="165" y="482" text-anchor="middle" font-size="11" font-weight="700" fill="white">5</text>
  <text x="192" y="473" font-size="13" font-weight="700" fill="#16a34a">5단계: Jira 코멘트와 patchset</text>
  <text x="192" y="494" font-size="11" fill="#2c3e50">맥락 코멘트, 재제출은 amend로 patchset 추가</text>

  <text x="420" y="532" text-anchor="middle" font-size="10" fill="#8b949e">빨간 관문(2단계)만 예측 불가입니다. 승인 요청을 1단계 직후 먼저 보내면 기다림이 줄어듭니다.</text>
</svg>

## 1단계: 확인 6단계

1~4번은 "upstream에 고쳐졌는가", 5~6번은 "우리 브랜치에 왔는가"입니다. master에 있다고 LTS에 있는 게 아닙니다.

| 순서 | 확인 | 수단 | 결과 |
|---|---|---|---|
| 1 | 기여 체계 | `cat .gitreview` | Gerrit(:29418) |
| 2 | 상위 브랜치 함수 | 얕은 fetch 후 비교 | b2_16 수정됨 |
| 3 | 파일 커밋 이력 | 미러 API | 수정 커밋 존재 |
| 4 | LU 번호 특정 | 커밋 검색 | LU-17115 |
| 5 | 브랜치별 change | `message:LU-17115` | b2_15 없음 |
| 6 | 우리 브랜치 반영 | `git log --grep` | 미반영 = 누락 |

```bash
# 1) 기여 체계 확인. Gerrit인가 GitHub인가
cat .gitreview

# 2) 상위 브랜치를 얕게 가져와 해당 함수를 직접 비교
git fetch --depth=1 origin master:refs/remotes/origin/master b2_16:refs/remotes/origin/b2_16
git show origin/b2_16:lustre/quota/qmt_handler.c | grep -nE 'lqe_write_lock|dt_trans_stop'

# 3) 그 파일을 고친 커밋 이력. GitHub 미러 API를 조회용으로 쓴다
curl -s "https://api.github.com/repos/lustre/lustre-release/commits?path=lustre/quota/qmt_handler.c&sha=b2_16&per_page=25"

# 4) LU 번호로 커밋 특정
curl -s "https://api.github.com/search/commits?q=repo:lustre/lustre-release+LU-17115"

# 5) 그 LU 번호로 올라온 Gerrit change 전체. 브랜치별 상태를 본다
curl -s "https://review.whamcloud.com/changes/?q=message:LU-17115" | tail -c +6

# 6) 우리 브랜치에 반영됐는지
git fetch --depth=400 origin b2_15:refs/remotes/origin/b2_15
git log --oneline --grep='LU-17115' origin/b2_15      # 출력 없음 = 미반영
```

> **Gerrit REST는 `)]}'`로 시작합니다**(XSSI 방어). `tail -c +6`으로 자릅니다.

### 판정

예시 사례의 결과입니다. master와 다음 LTS에는 수정이 있고 2.15 LTS에만 없었습니다.

| 브랜치 | 해당 함수 수정 여부 | 판정 |
|---|---|---|
| master (2.17) | 수정됨 | 백포트 원본 존재 |
| b2_16 | 수정됨 | 참조 대상 |
| b2_15 = 2.15 LTS | 미수정 | **백포트 대상** |

확인 결과가 이 표와 같다면 새 패치를 쓰지 말고 백포트로 갑니다. 수정은 이미 리뷰를 통과한 검증된 코드이기 때문입니다. 그런데 왜 2.15에는 아직 없을까요? 답은 Jira에 있습니다.

### 왜 2.15에는 오지 않았나

답은 Jira 필드에 있었습니다. 우선도 **Minor**, **Affects Version 비어 있음**, Fix Version 2.16.0, "backport" 언급 **0건**. 기각이 아니라 안건에 오른 적이 없습니다. 보고자가 담당자 본인이라 밀어줄 사람이 없었고, **Affects Version이 비면 선별에 아예 걸리지 않습니다.**

### 누락 입증

"정책적으로 뺀 것"이라는 반론은, 더 나중 백포트의 b2_15 병합 여부로 닫습니다.

| quota 백포트 | b2_15 병합 |
|---|---|
| LU-17974 quota: fix qmt_pool_lqes_lookup_spec | 2024-11-13 |
| LU-18516 quota: use wait_woken for qsd_op_begin0() | 2025-02-22 |
| LU-17115 quota: fix race of acquiring locks in qmt | **없음** |

나중 번호가 들어왔는데 17115만 빠졌습니다. 배제가 아니라 누락이라는 가장 강한 논거입니다. 이 대조표는 그대로 Jira 코멘트의 재료가 됩니다(5단계). 남은 일은 올리는 것인데, 창구가 GitHub에 없었습니다.

## 2단계: 기여 체계, GitHub PR이 아니라 Gerrit

`github.com/lustre/lustre-release`는 **읽기 전용 미러**라 PR을 받지 않습니다. 창구는 `.gitreview`가 알려 줍니다.

```
[gerrit]
host=review.whamcloud.com
port=29418
project=fs/lustre-release.git
defaultbranch=b2_15          # 2.15 LTS가 기본 타깃
```

이슈 추적 jira.whamcloud.com은 **자체 가입 불가**입니다. 커밋은 `LU-xxxxx` 제목과 `Signed-off-by:`(DCO), `Change-Id:`(commit-msg 훅), checkpatch 통과를 요구합니다. 창구는 찾았지만 첫 push는 거부됐습니다.

## 3단계: Upload denied는 승인 문제

계정은 OpenID로 만듭니다. Username **변경 불가**, Email은 **커밋 이메일과 일치**, 전용 키·**포트 29418**입니다.

```bash
ssh review.whamcloud.com gerrit version
# → gerrit version 3.11.3. 연결은 정상
# 그런데도 push하면: Upload denied for project 'fs/lustre-release'
```

Gerrit 3.11.3이 정상 응답해도 push가 거부됩니다. **설정이 아니라 승인 문제**입니다. 문서에 잘 안 보이는 스팸 방지 관문이라, **info@whamcloud.com에 username·실명·이메일·패치 성격을 적어 요청**합니다. 승인은 external-users 등록이고 제 경우 다음날 됐습니다. 기다림을 줄이려면 **승인 요청을 백포트할 것이 확정된 시점에 먼저** 보냅니다. Jira 계정도 같이 요청하면 왕복이 줄어듭니다.

```bash
ssh review.whamcloud.com gerrit ls-groups   # 승인 전에는 빈 출력
```

관문을 지나면 백포트 커밋이 남습니다.

## 4단계: 백포트 커밋, 원저자와 출처를 유지한다

백포트는 새 패치가 아닙니다. **원저자를 유지하고** 트레일러로 출처를 밝힙니다. 관례는 병합된 백포트 `0466a04`를 읽어 확인했고, 원본은 Gerrit change 52371입니다.

```
author: Li Xi <lixi@ddn.com>                           # 원저자 유지
...
Lustre-change: https://review.whamcloud.com/45904      # 원본 Gerrit change
Lustre-commit: 0688719a51d9c659399439535c5c3f8c66a7b577 # 원본 커밋 sha
Signed-off-by: Li Xi <lixi@ddn.com>
Signed-off-by: Lai Siyao <lai.siyao@whamcloud.com>
Change-Id: Ife39d539921a37994f9c6046ae066e1927154136
Signed-off-by: Etienne AUJAMES <eaujames@ddn.com>      # 백포터
```

author는 원저자, 백포터는 자기 `Signed-off-by:`를 추가합니다.

### 부분 백포트 사유

원본은 `qmt_reset_qid`까지 고쳤는데 그 함수는 2.16 신규 기능이라 2.15.8에 없습니다. 그 hunk는 빼고 **사유를 남겼습니다.** 결과는 b2_16과 diff해 구조가 같은지 봅니다.

```
The qmt_reset_qid hunk of the original patch is omitted here,
as that function was introduced after b2_15 and does not exist
in this branch.  Only qmt_delete_qid is affected on b2_15.
```

```bash
awk '/^static int qmt_delete_qid/,/^}/' lustre/quota/qmt_handler.c > ours.txt
git show origin/b2_16:lustre/quota/qmt_handler.c \
  | awk '/^static int qmt_delete_qid/,/^}/' > ref.txt
diff -u ref.txt ours.txt
```

### 트레일러 순서와 checkpatch 오탐

commit-msg 훅은 `Change-Id`를 `Signed-off-by` **앞에** 넣는데 `checkpatch.pl`이 무조건 잡습니다(커널 규칙 잔재). **S-o-b → Change-Id 순**으로 재배치하면 사라집니다. 남은 ERROR는 **병합된 커밋에 같은 검사를 돌려** 판별합니다. `commit <12+ chars of sha1>`은 `Lustre-commit:` sha를 오인하는 오탐입니다. **+2/−3**, checkpatch 통과, b2_16과 구조 일치였습니다. 이제 리뷰 큐로 올립니다.

## 5단계: refs/for push와 Jira 코멘트

push는 `refs/for/<branch>` refspec으로 리뷰 큐에 올립니다.

```bash
git remote add gerrit ssh://review.whamcloud.com/fs/lustre-release.git
git push gerrit lu-17115-b2_15:refs/for/b2_15
# remote: SUCCESS
# remote:   https://review.whamcloud.com/c/fs/lustre-release/+/68270
# remote:     LU-17115 quota: fix race of acquiring locks in qmt [NEW]
```

Gerrit이 `MAINTAINERS`와 이력으로 리뷰어를 자동 지정했는데 **원저자 Hongchao Zhang였습니다.** `Verified`엔 Jenkins/Maloo 결과가 들어오고 무관한 실패엔 `recheck` 코멘트입니다. 재제출은 `--amend` 후 같은 refspec으로 patchset 추가입니다.

```bash
git commit --amend             # Change-Id 유지
git push gerrit lu-17115-b2_15:refs/for/b2_15   # 기존 change에 patchset 추가
```

### Jira 코멘트 5가지

왜 오래된 티켓에 새 patch가 붙었는지 **맥락은 기여자가 써야 합니다.**

1. **백포트 change 링크**
2. **누락 정황.** 더 나중 LU 번호(17974, 18516)가 b2_15에 들어왔다는 대조
3. **Affects Version 기입 요청.** 선별에 걸리는 핵심
4. **원 보고에 없던 변종.** osd-zfs에서도 같은 교착이 성립
5. **재현 조건과 환경 버전.** 단일 변수 A/B가 가장 설득력 있음

external-users 계정엔 `versions`·`priority` 편집 권한이 있지만(`editmeta` 확인) **직접 고치지 않고 코멘트로 요청했습니다.** 남의 티켓을 고치면 월권입니다.

### 식별자 위생

커밋과 Jira 코멘트는 **영구 공개 기록**입니다. 회사명·제품명·호스트명·IP·내부 이슈번호는 빼고 주어를 커널 객체(`MDT pool`, `quota request`)로 잡으면 버그 관찰 기록이 됩니다. 다만 "회복이 노드 리셋뿐"이라는 신호는 재검토 근거라 남깁니다.
