import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

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
MAX_ITEMS = 100

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/154.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}


def normalize(text: str) -> str:
    return re.sub(r"\s+", "", text).casefold()


def load_keywords():
    data = json.loads(KEYWORDS_FILE.read_text(encoding="utf-8"))
    words = [x.strip() for x in data.get("keywords", []) if x.strip()]
    if not words:
        raise RuntimeError("keywords.json에 키워드를 1개 이상 넣어주세요.")
    return words


def load_seen():
    if not SEEN_FILE.exists():
        return set()
    try:
        return set(json.loads(SEEN_FILE.read_text(encoding="utf-8")))
    except Exception:
        return set()


def save_seen(values):
    values = list(values)
    SEEN_FILE.write_text(
        json.dumps(values[-5000:], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def decrypt_refresh_token():
    if not TOKEN_FILE.exists():
        raise RuntimeError(
            "kakao_refresh_token.enc가 없습니다. README의 초기 토큰 설정을 먼저 해주세요."
        )
    f = Fernet(KAKAO_TOKEN_KEY)
    return f.decrypt(TOKEN_FILE.read_bytes()).decode("utf-8").strip()


def encrypt_refresh_token(token: str):
    f = Fernet(KAKAO_TOKEN_KEY)
    TOKEN_FILE.write_bytes(f.encrypt(token.encode("utf-8")))


def refresh_kakao_access_token():
    refresh_token = decrypt_refresh_token()

    data = {
        "grant_type": "refresh_token",
        "client_id": KAKAO_REST_API_KEY,
        "refresh_token": refresh_token,
    }
    if KAKAO_CLIENT_SECRET:
        data["client_secret"] = KAKAO_CLIENT_SECRET

    r = requests.post(
        "https://kauth.kakao.com/oauth/token",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"},
        timeout=REQUEST_TIMEOUT,
    )
    r.raise_for_status()
    result = r.json()

    access_token = result["access_token"]

    # 카카오는 기존 Refresh Token의 만료가 가까우면 새 Refresh Token을 함께 반환할 수 있음.
    # 이 경우 암호화 파일을 갱신하고 workflow 마지막에 Git으로 커밋함.
    new_refresh = result.get("refresh_token")
    if new_refresh and new_refresh != refresh_token:
        encrypt_refresh_token(new_refresh)
        print("카카오 Refresh Token이 갱신되어 암호화 파일을 업데이트했습니다.")

    return access_token


def fetch_products():
    r = requests.get(TARGET_URL, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")

    products = []
    dedup = set()

    # 코믹존 상품 상세 링크 기준.
    for a in soup.select('a[href*="goods_view.php"]'):
        href = (a.get("href") or "").strip()
        title = a.get_text(" ", strip=True)

        if not href or not title:
            continue

        url = urljoin(TARGET_URL, href)
        if "goodsNo=" not in url or url in dedup:
            continue

        dedup.add(url)
        products.append({"title": title, "url": url})

        if len(products) >= MAX_ITEMS:
            break

    if not products:
        raise RuntimeError(
            "상품 링크를 찾지 못했습니다. 코믹존 HTML 구조가 변경됐을 수 있습니다."
        )

    return products


def matched_keywords(title, keywords):
    nt = normalize(title)
    return [kw for kw in keywords if normalize(kw) in nt]


def send_kakao(access_token, matched_products):
    # 하루 한 번 실행하므로 여러 건이면 한 메시지로 묶어서 전송.
    # 텍스트 템플릿의 본문은 너무 길어지지 않게 제한.
    lines = ["🔔 코믹존 키워드 신작"]

    for p in matched_products[:10]:
        matches = ", ".join(p["matches"])
        lines += [
            "",
            f"• {p['title']}",
            f"  키워드: {matches}",
            f"  {p['url']}",
        ]

    if len(matched_products) > 10:
        lines += ["", f"외 {len(matched_products) - 10}건"]

    text = "\n".join(lines)
    if len(text) > 1800:
        text = text[:1770] + "\n...(일부 생략)"

    template = {
        "object_type": "text",
        "text": text,
        "link": {
            "web_url": TARGET_URL,
            "mobile_web_url": TARGET_URL,
        },
        "button_title": "코믹존 열기",
    }

    r = requests.post(
        "https://kapi.kakao.com/v2/api/talk/memo/default/send",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/x-www-form-urlencoded;charset=utf-8",
        },
        data={"template_object": json.dumps(template, ensure_ascii=False)},
        timeout=REQUEST_TIMEOUT,
    )
    r.raise_for_status()

    result = r.json()
    if result.get("result_code") != 0:
        raise RuntimeError(f"카카오 메시지 발송 실패: {result}")


def main():
    keywords = load_keywords()
    seen = load_seen()
    products = fetch_products()

    current_urls = {p["url"] for p in products}

    # 첫 실행에서는 현재 상품을 기준점으로만 저장.
    if not seen:
        print(f"첫 실행: 현재 상품 {len(products)}개를 기준점으로 저장합니다.")
        save_seen(list(current_urls))
        return

    new_products = [p for p in products if p["url"] not in seen]
    if not new_products:
        print("새 상품 없음. 카카오톡을 보내지 않습니다.")
        return

    matched = []
    for p in reversed(new_products):
        hits = matched_keywords(p["title"], keywords)
        if hits:
            matched.append({**p, "matches": hits})

    # 신규 상품은 키워드 일치 여부와 관계없이 seen 처리.
    # 그래야 다음 날 같은 비매칭 상품을 반복 검사하지 않음.
    seen.update(current_urls)
    save_seen(list(seen))

    if not matched:
        print(
            f"새 상품 {len(new_products)}개 발견 / 키워드 일치 0개. "
            "카카오톡을 보내지 않습니다."
        )
        return

    access_token = refresh_kakao_access_token()
    send_kakao(access_token, matched)

    print(
        f"새 상품 {len(new_products)}개 / 키워드 일치 {len(matched)}개 / "
        "카카오톡 전송 완료"
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
