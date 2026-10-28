from pathlib import Path
import zipfile
import pytest
from textual.widgets import Input, DirectoryTree
from wcwidth import wcswidth
from mom.app import MomApp
from mom.screens import Choice, Prompt, TreeScreen, Viewer, ViewerBody
from mom.widgets import FilePanel


async def settle(app, pilot):
    await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause()


def select(app, name):
    app.state.cursor = next(i for i, entry in enumerate(app.state.entries) if entry.name == name)
    app.redraw()


@pytest.mark.parametrize('size', [(60, 18), (80, 24), (120, 32), (180, 45)])
async def test_render_navigation_modes(tmp_path, size):
    for i in range(100):
        (tmp_path / f'{i:03d} 한글 👩‍💻 파일.txt').write_text('hello')
    app = MomApp(tmp_path)
    async with app.run_test(size=size) as pilot:
        await settle(app, pilot)
        assert 'MOM' in app.query_one('#brand').render().plain
        assert 'Path:' in app.query_one('#status').render().plain
        assert 'F1' in app.query_one('#keybar').render().plain
        panel = app.query_one('#panel-0', FilePanel)
        assert not app.dual
        assert panel.geometry()[1] == 1
        assert not app.query_one('#panel-1').display
        assert 'SINGLE' in app.query_one('#brand').render().plain
        rendered = panel.render().plain
        assert all(wcswidth(line) == panel.content_size.width for line in rendered.splitlines())
        await pilot.press('down', 'space')
        assert len(app.state.marked) == 1 and app.state.cursor == 2
        await pilot.press('right')
        assert app.state.cursor == 2 + panel.rows
        await pilot.press('end')
        assert app.state.cursor == len(app.state.entries) - 1
        await pilot.press('home', 'pagedown')
        assert app.state.cursor == min(len(app.state.entries) - 1, panel.rows * panel.columns)
        await pilot.press('tab', 'ctrl+right')
        assert app.dual and app.active == 1
        assert app.query_one('#panel-0').display
        assert app.query_one('#panel-1').display
        assert all(p.geometry()[1] == 1 for p in app.query(FilePanel))
        assert 'DUAL' in app.query_one('#brand').render().plain
        assert app.panels[0].marked
        await pilot.press('down', 'tab')
        assert not app.dual and app.active == 0 and app.panels[1].cursor == 1
        assert not app.query_one('#panel-1').display
        assert panel.geometry()[1] == 1
        await pilot.resize_terminal(40, 12)
        await pilot.pause()
        assert app.query_one('#too-small').display
        await pilot.resize_terminal(*size)
        await pilot.pause()
        assert not app.query_one('#too-small').display


async def test_prompt_and_viewer_key_isolation(tmp_path):
    (tmp_path / '한글.txt').write_bytes('보라\n찾기\n한글 검색\n찾기'.encode('cp949'))
    app = MomApp(tmp_path)
    async with app.run_test(size=(100, 28)) as pilot:
        await settle(app, pilot)
        await pilot.press('k')
        assert isinstance(app.screen, Prompt)
        await pilot.press('q', 'm', 'c', 'd')
        assert app.screen.query_one(Input).value == 'qmcd'
        await pilot.press('escape')
        assert not (tmp_path / 'qmcd').exists()
        select(app, '한글.txt')
        await pilot.press('enter')
        await settle(app, pilot)
        assert isinstance(app.screen, Viewer)
        assert 'CP949' in app.screen.encoding
        await pilot.press('slash')
        app.screen.query_one(Input).value = '찾기'
        await pilot.press('enter')
        body = app.screen.query_one(ViewerBody)
        assert body.matches == [1, 3]
        await pilot.press('n')
        assert body.match_index == 1
        await pilot.press('N')
        assert body.match_index == 0
        await pilot.press('escape')
        assert app.state.current.name == '한글.txt'
        await pilot.press('slash')
        app.screen.query_one(Input).value = '한'
        await pilot.pause()
        assert app.state.current.name == '한글.txt'
        await pilot.press('escape')


async def test_file_commands_and_confirmation(tmp_path):
    source, destination = tmp_path / 'source', tmp_path / 'destination'
    source.mkdir()
    destination.mkdir()
    (source / 'file.txt').write_text('content')
    (destination / 'file.txt').write_text('existing')
    app = MomApp(source)
    async with app.run_test(size=(120, 32)) as pilot:
        await settle(app, pilot)
        app.browse(app.panels[1], destination)
        await settle(app, pilot)
        await pilot.press('tab')
        select(app, 'file.txt')
        await pilot.press('c', 'enter')
        await pilot.pause()
        assert isinstance(app.screen, Choice)
        await pilot.click('#cancel')
        await settle(app, pilot)
        assert (destination / 'file.txt').read_text() == 'existing'
        await pilot.press('f5', 'enter')
        await pilot.pause()
        await pilot.click('#overwrite')
        await settle(app, pilot)
        assert (destination / 'file.txt').read_text() == 'content'
        await pilot.press('f2')
        app.screen.query_one(Input).value = '새 이름.txt'
        await pilot.press('enter')
        await settle(app, pilot)
        assert (source / '새 이름.txt').exists()
        select(app, '새 이름.txt')
        await pilot.press('f6', 'enter')
        await settle(app, pilot)
        assert not (source / '새 이름.txt').exists()
        assert (destination / '새 이름.txt').exists()
        await pilot.press('f7')
        app.screen.query_one(Input).value = '새 폴더'
        await pilot.press('enter')
        await settle(app, pilot)
        assert (source / '새 폴더').is_dir()
        select(app, '새 폴더')
        await pilot.press('delete', 'escape')
        assert (source / '새 폴더').is_dir()
        await pilot.press('d')
        await pilot.click('#delete')
        await settle(app, pilot)
        assert not (source / '새 폴더').exists()


async def test_archive_ui_and_tree(tmp_path):
    path = tmp_path / 'test.zip'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('폴더/안녕.txt', '안녕하세요')
    destination = tmp_path / 'out'
    destination.mkdir()
    app = MomApp(tmp_path)
    async with app.run_test(size=(120, 32)) as pilot:
        await settle(app, pilot)
        select(app, 'test.zip')
        await pilot.press('enter')
        await settle(app, pilot)
        assert app.state.archive
        select(app, '폴더')
        await pilot.press('enter')
        await settle(app, pilot)
        assert app.state.prefix == '폴더'
        select(app, '안녕.txt')
        await pilot.press('v')
        await settle(app, pilot)
        assert isinstance(app.screen, Viewer)
        await pilot.press('escape', 'c')
        app.screen.query_one(Input).value = str(destination)
        await pilot.press('enter')
        await settle(app, pilot)
        assert (destination / '안녕.txt').read_text() == '안녕하세요'
        await pilot.press('backspace')
        await settle(app, pilot)
        assert app.state.archive and not app.state.prefix
        await pilot.press('backspace')
        await settle(app, pilot)
        assert app.state.archive is None
        await pilot.press('f9')
        await pilot.pause()
        assert isinstance(app.screen, TreeScreen)
        assert app.screen.query_one(DirectoryTree).path == tmp_path
        await pilot.press('escape', 'a')
        await pilot.press('down', 'down', 'enter')
        assert app.state.sort_by == 'size'
        await pilot.press('f1', 'escape')
