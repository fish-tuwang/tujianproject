from qqbot.fatfish_extensions.song_truth import audio_fallback


def test_codec_failure_has_file_fallback_but_network_failure_does_not_retry():
    p={'message':[{'type':'record','data':{'file':'/private/song.wav'}}]}
    assert audio_fallback(p,{'retcode':200,'message':"Requested output format 'ntsilk_s16le' is not a suitable output format"})=='/private/song.wav'
    assert audio_fallback(p,{'retcode':0}) is None
    assert audio_fallback(p,{'retcode':200,'message':'timeout'}) is None
    assert audio_fallback({'message':[]},{'retcode':200,'message':'ntsilk_s16le'}) is None
