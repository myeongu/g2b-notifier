# 나라장터 용역 입찰공고 모니터링

나라장터 용역 입찰공고 중 **"관리이행계획"** 관련 키워드가 포함된 공고를 자동으로 감지하여 Telegram/Slack으로 알림을 보내는 스크립트입니다.

## 구조

```
g2b_monitor/
├── bid_monitor.py          # 메인 스크립트
├── config.py               # 설정 파일 (API 키, 키워드, 알림 설정)
├── requirements.txt        # Python 의존성
├── notified_bids.db        # (자동 생성) 알림 이력 DB
├── bid_monitor.log         # (자동 생성) 실행 로그
└── .github/
    └── workflows/
        └── bid_monitor.yml # GitHub Actions 스케줄링
```

## 빠른 시작

### 1단계: API 키 발급

1. [공공데이터포털](https://www.data.go.kr) 가입
2. **"조달청 나라장터 입찰공고정보서비스"** 검색 → 활용 신청
3. 마이페이지 → 인증키 발급현황 → **Decoding 키** 복사

### 2단계: 알림 채널 설정 (택 1)

**Telegram (추천 — 모바일 푸시 알림)**

1. Telegram에서 `@BotFather` 검색 → `/newbot` → 봇 이름 입력 → **토큰** 복사
2. 생성된 봇에게 아무 메시지 전송
3. 브라우저에서 `https://api.telegram.org/bot{토큰}/getUpdates` 접속
4. 응답에서 `"chat": {"id": 123456789}` 의 숫자가 **Chat ID**

**Slack**

1. [Slack API](https://api.slack.com/apps) → Create New App → Incoming Webhooks 활성화
2. 채널 선택 → **Webhook URL** 복사

### 3단계: 설정 입력

`config.py`를 열어 아래 항목을 수정:

```python
API_KEY = "발급받은_Decoding_키"
NOTIFY_METHOD = "telegram"  # 또는 "slack", "both", "console"
TELEGRAM_TOKEN = "봇_토큰"
TELEGRAM_CHAT_ID = "챗_ID"
```

### 4단계: 실행

```bash
pip install requests
python bid_monitor.py
```

## 키워드 커스터마이징

`config.py`의 `KEYWORDS` 리스트를 수정하여 모니터링 범위를 조절합니다:

```python
KEYWORDS = [
    "관리이행계획",    # 정확한 키워드
    "관리이행",        # 부분 매칭
    "이행계획",        # 부분 매칭
    "이행관리",        # 유사 키워드
    "이행점검",        # 관련 키워드
    # "유지관리",      # 필요시 주석 해제
]
```

> **팁**: 처음에는 `CHECK_HOURS = 168` (7일)로 설정하고 `NOTIFY_METHOD = "console"`로 실행하면, 최근 일주일 공고 중 매칭되는 것을 미리 확인할 수 있습니다.

## 자동 스케줄링

### 방법 A: GitHub Actions (서버 불필요, 추천)

1. GitHub 리포지토리 생성 후 코드 push
2. Settings → Secrets → 아래 시크릿 추가:
   - `G2B_API_KEY`
   - `TELEGRAM_TOKEN`
   - `TELEGRAM_CHAT_ID`
3. 평일 09/12/15/18시(KST)에 자동 실행됨
4. Actions 탭에서 수동 실행(workflow_dispatch)도 가능

### 방법 B: cron (리눅스/맥 서버)

```bash
# crontab -e
# 평일 매 3시간마다 실행
0 9,12,15,18 * * 1-5 cd /path/to/g2b_monitor && python3 bid_monitor.py
```

### 방법 C: Windows 작업 스케줄러

```
schtasks /create /tn "G2B_Monitor" /tr "python C:\path\to\bid_monitor.py" /sc hourly /mo 3
```

## 동작 흐름

```
[cron / GitHub Actions]
        │
        ▼
  bid_monitor.py 실행
        │
        ▼
  나라장터 API 호출 (용역 공고 목록)
        │
        ▼
  키워드 필터링 ("관리이행계획" 등)
        │
        ▼
  SQLite 중복 체크 (이전 알림 건 제외)
        │
        ▼
  알림 발송 (Telegram / Slack)
```

## 참고 사항

- **API 호출 한도**: data.go.kr 기본 일일 1,000회. 3시간 간격이면 하루 약 5~8회 호출이므로 충분
- **공고 누락 방지**: `CHECK_HOURS`를 cron 주기보다 넉넉하게 설정 (예: 3시간 간격 → CHECK_HOURS=6)
- **DB 초기화**: `notified_bids.db` 삭제 후 재실행하면 모든 공고를 새 공고로 인식
- **API 버전**: `BidPublicInfoService04` (2024년 기준 최신 버전) 사용. 조달청 API 버전이 변경되면 엔드포인트 URL 업데이트 필요
