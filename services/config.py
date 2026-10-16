"""API 키를 한 곳에서 읽는다 - 로컬은 .env, 배포(Streamlit Cloud)는 st.secrets.

배포 환경에는 .env 파일이 올라가지 않는다(gitignore 대상). 그래서 os.getenv만 쓰면
배포하는 순간 카카오·Claude 호출이 전부 실패한다. 둘 다 보도록 여기서 묶는다.

환경변수를 먼저 보는 이유: 로컬에서 .env로 작업하던 흐름을 그대로 두기 위해서다.
배포에서는 환경변수가 비어 있으니 st.secrets가 쓰인다.
"""

import os
import sys

from dotenv import load_dotenv

load_dotenv()

# Windows 콘솔에서 한글 출력이 깨지는 것을 방지
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def get_secret(name, default=None):
    """환경변수(.env) -> st.secrets 순으로 값을 찾는다.

    st.secrets는 secrets.toml이 없으면 접근만 해도 예외를 던지고, Streamlit 밖(CLI
    스크립트)에서는 아예 쓸 수 없다. 그래서 통째로 감싼다.
    """
    value = os.getenv(name)
    if value:
        return value

    try:
        import streamlit as st

        secrets = st.secrets
        if name in secrets:
            return secrets[name]
    except Exception:
        # secrets.toml 없음 / Streamlit 런타임 밖 - 둘 다 "값이 없다"로 본다
        pass

    return default


def has_secret(name):
    """키가 설정되어 있는지만 확인한다 (값은 로그에 남기지 않는다)."""
    return bool(get_secret(name))
