"""botkit - 고객사별 업무 자동화 봇을 YAML 한 장으로 찍어내는 보일러플레이트.

수집(구글시트/RSS/JSON API) -> Claude 요약 -> 텔레그램/웹훅 발송까지를
`config/jobs/<고객사>.yaml` 한 파일로 정의한다. 코드를 고치지 않고 YAML의
프롬프트와 스케줄만 바꿔서 납품하는 것이 이 패키지의 존재 이유다.

autocpna(쿠팡/네이버 제휴 파이프라인)와는 의도적으로 import 의존이 없다.
고객사 리포지터리에는 src/botkit + config/jobs + .github/workflows/botkit.yml
세 덩어리만 복사하면 그대로 돌아가야 하기 때문이다.
"""
