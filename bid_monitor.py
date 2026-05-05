"""
나라장터 용역 입찰공고 모니터링 스크립트
- 대상: 용역 입찰공고 중 "관리이행계획" 관련 키워드 포함 공고
- 알림: Telegram Bot / Slack Webhook (선택)
- 중복방지: SQLite 기반
- 스케줄링: cron / GitHub Actions / 직접 실행

[사전 준비]
1. data.go.kr 가입 → "조달청 나라장터 입찰공고정보서비스" API 신청
2. 발급받은 서비스키(Decoding)를 config.py에 입력
3. Telegram Bot 또는 Slack Webhook 설정 후 config.py에 입력
4. pip install requests  (기본 라이브러리 외 추가 설치 필요 없음)
"""

import requests
import sqlite3
import json
import logging
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from urllib.parse import quote_plus
from pathlib import Path

from config import (
    API_KEY,
    KEYWORDS,
    NOTIFY_METHOD,
    TELEGRAM_TOKEN,
    TELEGRAM_CHAT_ID,
    SLACK_WEBHOOK_URL,
    DB_PATH,
    CHECK_HOURS,
    LOG_LEVEL,
)

# ──────────────────────────────────────────────
# 로깅 설정
# ──────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(Path(__file__).parent / "bid_monitor.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# 1. API 호출 (용역 입찰공고 목록 조회)
# ──────────────────────────────────────────────

# 용역 입찰공고 엔드포인트 (일반용역 + 기술용역 모두 포함)
ENDPOINTS = {
    "용역": "https://apis.data.go.kr/1230000/ad/BidPublicInfoService",
}


def fetch_bids(from_dt: str, to_dt: str, endpoint_name: str = "용역") -> list:
    """
    나라장터 API에서 입찰공고 목록을 조회합니다.

    Args:
        from_dt: 조회 시작일시 (yyyyMMddHHmm)
        to_dt:   조회 종료일시 (yyyyMMddHHmm)
        endpoint_name: 조회할 업무 구분

    Returns:
        list of dict: 입찰공고 항목 리스트
    """
    base_url = ENDPOINTS + "/getBidPblancListInfoServc"
    all_items = []
    page = 1
    max_pages = 10  # 안전장치

    # ─── 핵심 수정: serviceKey 이중 인코딩 방지 ───
    # data.go.kr API는 serviceKey에 +, /, = 등이 포함되어 있어
    # requests의 params에 넣으면 이중 인코딩되어 인증 실패함.
    # → serviceKey만 URL에 직접 붙이고, 나머지는 params로 전달.
    encoded_key = quote_plus(API_KEY)

    while page <= max_pages:
        url = f"{base_url}?serviceKey={encoded_key}"
        params = {
            "pageNo": page,
            "numOfRows": 100,
            "inqryDiv": "1",            # 1: 공고일시 기준 조회
            "inqryBgnDt": from_dt,
            "inqryEndDt": to_dt,
            "type": "json",
        }

        try:
            resp = requests.get(url, params=params, timeout=30)

            # 빈 응답 체크
            if not resp.text or not resp.text.strip():
                logger.error("빈 응답 수신. API 키 또는 서비스 승인 상태를 확인하세요.")
                break

            # API 키 오류 등으로 XML 응답이 오는 경우 처리
            content_type = resp.headers.get("Content-Type", "")
            if "xml" in content_type.lower() or resp.text.strip().startswith("<"):
                logger.error(f"XML 응답 수신 (API 키 확인 필요): {resp.text[:500]}")
                break

            data = resp.json()

            # 응답 구조 파싱
            body = data.get("response", {}).get("body", {})
            total_count = int(body.get("totalCount", 0))
            items = body.get("items", [])

            if not items:
                break

            # items가 dict인 경우 (단건 응답)
            if isinstance(items, dict):
                items = items.get("item", [])
            if isinstance(items, dict):
                items = [items]

            all_items.extend(items)
            logger.info(f"[{endpoint_name}] 페이지 {page} 조회: {len(items)}건 (누적 {len(all_items)}/{total_count})")

            if len(all_items) >= total_count:
                break

            page += 1
            time.sleep(0.3)  # API 부하 방지

        except requests.exceptions.RequestException as e:
            logger.error(f"API 호출 실패: {e}")
            break
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"응답 파싱 실패: {e}")
            break

    return all_items


# ──────────────────────────────────────────────
# 2. 키워드 필터링
# ──────────────────────────────────────────────

def filter_by_keywords(items: list) -> list:
    """
    공고명(bidNtceNm)에서 키워드 매칭하여 관련 공고만 추출합니다.
    """
    matched = []

    for item in items:
        title = item.get("bidNtceNm", "")
        detail = item.get("ntceSpecDocUrl1", "")  # 공고 상세

        # 공고명 기준 키워드 매칭
        matched_keywords = [kw for kw in KEYWORDS if kw in title]

        if matched_keywords:
            bid_info = {
                "공고번호": item.get("bidNtceNo", ""),
                "공고차수": item.get("bidNtceOrd", ""),
                "공고명": title,
                "발주기관": item.get("dminsttNm", ""),     # 수요기관
                "공고기관": item.get("ntceInsttNm", ""),   # 공고기관
                "추정가격": _format_price(item.get("presmptPrce", "")),
                "기초금액": _format_price(item.get("bssamt", "")),
                "입찰마감": _format_datetime(item.get("bidClseDt", "")),
                "공고일": _format_datetime(item.get("bidNtceDt", "")),
                "계약방법": item.get("cntrctCnclsMthdNm", ""),
                "링크": item.get("bidNtceDtlUrl", ""),
                "매칭키워드": ", ".join(matched_keywords),
            }
            matched.append(bid_info)

    logger.info(f"키워드 매칭 결과: {len(items)}건 중 {len(matched)}건 해당")
    return matched


def _format_price(price) -> str:
    """가격을 읽기 좋은 형태로 변환"""
    if not price:
        return "미정"
    try:
        p = int(float(price))
        if p >= 100_000_000:
            return f"{p / 100_000_000:.1f}억원"
        elif p >= 10_000:
            return f"{p / 10_000:.0f}만원"
        return f"{p:,}원"
    except (ValueError, TypeError):
        return str(price)


def _format_datetime(dt_str: str) -> str:
    """날짜 문자열을 보기 좋게 변환"""
    if not dt_str:
        return "미정"
    try:
        # API 응답: "2025/01/15 18:00:00" 또는 "2025-01-15 18:00:00" 등
        dt_str = dt_str.replace("/", "-")
        dt = datetime.strptime(dt_str[:16], "%Y-%m-%d %H:%M")
        return dt.strftime("%m/%d(%a) %H:%M")
    except (ValueError, IndexError):
        return dt_str


# ──────────────────────────────────────────────
# 3. 중복 방지 (SQLite)
# ──────────────────────────────────────────────

def init_db():
    """DB 및 테이블 초기화"""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS notified_bids (
            bid_id      TEXT PRIMARY KEY,
            title       TEXT,
            org         TEXT,
            notified_at TEXT,
            keywords    TEXT
        )
    """)
    conn.commit()
    conn.close()


def filter_new_bids(bids: list) -> list:
    """이미 알림을 보낸 공고를 필터링하고, 새 공고만 반환합니다."""
    conn = sqlite3.connect(DB_PATH)
    new_bids = []

    for bid in bids:
        bid_id = f"{bid['공고번호']}_{bid['공고차수']}"
        cursor = conn.execute(
            "SELECT 1 FROM notified_bids WHERE bid_id = ?", (bid_id,)
        )

        if not cursor.fetchone():
            new_bids.append(bid)
            conn.execute(
                "INSERT INTO notified_bids (bid_id, title, org, notified_at, keywords) VALUES (?, ?, ?, ?, ?)",
                (
                    bid_id,
                    bid["공고명"],
                    bid["공고기관"],
                    datetime.now().isoformat(),
                    bid["매칭키워드"],
                ),
            )

    conn.commit()
    conn.close()
    logger.info(f"신규 공고: {len(new_bids)}건 (중복 제외: {len(bids) - len(new_bids)}건)")
    return new_bids


# ──────────────────────────────────────────────
# 4. 알림 발송
# ──────────────────────────────────────────────

def notify(bids: list):
    """설정된 방법으로 알림을 발송합니다."""
    if NOTIFY_METHOD == "telegram":
        _notify_telegram(bids)
    elif NOTIFY_METHOD == "slack":
        _notify_slack(bids)
    elif NOTIFY_METHOD == "both":
        _notify_telegram(bids)
        _notify_slack(bids)
    else:
        # 콘솔 출력만
        _notify_console(bids)


def _notify_telegram(bids: list):
    """Telegram Bot으로 알림 발송"""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    # 요약 헤더
    header = f"📢 나라장터 용역 신규 공고 {len(bids)}건\n{'─' * 30}\n"

    # 개별 공고 메시지 (Telegram 메시지 길이 제한: 4096자)
    messages = []
    current_msg = header

    for i, bid in enumerate(bids, 1):
        entry = (
            f"\n{i}. {bid['공고명']}\n"
            f"   🏢 {bid['공고기관']}\n"
            f"   💰 추정가: {bid['추정가격']}\n"
            f"   ⏰ 마감: {bid['입찰마감']}\n"
            f"   🔑 키워드: {bid['매칭키워드']}\n"
            f"   🔗 {bid['링크']}\n"
        )

        if len(current_msg) + len(entry) > 4000:
            messages.append(current_msg)
            current_msg = f"📢 계속 ({i}번~)\n"

        current_msg += entry

    messages.append(current_msg)

    for msg in messages:
        try:
            resp = requests.post(
                url,
                json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"},
                timeout=10,
            )
            if resp.status_code == 200:
                logger.info("Telegram 알림 발송 성공")
            else:
                logger.error(f"Telegram 발송 실패: {resp.text}")
        except Exception as e:
            logger.error(f"Telegram 발송 에러: {e}")

        time.sleep(0.5)


def _notify_slack(bids: list):
    """Slack Webhook으로 알림 발송"""
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"📢 나라장터 용역 신규 공고 {len(bids)}건"},
        }
    ]

    for bid in bids:
        blocks.append({"type": "divider"})
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*{bid['공고명']}*\n"
                        f"🏢 {bid['공고기관']} | 💰 {bid['추정가격']}\n"
                        f"⏰ 마감: {bid['입찰마감']} | 🔑 {bid['매칭키워드']}\n"
                        f"<{bid['링크']}|상세보기>"
                    ),
                },
            }
        )

    try:
        resp = requests.post(
            SLACK_WEBHOOK_URL,
            json={"blocks": blocks},
            timeout=10,
        )
        if resp.status_code == 200:
            logger.info("Slack 알림 발송 성공")
        else:
            logger.error(f"Slack 발송 실패: {resp.text}")
    except Exception as e:
        logger.error(f"Slack 발송 에러: {e}")


def _notify_console(bids: list):
    """콘솔에 결과 출력 (테스트용)"""
    print(f"\n{'=' * 60}")
    print(f"  📢 나라장터 용역 신규 공고 {len(bids)}건")
    print(f"  조회 시각: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'=' * 60}")

    for i, bid in enumerate(bids, 1):
        print(f"\n  [{i}] {bid['공고명']}")
        print(f"      공고기관: {bid['공고기관']}")
        print(f"      발주기관: {bid['발주기관']}")
        print(f"      추정가격: {bid['추정가격']}")
        print(f"      기초금액: {bid['기초금액']}")
        print(f"      입찰마감: {bid['입찰마감']}")
        print(f"      계약방법: {bid['계약방법']}")
        print(f"      매칭키워드: {bid['매칭키워드']}")
        print(f"      링크: {bid['링크']}")

    print(f"\n{'=' * 60}\n")


# ──────────────────────────────────────────────
# 5. 메인 실행
# ──────────────────────────────────────────────

def run():
    """메인 실행 함수"""
    logger.info("=" * 50)
    logger.info("나라장터 용역 입찰공고 모니터링 시작")
    logger.info(f"검색 키워드: {KEYWORDS}")

    # DB 초기화
    init_db()

    # 조회 기간 설정
    now = datetime.now()
    from_dt = (now - timedelta(hours=CHECK_HOURS)).strftime("%Y%m%d%H%M")
    to_dt = now.strftime("%Y%m%d%H%M")
    logger.info(f"조회 기간: {from_dt} ~ {to_dt}")

    # API 조회
    items = fetch_bids(from_dt, to_dt)
    logger.info(f"전체 용역 공고: {len(items)}건")

    if not items:
        logger.info("조회된 공고가 없습니다.")
        return

    # 키워드 필터링
    matched = filter_by_keywords(items)

    if not matched:
        logger.info("키워드에 해당하는 공고가 없습니다.")
        return

    # 중복 제거
    new_bids = filter_new_bids(matched)

    if not new_bids:
        logger.info("신규 공고가 없습니다 (모두 기존 알림 완료).")
        return

    # 알림 발송
    notify(new_bids)
    logger.info(f"완료: {len(new_bids)}건 알림 발송")


if __name__ == "__main__":
    run()
