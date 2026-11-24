from qqbot.fatfish_extensions.no_echo import clean


def test_screenshot_echo_openings_are_removed():
    assert clean('来唱一首歌？ 🎤\n可以，想听哪首？','来唱一首歌') == '可以，想听哪首？'
    assert clean('随便一首日文歌？\n推荐一首。','随便一首日文歌') == '推荐一首。'
    assert clean('手？','手') == ''
    assert clean('小本本？','小本本') == ''


def test_substantive_reply_and_requested_transformation_are_retained():
    assert clean('这首歌叫晴天。','唱晴天') == '这首歌叫晴天。'
    assert clean('你好','翻译hello') == '你好'
    assert clean('[[表情:睡觉]]','睡觉') == '[[表情:睡觉]]'
