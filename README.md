# Comiczone → KakaoTalk Keyword Watcher

매일 **한국시간 오후 12:10**에 코믹존 카테고리를 확인합니다.

- 신규 상품 없음 → 아무 알림 없음
- 신규 상품은 있으나 키워드 불일치 → 아무 알림 없음
- 신규 상품 + 키워드 일치 → **내 카카오톡 '나와의 채팅'으로 알림**
- OpenAI API 사용 안 함 → OpenAI 비용 없음

기본 감시 주소:

```text
https://comiczone.co.kr/goods/goods_list.php?cateCd=056
```

---

## 파일 구조

```text
comiczone-kakao-watcher/
├─ watcher.py
├─ init_token.py
├─ requirements.txt
├─ keywords.json
├─ seen.json
├─ kakao_refresh_token.enc   # init_token.py 실행 후 생성
└─ .github/
   └─ workflows/
      └─ watch.yml
```

---

# 1. 카카오 Developers 앱 생성

카카오 Developers에서 애플리케이션을 하나 만듭니다.

필요한 설정:

1. 카카오 로그인 활성화
2. Redirect URI 등록
3. 동의 항목에서 카카오톡 메시지 전송(`talk_message`) 사용
4. REST API 키 확인
5. Client Secret이 ON이면 Client Secret도 확인

`나에게 메시지 발송`은 본인 카카오톡의 **나와의 채팅**으로 전송됩니다.

---

# 2. 최초 카카오 인증

브라우저에서 인가 코드를 받아 Refresh Token을 한 번 발급해야 합니다.

인가 URL 예시:

```text
https://kauth.kakao.com/oauth/authorize?client_id=REST_API_KEY&redirect_uri=등록한_REDIRECT_URI&response_type=code&scope=talk_message
```

로그인/동의 후 Redirect URI 뒤에 붙는:

```text
?code=....
```

의 `code` 값을 이용해 토큰을 발급합니다.

예:

```bash
curl -X POST "https://kauth.kakao.com/oauth/token" \
  -H "Content-Type: application/x-www-form-urlencoded;charset=utf-8" \
  -d "grant_type=authorization_code" \
  -d "client_id=REST_API_KEY" \
  -d "redirect_uri=등록한_REDIRECT_URI" \
  -d "code=인가코드" \
  -d "client_secret=CLIENT_SECRET"
```

응답의:

```json
{
  "access_token": "...",
  "refresh_token": "..."
}
```

중 `refresh_token`이 필요합니다.

Client Secret을 사용하지 않는 앱이면 위 요청에서
`client_secret` 항목을 제외합니다.

---

# 3. Refresh Token 암호화

PC에서:

```bash
pip install cryptography
python init_token.py
```

Refresh Token을 붙여 넣으면:

```text
kakao_refresh_token.enc
```

파일이 생성되고 다음 값이 화면에 출력됩니다.

```text
KAKAO_TOKEN_KEY=xxxxxxxx
```

### 중요

- `kakao_refresh_token.enc` → GitHub 저장소에 올림
- `KAKAO_TOKEN_KEY` → GitHub Secret에만 저장
- 평문 Refresh Token은 저장소에 올리지 않음

카카오가 Refresh Token을 새로 발급하면 Actions가
`kakao_refresh_token.enc`를 자동으로 갱신합니다.

---

# 4. GitHub Secrets

Repository:

```text
Settings
→ Secrets and variables
→ Actions
→ New repository secret
```

다음을 등록합니다.

### KAKAO_REST_API_KEY

카카오 Developers의 REST API 키.

### KAKAO_CLIENT_SECRET

카카오 앱 Client Secret.

Client Secret을 사용하지 않으면 빈 값으로 두거나 만들지 않아도 됩니다.

### KAKAO_TOKEN_KEY

`init_token.py` 실행 시 출력된 키.

### TARGET_URL (선택)

```text
https://comiczone.co.kr/goods/goods_list.php?cateCd=056
```

등록하지 않으면 코드의 기본 URL을 사용합니다.

---

# 5. 키워드

`keywords.json`만 수정하면 됩니다.

```json
{
  "keywords": [
    "러브라이브",
    "Aqours",
    "쿠로사와 루비",
    "루비"
  ]
}
```

공백과 영문 대소문자는 무시합니다.

`루비`처럼 짧은 단어는 다른 상품에도 우연히 포함될 수 있으니
필요하면 보다 구체적인 키워드만 남기세요.

---

# 6. GitHub Actions 실행 시간

`.github/workflows/watch.yml`

```yaml
schedule:
  - cron: "10 12 * * *"
    timezone: "Asia/Seoul"
```

즉:

```text
매일 오후 12:10 KST
```

입니다.

GitHub Actions의 예약 실행은 서버 상황에 따라 정확히 12:10:00에
시작되지 않고 약간 늦을 수 있습니다.

---

# 7. 최초 실행

Repository에서:

```text
Actions
→ Comiczone Kakao Watcher
→ Run workflow
```

최초 실행은 현재 상품들을 `seen.json`에 기록만 합니다.

따라서 기존 상품들이 카카오톡으로 한꺼번에 오지 않습니다.

다음 실행부터:

```text
신규 상품
    ↓
keywords.json 검사
    ↓
일치
    ↓
카카오톡 나와의 채팅
```

으로 동작합니다.

---

# 카카오톡 예시

```text
🔔 코믹존 키워드 신작

• [예약] 러브라이브! 선샤인!! 쿠로사와 루비 아크릴 스탠드
  키워드: 러브라이브, 쿠로사와 루비, 루비
  https://comiczone.co.kr/goods/goods_view.php?goodsNo=...
```

여러 상품이 있으면 그날 발견된 일치 상품을 한 메시지에 묶습니다.
