from qqbot.qq_chat import PERSONALITY,fatfish_personality


def test_fatfish_profile_keeps_character_and_uses_native_protocol():
    native=fatfish_personality()
    assert '哦鲸鲸' in native and '群友' in native and '做事仍然靠谱' in native
    assert '[[表情:目录名字]]' in native
    assert 'reply_mode' not in native and 'image_prompt' not in native and '只输出JSON' not in native
    assert '只输出JSON' in PERSONALITY  # the compatible legacy engine retains its own protocol


def test_profile_keeps_user_boundaries_and_action_grounding():
    native=fatfish_personality()
    for phrase in ['不针对人','不卖惨','不编现实经历','工具没有确认','22:00—09:00','不能连续同一张','不把私聊里的事拿到群里说']:
        assert phrase in native
