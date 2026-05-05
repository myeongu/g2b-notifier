"""
나라장터 입찰공고 모니터링 설정 파일

[설정 순서]
1. API_KEY: data.go.kr에서 발급받은 Decoding 키
2. KEYWORDS: 모니터링할 키워드 리스트
3. 알림 방법 선택 후 해당 토큰/URL 입력
"""

import os

# ──────────────────────────────────────────────
# 1. 공공데이터포털 API 키 (필수)
# ──────────────────────────────────────────────
# 로컬: 아래 기본값 사용 / GitHub Actions: Secrets → API_KEY
API_KEY = os.getenv("API_KEY")


# ──────────────────────────────────────────────
# 2. 모니터링 키워드 (필수)
# ──────────────────────────────────────────────
# 공고명에 아래 키워드 중 하나라도 포함되면 알림 대상
KEYWORDS = [
    "관리이행계획",
    "관리이행",
    "이행계획",
    "이행관리",
    "이행점검",
    "관리계획",
    # ──── 필요시 추가 키워드 ────
    # "유지관리",
    # "시설관리",
    # "위탁운영",
]


# ──────────────────────────────────────────────
# 3. 알림 방법 선택 (필수)
# ──────────────────────────────────────────────
# "telegram" | "slack" | "both" | "console"
NOTIFY_METHOD = "telegram"


# ──────────────────────────────────────────────
# 4-A. Telegram 설정 (NOTIFY_METHOD가 telegram/both일 때)
# ──────────────────────────────────────────────
# 로컬: 아래 기본값 사용 / GitHub Actions: Secrets → TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


# ──────────────────────────────────────────────
# 4-B. Slack 설정 (NOTIFY_METHOD가 slack/both일 때)
# ──────────────────────────────────────────────
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/YOUR/WEBHOOK/URL")


# ──────────────────────────────────────────────
# 5. 기타 설정
# ──────────────────────────────────────────────
# 조회 기간: 현재 시각 기준 N시간 전까지의 공고를 조회
# 하루 1회 실행 기준, 25시간으로 설정해 누락 방지
CHECK_HOURS = 25

# SQLite DB 파일 경로
DB_PATH = "notified_bids.db"

# 로그 레벨: DEBUG | INFO | WARNING | ERROR
LOG_LEVEL = "INFO"
