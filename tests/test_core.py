from pathlib import Path
import io
import os
import tarfile
import zipfile
import pytest
from wcwidth import wcswidth
from mom.archives import Archive, member_name
from mom.cli import write_last_directory
from mom.display import color, fit, safe
from mom.filesystem import (Entry, PanelState, decode_text, expanded, listing,
                            read_text, remove, transfer, validate_transfer)


@pytest.mark.parametrize('value', ['한글 파일명.txt', 'e\u0301é.txt', '👩\u200d💻 파일🌏', 'a\x1b[31m', 'a\nb', '아' * 100])
@pytest.mark.parametrize('width', [0, 1, 2, 7, 20])
def test_cell_width(value, width):
    assert wcswidth(fit(value, width)) == width
    assert '\x1b' not in fit(value, width)
    assert '\n' not in fit(value, width)


def test_color_priority():
    assert color(Entry('a.py', 'a.py', executable=True)) == '#ffff55'
    assert color(Entry('X.ZIP', 'X.ZIP', executable=True)) == '#ff55ff'
    assert color(Entry('a.app', 'a.app', is_dir=True)) == '#55ff55'
    assert color(Entry('폴더', '폴더', is_dir=True)) == 'bold #ffff55'
    assert color(Entry('run', 'run', executable=True)) == '#55ff55'


def test_listing_sort_mark(tmp_path):
    (tmp_path / '한글.txt').write_text('abc')
    (tmp_path / 'z').mkdir()
    (tmp_path / 'a.py').write_text('print(1)')
    state = PanelState(tmp_path)
    state.install(listing(tmp_path))
    assert [e.name for e in state.entries] == ['..', 'z', 'a.py', '한글.txt']
    state.mark()
    assert not state.marked
    state.cursor = 2
    state.mark()
    assert state.marked == {'a.py'} and state.cursor == 3
    assert [e.name for e in state.selected()] == ['a.py']
    state.sort_by, state.reverse = 'size', True
    state.install(state.entries)
    assert state.entries[0].parent and state.entries[1].is_dir
    state.jump('한')
    assert state.current.name == '한글.txt'
    assert expanded('../a', tmp_path) == tmp_path.parent / 'a'


def test_copy_move_overwrite_and_links(tmp_path):
    source = tmp_path / '한 글.txt'
    source.write_text('old')
    target = tmp_path / 'copied'
    transfer(source, target)
    assert target.read_text() == 'old' and source.exists()
    source.write_text('new')
    with pytest.raises(FileExistsError):
        transfer(source, target)
    assert target.read_text() == 'old'
    transfer(source, target, overwrite=True)
    assert target.read_text() == 'new'
    renamed = tmp_path / 'renamed'
    transfer(target, renamed, move=True)
    assert not target.exists() and renamed.read_text() == 'new'
    directory = tmp_path / 'dir'
    directory.mkdir()
    (directory / 'child').write_text('child')
    (directory / 'link').symlink_to(source)
    transfer(directory, tmp_path / 'dir2')
    assert (tmp_path / 'dir2/link').is_symlink()
    transfer(directory, tmp_path / 'dir2', overwrite=True)
    with pytest.raises(ValueError):
        transfer(directory, directory / 'recursive')
    with pytest.raises(ValueError):
        validate_transfer(source, source)
    with pytest.raises(ValueError):
        validate_transfer(directory / 'child', directory)
    remove(tmp_path / 'dir2')
    assert source.exists() and not (tmp_path / 'dir2').exists()
    assert not list(tmp_path.glob('.mom-*'))


def test_encoding_and_binary(tmp_path):
    for encoding in ['utf-8', 'utf-8-sig', 'cp949']:
        path = tmp_path / encoding
        path.write_bytes('안녕하세요\n둘째 줄'.encode(encoding))
        text, detected, truncated = read_text(path)
        assert text == '안녕하세요\n둘째 줄' and not truncated
        assert ('CP949' if encoding == 'cp949' else 'UTF-8') in detected
    with pytest.raises(ValueError):
        decode_text(b'ab\x00cd')
    text, encoding = decode_text(b'\xff\xff')
    assert '대체' in encoding
    assert decode_text('한글'.encode()[:-1], truncated=True)[0] == '한'


@pytest.mark.parametrize('name', ['../escape', '/root', 'C:/escape', 'a/../../b', 'a\\b', 'a/C:evil', '.'])
def test_unsafe_names(name):
    with pytest.raises(ValueError):
        member_name(name)


@pytest.fixture(params=['zip', 'tar.gz'])
def archive_file(tmp_path, request):
    path = tmp_path / ('테스트.' + request.param)
    if request.param == 'zip':
        with zipfile.ZipFile(path, 'w') as stream:
            stream.writestr('폴더/한글.txt', '보라 뷰어\n검색 내용'.encode('cp949'))
            stream.writestr('plain.txt', 'hello')
            stream.writestr('../escape', 'bad')
            link = zipfile.ZipInfo('link')
            link.external_attr = (0o120777 << 16)
            stream.writestr(link, '/tmp')
    else:
        with tarfile.open(path, 'w:gz') as stream:
            for name, data in [('폴더/한글.txt', '보라 뷰어\n검색 내용'.encode('cp949')), ('plain.txt', b'hello'), ('../escape', b'bad')]:
                member = tarfile.TarInfo(name)
                member.size = len(data)
                stream.addfile(member, io.BytesIO(data))
            link = tarfile.TarInfo('link')
            link.type = tarfile.SYMTYPE
            link.linkname = '/tmp'
            stream.addfile(link)
    return path


def test_archive_navigation_extract(archive_file, tmp_path):
    archive = Archive(archive_file)
    assert archive.blocked == 2
    assert {e.name for e in archive.listing()} == {'..', '폴더', 'plain.txt'}
    assert {e.name for e in archive.listing('폴더')} == {'..', '한글.txt'}
    assert archive.read_text('폴더/한글.txt')[0].startswith('보라')
    target = tmp_path / 'out'
    target.mkdir()
    archive.extract(['폴더', 'plain.txt'], target)
    assert (target / '폴더/한글.txt').read_bytes().decode('cp949').startswith('보라')
    assert (target / 'plain.txt').read_text() == 'hello'
    assert not (tmp_path / 'escape').exists()
    with pytest.raises(FileExistsError):
        archive.extract(['plain.txt'], target)
    archive.extract(['plain.txt'], target, overwrite=True)


def test_extract_symlink_parent(archive_file, tmp_path):
    archive = Archive(archive_file)
    target, outside = tmp_path / 'out', tmp_path / 'outside'
    target.mkdir()
    outside.mkdir()
    (target / '폴더').symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        archive.extract(['폴더'], target, overwrite=True)
    assert not list(outside.iterdir())


def test_archive_limits(tmp_path, monkeypatch):
    from mom import archives
    path = tmp_path / 'a.zip'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('a', 'hello')
        archive.writestr('b', 'world')
    monkeypatch.setattr(archives, 'MAX_MEMBERS', 1)
    with pytest.raises(ValueError):
        Archive(path)
    monkeypatch.setattr(archives, 'MAX_MEMBERS', 100)
    monkeypatch.setattr(archives, 'MAX_BYTES', 2)
    with pytest.raises(OverflowError):
        Archive(path)


def test_last_directory(tmp_path):
    directory = tmp_path / '공백 포함\n경로'
    directory.mkdir()
    record = tmp_path / 'last'
    write_last_directory(record, directory)
    assert os.fsdecode(record.read_bytes()) == str(directory)
    assert not list(tmp_path.glob('.mom-last-*'))
