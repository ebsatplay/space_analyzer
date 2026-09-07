# Space Analyzer

KOSIS(국가통계포털) API를 활용한 데이터 분석 Streamlit 애플리케이션.

## 프로젝트 구조

```
space_analyzer/
├── app.py                # Streamlit 앱 진입점 (예정)
├── data/
│   └── raw/               # 원본 데이터 (git 추적 제외)
├── .env                   # 환경 변수 (git 추적 제외, .env.example 참고)
├── .env.example           # 환경 변수 템플릿
├── requirements.txt       # Python 의존성
└── README.md
```

## 시작하기

### 1. 가상환경 설정

```bash
python -m venv .venv
.venv\Scripts\activate      # Windows
source .venv/bin/activate   # macOS/Linux
```

### 2. 의존성 설치

```bash
pip install -r requirements.txt
```

### 3. 환경 변수 설정

`.env.example`을 복사해 `.env` 파일을 만들고 API 키를 채워 넣습니다.

```bash
cp .env.example .env
```

```
KOSIS_API_KEY=발급받은_API_키
```

### 4. 앱 실행

```bash
streamlit run app.py
```

## 상태

현재 프로젝트 구조만 초기화된 상태이며, 실제 API 연동 및 앱 로직은 아직 구현되지 않았습니다.
