import json
import os
import re
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
)

KAKAO_REST_API_KEY = os.environ["KAKAO_REST_API_KEY"]
KAKAO_CLIENT_SECRET = os.environ.get(
    "KAKAO_CLIENT_SECRET",
    "",
).strip()

KAKAO_TOKEN_KEY = os.environ[
    "KAKAO_TOKEN_KEY"
].encode()

TOKEN_FILE = Path("kakao_refresh_token.enc")

REQUEST_TIMEOUT = 25
MAX_PAGES = 10
MAX_ITEMS_PER_PAGE = 100

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/154.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}


def decrypt_refresh_token():
    if not TOKEN_FILE.exists():
        raise RuntimeError(
            "kakao_refresh_token.enc가 없습니다."
        )

    fernet = Fernet(KAKAO_TOKEN_KEY)

    return (
        fernet.decrypt(
            TOKEN_FILE.read_bytes()
        )
        .decode("utf-8")
        .strip()
    )


def encrypt_refresh_token(token: str):
    fernet = Fernet(KAKAO_TOKEN_KEY)

    TOKEN_FILE.write_bytes(
        fernet.encrypt(
            token.encode("utf-8")
        )
    )


def refresh_kakao_access_token():
    refresh_token = decrypt_refresh_token()

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
            "application/x-www-form-urlencoded;charset=utf-8"
        },
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()

    result = response.json()

    access_token = result["access_token"]

    new_refresh_token = result.get(
        "refresh_token"
    )

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

        if page_count == 0:
            print(
                "상품이 없는 페이지라 "
                "순회를 종료합니다."
            )
            break

    if not products:
        raise RuntimeError(
            "상품 링크를 찾지 못했습니다."
        )

    return products


def send_test_kakao(
    access_token,
    page1_products,
):
    lines = [
        "🧪 코믹존 카카오톡 테스트",
        "",
        "현재 1페이지 상품 목록",
    ]

    test_products = (
        page1_products[:10]
    )

    for index, product in enumerate(
        test_products,
        start=1,
    ):
        lines += [
            "",
            f"{index}. "
            f"{product['title']}",
            product["url"],
        ]

    if len(page1_products) > 10:
        lines += [
            "",
            f"외 "
            f"{len(page1_products) - 10}"
            f"개 상품",
        ]

    text = "\n".join(lines)

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

    print(
        "카카오톡 테스트 메시지 전송 완료"
    )


def main():
    print(
        "=== 코믹존 카카오톡 테스트 모드 ==="
    )

    products = fetch_products()

    page1_products = [
        product
        for product in products
        if product.get("page") == 1
    ]

    if not page1_products:
        raise RuntimeError(
            "1페이지 상품을 찾지 못했습니다."
        )

    print(
        f"1페이지 상품 "
        f"{len(page1_products)}개 확인"
    )

    access_token = (
        refresh_kakao_access_token()
    )

    send_test_kakao(
        access_token,
        page1_products,
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
