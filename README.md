# 정진호의 물가일기

- 홈페이지: https://jmsk300.github.io/
- 미니게임: https://jmsk300.github.io/games/
- 출조 기록 보기: https://jmsk300.github.io/planner/

## 날짜별 출조 도우미

작업 폴더에서 출조도우미-실행.bat을 두 번 눌러 실행하거나 아래 명령을 사용합니다.

    python outing_helper.py

브라우저가 로컬 편집 화면을 엽니다. 날씨는 Open-Meteo에서 자동 조회하며, 물때는 국립해양조사원 조석예보 API 키와 관측소 코드가 있을 때 자동 조회할 수 있습니다. 인증키 없이도 날씨 메모와 물때를 직접 기록할 수 있습니다.

기록은 기본적으로 내 컴퓨터의 outing_records.json에 저장됩니다. 공개하려는 항목에만 **홈페이지에 공개**를 체크하세요. 공개 기록은 data/outings.json에 생성되며, 이 파일을 GitHub에 반영하면 홈페이지의 출조 기록 페이지에 표시됩니다. API 인증키는 outing_config.json에 로컬 저장되며 Git에 포함되지 않습니다.
