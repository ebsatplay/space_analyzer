"""SK Open API "데이터 제공 가능 장소" 목록 조회 검증용 스크립트.

실행: python services/skt_probe.py

429(quota) 등으로 중간에 멈추면 그때까지 받은 데이터를 CSV로 저장하고,
다음 실행할 offset을 진행 상황 파일에 기록한다. 다시 실행하면 그 지점부터 이어받는다.
"""

import json
import os
import sys
import time

import pandas as pd
import requests
from dotenv import load_dotenv

API_URL = "https://apis.openapi.sk.com/puzzle/place/meta/pois"
OUTPUT_DIR = os.path.join("data", "processed")
OUTPUT_PATH = os.path.join(OUTPUT_DIR, "skt_pois.csv")
PROGRESS_PATH = os.path.join(OUTPUT_DIR, "skt_pois_progress.json")
PAGE_SIZE = 1000
REQUEST_INTERVAL_SEC = 3.0

# Windows 콘솔에서 한글 출력이 깨지는 것을 방지
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def fetch_page(app_key, offset):
    headers = {
        "appkey": app_key,
        "Accept": "application/json",
    }
    params = {
        "offset": offset,
        "limit": PAGE_SIZE,
    }
    return requests.get(API_URL, headers=headers, params=params, timeout=10)


def load_resume_state():
    """이전에 중단된 지점이 있으면 (시작 offset, 기존 수집분)을 반환한다."""
    if not os.path.exists(PROGRESS_PATH) or not os.path.exists(OUTPUT_PATH):
        return 0, []

    with open(PROGRESS_PATH, "r", encoding="utf-8") as f:
        progress = json.load(f)

    existing_df = pd.read_csv(OUTPUT_PATH, dtype=str, encoding="utf-8-sig")
    existing_contents = existing_df.to_dict("records")

    next_offset = progress.get("next_offset", 0)
    print(f"이전에 중단된 지점을 찾았습니다. offset={next_offset}부터 이어받습니다. (기존 {len(existing_contents)}개)")
    return next_offset, existing_contents


def save_results(all_contents):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    df = pd.DataFrame(all_contents, columns=["poiId", "poiName"])
    df = df.sort_values("poiName").reset_index(drop=True)
    df.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")
    return len(df)


def save_progress(next_offset, total_count):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(PROGRESS_PATH, "w", encoding="utf-8") as f:
        json.dump({"next_offset": next_offset, "total_count": total_count}, f, ensure_ascii=False, indent=2)


def clear_progress():
    if os.path.exists(PROGRESS_PATH):
        os.remove(PROGRESS_PATH)


def stop_and_save(all_contents, resume_offset, total_count, last_success_offset, reason):
    print(reason)
    print(f"마지막으로 성공한 offset: {last_success_offset}")

    if all_contents:
        saved_count = save_results(all_contents)
        save_progress(resume_offset, total_count)
        print(f"지금까지 수집된 개수: {saved_count}")
        print(f"저장 완료: {OUTPUT_PATH}")
        print(f"다음 실행 시 offset={resume_offset}부터 이어받습니다.")
    else:
        print("이번 실행에서 새로 수집된 데이터가 없어 기존 파일은 변경하지 않았습니다.")


def main():
    load_dotenv()
    app_key = os.getenv("SKT_APP_KEY")

    if not app_key:
        print("SKT_APP_KEY가 설정되어 있지 않습니다. .env 파일을 확인해주세요.")
        return

    offset, all_contents = load_resume_state()
    total_count = None
    last_success_offset = None

    while True:
        try:
            response = fetch_page(app_key, offset)
        except requests.exceptions.RequestException as e:
            stop_and_save(
                all_contents, offset, total_count, last_success_offset,
                reason=f"API 호출 중 네트워크 오류가 발생했습니다: {e}",
            )
            return

        if response.status_code != 200:
            stop_and_save(
                all_contents, offset, total_count, last_success_offset,
                reason=f"API 호출 실패 (status={response.status_code}, offset={offset})\n{response.text}",
            )
            return

        body = response.json()
        status = body.get("status", {})
        status_code = status.get("code")

        if status_code is not None and status_code != "00":
            stop_and_save(
                all_contents, offset, total_count, last_success_offset,
                reason=f"API에서 에러 응답을 받았습니다 (code={status_code}, offset={offset})\n{status.get('message')}",
            )
            return

        if total_count is None:
            total_count = status.get("totalCount")
            print(f"totalCount: {total_count}")

        contents = body.get("contents", [])
        if not contents:
            break

        all_contents.extend(contents)
        last_success_offset = offset
        offset += PAGE_SIZE
        print(f"수집 중... {len(all_contents)}/{total_count} (offset={last_success_offset} 성공)")

        if total_count is not None and offset >= total_count:
            break

        time.sleep(REQUEST_INTERVAL_SEC)

    saved_count = save_results(all_contents)
    clear_progress()

    print(f"\n전체 수집 완료. 최종 수집 개수: {saved_count} / totalCount: {total_count}")
    print(f"저장 완료: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
