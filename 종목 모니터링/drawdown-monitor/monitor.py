"""작업 스케줄러가 30분마다 실행하는 진입점. 화면 없이 돌고 결과는 logs/monitor.log에 남긴다."""
import core

if __name__ == '__main__':
    core.setup_logging()
    try:
        core.log.info(core.run_check().replace('\n', ' / '))
    except Exception:
        core.log.exception('점검 중 예외')
