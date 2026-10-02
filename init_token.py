"""
최초 1회 실행용.

사용법:
1) pip install cryptography
2) python init_token.py

프로그램이 Fernet 키를 생성하고 카카오 Refresh Token을 입력받습니다.
출력되는 KAKAO_TOKEN_KEY는 GitHub Secret으로 저장하고,
생성되는 kakao_refresh_token.enc는 저장소에 올리세요.
"""

from getpass import getpass
from pathlib import Path
from cryptography.fernet import Fernet

OUT = Path("kakao_refresh_token.enc")

key = Fernet.generate_key()
refresh_token = getpass("카카오 Refresh Token 입력: ").strip()

if not refresh_token:
    raise SystemExit("Refresh Token이 비어 있습니다.")

OUT.write_bytes(Fernet(key).encrypt(refresh_token.encode("utf-8")))

print()
print("완료.")
print("GitHub Secret KAKAO_TOKEN_KEY 값:")
print(key.decode())
print()
print("생성 파일:", OUT)
print("이 파일은 GitHub 저장소에 올리세요.")
