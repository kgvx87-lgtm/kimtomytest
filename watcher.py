import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qsl, urlencode, urlunparse

import requests
from bs4 import BeautifulSoup
from cryptography.fernet import Fernet


TARGET_URL = os.environ.get(
    "TARGET_URL",
    "https://comiczone.co.kr/goods/goods_list.php?cateCd=056",
)

KAKAO_REST_API_KEY = os.environ["KAKAO_REST_API_KEY"]
KAKAO_CLIENT_SECRET = os.environ.get("KAKAO_CLIENT_SECRET", "").strip()
KAKAO_TOKEN_KEY = os.environ["KAKAO_TOKEN_KEY"].encode()

KEYWORDS_FILE = Path("keywords.json")
SEEN_FILE = Path("seen.json")
TOKEN_FILE = Path("kakao_refresh_token.enc")

REQUEST_TIMEOUT = 25

# 코믹존 목록을 몇 페이지까지 확인할지
MAX_PAGES = 10

# 한 페이지에서 최대 몇 개 상품 링크를 읽을지
MAX_ITEMS_PER_PAGE = 100

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/154.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}


def normalize(text: str) -> str:
    """
    키워드 비교용 정규화.
    공백 제거 + 대소문자 무시.
    """
    return re.sub(r"\s+", "", text).casefold()


def load_keywords():
    data = json.loads(KEYWORDS_FILE.read_text(encoding="utf-8"))

    words = [
        x.strip()
        for x in data.get("keywords", [])
        if x.strip()
    ]

    if not words:
        raise RuntimeError(
            "keywords.json에 키워드를 1개 이상 넣어주세요."
        )

    return words


def load_seen():
    if not SEEN_FILE.exists():
        return set()

    try:
        return set(
            json.loads(
                SEEN_FILE.read_text(encoding="utf-8")
            )
        )
    except Exception:
        return set()


def save_seen(values):
    values = list(values)

    # 너무 커지지 않도록 최근 기록만 유지
    SEEN_FILE.write_text(
        json.dumps(
            values[-5000:],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def decrypt_refresh_token():
    if not TOKEN_FILE.exists():
        raise RuntimeError(
            "kakao_refresh_token.enc가 없습니다."
        )

    f = Fernet(KAKAO_TOKEN_KEY)

    return (
        f.decrypt(TOKEN_FILE.read_bytes())
        .decode("utf-8")
        .strip()
    )


def encrypt_refresh_token(token: str):
    f = Fernet(KAKAO_TOKEN_KEY)

    TOKEN_FILE.write_bytes(
        f.encrypt(token.encode("utf-8"))
    )


def refresh_kakao_access_token():
    """
    Refresh Token으로 Access Token 발급.
    카카오가 새 Refresh Token을 반환하면
    암호화 파일을 자동 갱신.
    """

    refresh_token = decrypt_refresh_token()

    data = {
        "grant_type": "refresh_token",
        "client_id": KAKAO_REST_API_KEY,
        "refresh_token": refresh_token,
    }

    if KAKAO_CLIENT_SECRET:
        data["client_secret"] = KAKAO_CLIENT_SECRET

    response = requests.post(
        "https://kauth.kakao.com/oauth/token",
        data=data,
        headers={
            "Content-Type":
            "application/x-www-form-urlencoded;charset=utf-8"
        },
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()

    result = response.json()

    access_token = result["access_token"]

    new_refresh_token = result.get("refresh_token")

    if (
        new_refresh_token
        and new_refresh_token != refresh_token
    ):
        encrypt_refresh_token(new_refresh_token)

        print(
            "카카오 Refresh Token이 갱신되어 "
            "암호화 파일을 업데이트했습니다."
        )

    return access_token


def make_page_url(base_url: str, page: int) -> str:
    """
    기존 URL query string을 유지하면서
    page 파라미터만 변경.
    """

    parsed = urlparse(base_url)

    query = dict(
        parse_qsl(
            parsed.query,
            keep_blank_values=True,
        )
    )

    query["page"] = str(page)

    return urlunparse(
        parsed._replace(
            query=urlencode(query)
        )
    )


def fetch_products():
    """
    코믹존 목록 1~MAX_PAGES 페이지를 순회해서
    상품 정보를 수집.
    """

    products = []
    dedup = set()

    last_page = 0

    for page in range(1, MAX_PAGES + 1):
        last_page = page

        page_url = make_page_url(
            TARGET_URL,
            page,
        )

        print(
            f"{page}페이지 확인 중: "
            f"{page_url}"
        )

        response = requests.get(
            page_url,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        page_count = 0

        # 코믹존 상품 상세 페이지 링크만 추출
        for a in soup.select(
            'a[href*="goods_view.php"]'
        ):
            href = (
                a.get("href") or ""
            ).strip()

            title = a.get_text(
                " ",
                strip=True,
            )

            if not href or not title:
                continue

            url = urljoin(
                page_url,
                href,
            )

            if "goodsNo=" not in url:
                continue

            if url in dedup:
                continue

            dedup.add(url)

            products.append(
                {
                    "title": title,
                    "url": url,
                    "page": page,
                }
            )

            page_count += 1

            if (
                page_count
                >= MAX_ITEMS_PER_PAGE
            ):
                break

        print(
            f"{page}페이지: "
            f"{page_count}개 상품 확인"
        )

        # 상품이 하나도 없는 페이지면
        # 마지막 페이지로 판단하고 종료
        if page_count == 0:
            print(
                f"{page}페이지에 상품이 없어 "
                "페이지 순회를 종료합니다."
            )
            break

    if not products:
        raise RuntimeError(
            "상품 링크를 찾지 못했습니다. "
            "코믹존 HTML 구조가 변경됐을 수 있습니다."
        )

    print(
        f"총 {len(products)}개 상품 확인 "
        f"({last_page}페이지까지)"
    )

    return products


def matched_keywords(
    title,
    keywords,
):
    normalized_title = normalize(title)

    return [
        keyword
        for keyword in keywords
        if normalize(keyword)
        in normalized_title
    ]


def send_kakao(
    access_token,
    matched_products,
):
    """
    하루 한 번 실행하므로
    여러 개 일치 상품을 한 메시지로 묶어서 전송.
    """

    lines = [
        "🔔 코믹존 키워드 신작"
    ]

    for product in matched_products[:10]:
        matches = ", ".join(
            product["matches"]
        )

        lines += [
            "",
            f"• {product['title']}",
            f"  키워드: {matches}",
            f"  {product['url']}",
        ]

    if len(matched_products) > 10:
        lines += [
            "",
            f"외 "
            f"{len(matched_products) - 10}"
            f"건",
        ]

    text = "\n".join(lines)

    # 카카오 텍스트 템플릿 길이 제한 대비
    if len(text) > 1800:
        text = (
            text[:1770]
            + "\n...(일부 생략)"
        )

    template = {
        "object_type": "text",
        "text": text,
        "link": {
            "web_url": TARGET_URL,
            "mobile_web_url": TARGET_URL,
        },
        "button_title": "코믹존 열기",
    }

    response = requests.post(
        (
            "https://kapi.kakao.com/"
            "v2/api/talk/memo/default/send"
        ),
        headers={
            "Authorization":
            f"Bearer {access_token}",
            "Content-Type":
            (
                "application/"
                "x-www-form-urlencoded;"
                "charset=utf-8"
            ),
        },
        data={
            "template_object":
            json.dumps(
                template,
                ensure_ascii=False,
            )
        },
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()

    result = response.json()

    if result.get("result_code") != 0:
        raise RuntimeError(
            f"카카오 메시지 발송 실패: "
            f"{result}"
        )


def main():
    keywords = load_keywords()
    seen = load_seen()

    products = fetch_products()

    current_urls = {
        product["url"]
        for product in products
    }

    # 최초 실행:
    # 현재 상품들을 기준점으로 저장만 하고
    # 기존 상품 알림은 보내지 않음.
    if not seen:
        print(
            f"첫 실행: 현재 상품 "
            f"{len(products)}개를 "
            "기준점으로 저장합니다."
        )

        save_seen(
            list(current_urls)
        )

        return

    new_products = [
        product
        for product in products
        if product["url"] not in seen
    ]

    if not new_products:
        print(
            "새 상품 없음. "
            "카카오톡을 보내지 않습니다."
        )

        return

    print(
        f"새 상품 "
        f"{len(new_products)}개 발견"
    )

    matched = []

    # 오래된 신규상품 → 최신 신규상품 순으로 처리
    for product in reversed(new_products):
        hits = matched_keywords(
            product["title"],
            keywords,
        )

        print(
            f"- {product['title']} "
            f"(페이지 {product['page']})"
        )

        if hits:
            print(
                "  키워드 일치:",
                ", ".join(hits),
            )

            matched.append(
                {
                    **product,
                    "matches": hits,
                }
            )
        else:
            print(
                "  키워드 불일치"
            )

    # 키워드 일치 여부와 관계없이
    # 이번에 확인한 상품은 seen 처리.
    seen.update(current_urls)

    save_seen(
        list(seen)
    )

    if not matched:
        print(
            f"새 상품 "
            f"{len(new_products)}개 발견 / "
            "키워드 일치 0개. "
            "카카오톡을 보내지 않습니다."
        )

        return

    access_token = (
        refresh_kakao_access_token()
    )

    send_kakao(
        access_token,
        matched,
    )

    print(
        f"새 상품 "
        f"{len(new_products)}개 / "
        f"키워드 일치 "
        f"{len(matched)}개 / "
        "카카오톡 전송 완료"
    )


if __name__ == "__main__":
    try:
        main()

    except Exception as exc:
        print(
            f"ERROR: {exc}",
            file=sys.stderr,
        )

        raise
