# 네이버 부동산 크롤러 신규 메서드 스펙

## 개요

기존 `naver_crawler.py`의 클래스 구조와 메서드는 그대로 유지하며,
아래 두 메서드를 **신규 추가**한다.

- `crawl_complexes_v2(...)` — 매물 ID 목록 수집
- `extract_detail_v2(atcl_no)` — 개별 매물 상세 정보 추출

---

## 1. 사전 수정: 지역 입력 방식 변경

### 기존
`naver_crawler.py`는 특정 방식으로 지역을 입력받고 있었음.

### 변경
피터팬, 온하우스 크롤러처럼 **`app`에서 로드된 `regions_bbox`를 사용**하여,
**시/군/구 단위를 GUI 상에서 입력받는 방식**으로 변경한다.

- 시/군 단위까지만 입력된 경우 → 해당 시/군 하위의 **동(洞)을 순회**하며 크롤링
- 동 단위까지 입력된 경우 → 해당 동 단일 bbox로 요청

각 동의 bbox(`btm`, `lft`, `top`, `rgt`)와 중심 좌표(`lat`, `lon`)는
`regions_bbox`에서 로드한 값을 사용한다.

---

## 2. `crawl_complexes_v2` 메서드

### 역할
지역 bbox 기반으로 네이버 부동산 articleList API를 페이지 순회하며
조건에 맞는 매물의 `atclNo`를 수집하고,
수집 즉시 `extract_detail_v2`를 호출하여 상세 정보를 yield한다.

### 엔드포인트
```
GET https://m.land.naver.com/cluster/ajax/articleList
```

### 세션
`self.search_sess` 사용 (기존 `__init__`에 정의된 세션)

### User-Agent
`naver_test.py`와 동일한 User-Agent 변조 방식 적용

### 요청 파라미터

| 파라미터 | 설명 | 값 |
|---------|------|----|
| `itemId` | 고정 | `""` |
| `mapKey` | 고정 | `""` |
| `lgeo` | 고정 | `""` |
| `showR0` | 고정 | `""` |
| `cortarNo` | 고정 | `""` |
| `z` | 고정 | `"12"` |
| `rletTpCd` | 매물 유형 | 기존 `realestate_type` 값에 대응 |
| `tradTpCd` | 거래 유형 | 기존 `tradeType` 값에 대응 |
| `lat` | 중심 위도 | `regions_bbox`에서 로드 |
| `lon` | 중심 경도 | `regions_bbox`에서 로드 |
| `btm` | bbox 하단 위도 | `regions_bbox`에서 로드 |
| `lft` | bbox 좌측 경도 | `regions_bbox`에서 로드 |
| `top` | bbox 상단 위도 | `regions_bbox`에서 로드 |
| `rgt` | bbox 우측 경도 | `regions_bbox`에서 로드 |
| `wprcMin` | 보증금 최솟값 | 입력값 (없으면 생략) |
| `wprcMax` | 보증금 최댓값 | 입력값 (없으면 생략) |
| `rprcMin` | 월세 최솟값 | 입력값 (없으면 생략) |
| `rprcMax` | 월세 최댓값 | 입력값 (없으면 생략) |
| `dprcMin` | 매매가 최솟값 | 입력값 (없으면 생략) |
| `dprcMax` | 매매가 최댓값 | 입력값 (없으면 생략) |
| `spcMin` | 면적 최솟값 | 입력값 (없으면 생략) |
| `spcMax` | 면적 최댓값 | 입력값 (없으면 생략) |
| `sort` | 정렬 기준 | `"dates"` 고정 |
| `page` | 페이지 번호 | `1`부터 시작하여 순회 |

### 날짜 필터링 로직

응답 `response.json()["body"]` 리스트를 순회하면서,
각 아이템의 `"atclCfmYmd"` 필드를 확인한다.

- 포맷 예시: `"26.02.27."` → `"YY.MM.DD."` 형태
- `datetime.strptime(atclCfmYmd.rstrip("."), "%y.%m.%d")` 로 파싱
- `min_date` (등록일 필터) 가 인자로 전달된 경우:
  - 해당 아티클의 날짜 < `min_date` 이면 → **즉시 `break`** (해당 동 순회 종료)
  - 해당 아티클의 날짜 >= `min_date` 이면 → 상세 추출 진행

### 페이지 순회 종료 조건

아래 중 하나라도 해당되면 해당 동의 페이지 순회를 종료:
1. 날짜 필터 `break` 발생
2. `response.json()["more"] == False` (다음 페이지 없음)
3. `response.json()["body"]` 가 비어있음

### yield 방식

`atclNo`를 구하는 즉시 `extract_detail_v2(atcl_no)`를 호출하고,
반환된 상세 데이터를 `yield`한다. (리스트로 모아서 한번에 반환하지 않음)

### 메서드 시그니처 (예시)
```python
def crawl_complexes_v2(
    self,
    realestate_type: str,
    trade_type: str,
    region: str,                  # 시/군/구/동 입력
    min_date: datetime = None,
    wprc_min: int = None,
    wprc_max: int = None,
    rprc_min: int = None,
    rprc_max: int = None,
    dprc_min: int = None,
    dprc_max: int = None,
    spc_min: int = None,
    spc_max: int = None,
):
```

---

## 3. `extract_detail_v2` 메서드

### 역할
`naver_crawler.py` 기존 614~619번째 줄의 요청 방식으로
개별 매물 상세 API를 호출하고,
기존 1041~1101번째 줄과 동일한 필드 구조로 데이터를 파싱하여 반환한다.

### 세션
`self.search_sess` 사용

### 반환값
기존 1041~1101줄의 딕셔너리 구조와 동일한 포맷의 `dict`

### 메서드 시그니처 (예시)
```python
def extract_detail_v2(self, atcl_no: str) -> dict:
```

---

## 4. 전체 흐름 요약

```
search_complexes_v2 호출
    └─ regions_bbox에서 동 목록 로드
        └─ 동 순회
            └─ page=1부터 순회
                └─ articleList API GET 요청
                    └─ body 리스트 순회
                        ├─ atclCfmYmd 날짜 체크
                        │   └─ min_date보다 이전이면 break
                        └─ extract_detail_v2(atclNo) 호출
                            └─ 상세 데이터 yield
```