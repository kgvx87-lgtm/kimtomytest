import json
import os
import sys
from pathlib import Path
from urllib.parse import (
    urljoin,
    urlparse,
    parse_qsl,
    urlencode,
    urlunparse,
)

import requests
from bs4 import BeautifulSoup
from cryptography.fernet import Fernet


TARGET_URL = os.environ.get(
    "TARGET_URL",
    "https://comiczone.co.kr/goods/goods_list.php?cateCd=056",
).strip()

if not TARGET_URL.startswith(("http://", "https://")):
    TARGET_URL = (
        "https://comiczone.co.kr/"
        "goods/goods_list.php?cateCd=056"
    )

KAKAO_REST_API_KEY = os.environ["KAKAO_REST_API_KEY"]
KAKAO_CLIENT_SECRET = os.environ.get(
    "KAKAO_CLIENT_SECRET",
    "",
).strip()

KAKAO_TOKEN_KEY = os.environ[
    "KAKAO_TOKEN_KEY"
].encode()

KEYWORDS_FILE = Path("keywords.json")
SEEN_FILE = Path("seen.json")
TOKEN_FILE = Path("kakao_refresh_token.enc")

REQUEST_TIMEOUT = 25

# 매일 확인할 페이지 수
MAX_PAGES = 10

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/154.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}


def normalize(text: str) -> str:
    return "".join(
        text.casefold().split()
    )


def load_keywords():
    data = json.loads(
        KEYWORDS_FILE.read_text(
            encoding="utf-8"
        )
    )

    keywords = [
        item.strip()
        for item in data.get("keywords", [])
        if item.strip()
    ]

    if not keywords:
        raise RuntimeError(
            "keywords.json에 키워드가 없습니다."
        )

    return keywords


def load_seen():
    if not SEEN_FILE.exists():
        return set()

    try:
        return set(
            json.loads(
                SEEN_FILE.read_text(
                    encoding="utf-8"
                )
            )
        )
    except Exception:
        return set()


def save_seen(values):
    # URL 자체가 식별자 역할
    values = sorted(set(values))

    # 지나치게 커지는 것 방지
    values = values[-5000:]

    SEEN_FILE.write_text(
        json.dumps(
            values,
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

    fernet = Fernet(
        KAKAO_TOKEN_KEY
    )

    return (
        fernet.decrypt(
            TOKEN_FILE.read_bytes()
        )
        .decode("utf-8")
        .strip()
    )


def encrypt_refresh_token(
    token: str,
):
    fernet = Fernet(
        KAKAO_TOKEN_KEY
    )

    TOKEN_FILE.write_bytes(
        fernet.encrypt(
            token.encode("utf-8")
        )
    )


def refresh_kakao_access_token():
    refresh_token = (
        decrypt_refresh_token()
    )

    data = {
        "grant_type": "refresh_token",
        "client_id": KAKAO_REST_API_KEY,
        "refresh_token": refresh_token,
    }

    if KAKAO_CLIENT_SECRET:
        data["client_secret"] = (
            KAKAO_CLIENT_SECRET
        )

    response = requests.post(
        "https://kauth.kakao.com/oauth/token",
        data=data,
        headers={
            "Content-Type":
            (
                "application/"
                "x-www-form-urlencoded;"
                "charset=utf-8"
            )
        },
        timeout=REQUEST_TIMEOUT,
    )

    if not response.ok:
        print(
            "Kakao token status:",
            response.status_code,
        )
        print(
            "Kakao token response:",
            response.text,
        )

    response.raise_for_status()

    result = response.json()

    access_token = result[
        "access_token"
    ]

    new_refresh_token = (
        result.get("refresh_token")
    )

    # 카카오가 새 Refresh Token을
    # 같이 내려주는 경우 자동 갱신
    if (
        new_refresh_token
        and new_refresh_token
        != refresh_token
    ):
        encrypt_refresh_token(
            new_refresh_token
        )

        print(
            "카카오 Refresh Token 갱신 완료"
        )

    return access_token


def make_page_url(
    base_url: str,
    page: int,
) -> str:
    parsed = urlparse(
        base_url
    )

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
    products = []
    dedup = set()

    for page in range(
        1,
        MAX_PAGES + 1,
    ):
        page_url = make_page_url(
            TARGET_URL,
            page,
        )

        print(
            f"{page}페이지 확인 중"
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

        page_products = []

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

            item = {
                "title": title,
                "url": url,
                "page": page,
            }

            page_products.append(
                item
            )

            products.append(
                item
            )

        print(
            f"{page}페이지: "
            f"{len(page_products)}개 상품 확인"
        )

        # 마지막 페이지 도달 시 종료
        if not page_products:
            print(
                "상품이 없는 페이지라 "
                "페이지 확인 종료"
            )
            break

    if not products:
        raise RuntimeError(
            "코믹존 상품을 찾지 못했습니다."
        )

    print(
        f"총 {len(products)}개 상품 확인"
    )

    return products


def matched_keywords(
    title,
    keywords,
):
    normalized_title = (
        normalize(title)
    )

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
    lines = [
        "🔔 코믹존 키워드 신작"
    ]

    # 카카오 메시지 길이 때문에
    # 한 번에 최대 10개 표시
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
            (
                f"외 "
                f"{len(matched_products) - 10}"
                f"건"
            ),
        ]

    text = "\n".join(
        lines
    )

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
            "mobile_web_url":
                TARGET_URL,
        },
        "button_title":
            "코믹존 열기",
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

    if not response.ok:
        print(
            "Kakao message status:",
            response.status_code,
        )
        print(
            "Kakao message response:",
            response.text,
        )

    response.raise_for_status()

    result = response.json()

    if result.get(
        "result_code"
    ) != 0:
        raise RuntimeError(
            f"카카오 메시지 발송 실패: "
            f"{result}"
        )


def main():
    print(
        "=== 코믹존 신상품 감시 시작 ==="
    )

    keywords = load_keywords()
    seen = load_seen()

    products = fetch_products()

    current_urls = {
        product["url"]
        for product in products
    }

    # 최초 실행:
    # 현재 상품을 모두 기존 상품으로 등록
    if not seen:
        print(
            f"첫 실행: "
            f"{len(products)}개 상품을 "
            "기준점으로 저장"
        )

        save_seen(
            current_urls
        )

        return

    new_products = [
        product
        for product in products
        if product["url"]
        not in seen
    ]

    if not new_products:
        print(
            "신규 상품 없음"
        )
        return

    print(
        f"신규 상품 "
        f"{len(new_products)}개 발견"
    )

    matched = []

    for product in reversed(
        new_products
    ):
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

    # 키워드가 안 맞은 신규 상품도
    # 다음 실행에서는 신규로 다시 보지 않게 저장
    seen.update(
        current_urls
    )

    save_seen(
        seen
    )

    if not matched:
        print(
            "신규 상품은 있으나 "
            "키워드 일치 상품 없음"
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
        f"카카오톡 전송 완료: "
        f"{len(matched)}개"
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
