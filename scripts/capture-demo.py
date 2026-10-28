"""Generate documentation screenshots using disposable sample files."""
import asyncio
import os
from pathlib import Path
import tempfile
import zipfile

# Screenshots document the default color theme, independently of CI's NO_COLOR.
os.environ.pop('NO_COLOR', None)
from mom.app import MomApp


async def capture():
    with tempfile.TemporaryDirectory(prefix='MOM-DEMO-') as temporary:
        root = Path(temporary)
        for name in ['DOS 자료실', '개발 프로젝트', '사진 앨범', '문서', 'Downloads']:
            (root / name).mkdir()
        samples = {'README.md': 'MOM 파일 관리자\n안녕하세요!\n',
                   '시작하기.txt': 'Mdir의 추억을 터미널에서', 'app.py': 'print("Hello MOM")\n',
                   'package.json': '{"name": "mom"}', 'run.sh': '#!/bin/sh\necho MOM',
                   '추억의 음악.mp3': '', '여행 사진.jpg': '', '보고서.hwp': '',
                   '프로젝트.tar.gz': '', '메모.txt': '한글 완벽 지원',
                   'INSTALL.EXE': '', 'autoexec.bat': '', '설정.toml': 'theme="DOS"'}
        for name, text in samples.items():
            (root / name).write_text(text, encoding='utf-8')
        with zipfile.ZipFile(root / '자료실.zip', 'w') as archive:
            archive.writestr('설명.txt', '압축을 풀지 않고 탐색하세요')
        app = MomApp(root)
        output = Path(__file__).resolve().parents[1] / 'docs'
        output.mkdir(exist_ok=True)
        async with app.run_test(size=(144, 36)) as pilot:
            await pilot.pause()
            await app.workers.wait_for_complete()
            app.state.cursor = next(i for i, entry in enumerate(app.state.entries) if entry.name == 'README.md')
            app.state.marked = {'app.py', '메모.txt'}
            app.redraw()
            await pilot.pause()
            app.save_screenshot('mom-single.svg', path=output)
            await pilot.press('tab', 'ctrl+right')
            await pilot.pause()
            app.save_screenshot('mom-dual.svg', path=output)


if __name__ == '__main__':
    asyncio.run(capture())
