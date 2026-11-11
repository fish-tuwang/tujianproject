"""Supplemental search spellings; source names remain unchanged."""
import re
import unicodedata

# Longer spellings take precedence (Mark X before the Japanese word マーク).
ALIASES = (
    ('pandorobou', ('パンどろぼう', 'Pandorobou', 'Pandorobo', 'Bread Thief', '面包小偷', '麵包小偷')),
    ('ghibli', ('ジブリ', 'Ghibli', '吉卜力', '吉卜莉')),
    ('totoro', ('トトロ', 'Totoro', '龙猫', '龍貓')),
    ('snoopy', ('スヌーピー', 'Snoopy', '史努比')),
    ('hellokitty', ('ハローキティ', 'Hello Kitty', '凯蒂猫', '凱蒂貓')),
    ('doraemon', ('ドラえもん', 'Doraemon', '哆啦A梦', '哆啦A夢')),
    ('chiikawa', ('ちいかわ', 'Chiikawa', '吉伊卡哇')),
    ('kirby', ('カービィ', 'Kirby', '星之卡比', '卡比')),
    ('sanrio', ('サンリオ', 'Sanrio', '三丽鸥', '三麗鷗')),
    ('disney', ('ディズニー', 'Disney', '迪士尼')),
    ('tomandjerry', ('トムとジェリー', 'Tom and Jerry', '猫和老鼠', '貓和老鼠')),
    ('anpanman', ('アンパンマン', 'Anpanman', '面包超人', '麵包超人')),
    ('howl', ('ハウル', 'Howl', '哈尔', '霍爾')),
    ('hungrycaterpillar', ('はらぺこあおむし', 'Hungry Caterpillar', '好饿的毛毛虫', '好餓的毛毛蟲')),
    ('nenaiko', ('ねないこだれだ', 'ねないこだれ')),
    ('toyota', ('Toyota', 'トヨタ', '丰田', '豐田')),
    ('nissan', ('Nissan', 'ニッサン', '日産', '日产', '日產')),
    ('honda', ('Honda', 'ホンダ', '本田')),
    ('mazda', ('Mazda', 'マツダ', '马自达', '馬自達')),
    ('subaru', ('Subaru', 'スバル', '斯巴鲁', '斯巴魯')),
    ('mitsubishi', ('Mitsubishi', '三菱')),
    ('suzuki', ('Suzuki', 'スズキ', '铃木', '鈴木')),
    ('daihatsu', ('Daihatsu', 'ダイハツ', '大发', '大發')),
    ('isuzu', ('Isuzu', 'いすゞ', '五十铃', '五十鈴')),
    ('hino', ('Hino', '日野')),
    ('ford', ('Ford', 'フォード', '福特')),
    ('porsche', ('Porsche', 'ポルシェ', '保时捷', '保時捷')),
    ('ferrari', ('Ferrari', 'フェラーリ', '法拉利')),
    ('lamborghini', ('Lamborghini', 'ランボルギーニ', '兰博基尼', '蘭博基尼')),
    ('mercedesbenz', ('Mercedes-Benz', 'メルセデス', '奔驰', '奔馳')),
    ('bmw', ('BMW', '宝马', '寶馬')),
    ('volkswagen', ('Volkswagen', 'フォルクスワーゲン', '大众', '大眾')),
    ('markx', ('Mark X', 'マークX', 'Reiz', '锐志', '銳志')),
    ('markii', ('Mark II', 'マークII')),
    ('mark', ('マーク',)),
    ('crown', ('Crown', 'クラウン', '皇冠')),
    ('corolla', ('Corolla', 'カローラ', '卡罗拉', '卡羅拉', '花冠')),
    ('camry', ('Camry', 'カムリ', '凯美瑞', '凱美瑞', '佳美')),
    ('supra', ('Supra', 'スープラ')),
    ('celica', ('Celica', 'セリカ')),
    ('prius', ('Prius', 'プリウス', '普锐斯', '普銳斯')),
    ('landcruiser', ('Land Cruiser', 'ランドクルーザー', '陆地巡洋舰', '蘭德酷路澤', '兰德酷路泽')),
    ('alphard', ('Alphard', 'アルファード', '埃尔法', '埃爾法')),
    ('vellfire', ('Vellfire', 'ヴェルファイア', '威尔法', '威爾法')),
    ('hiace', ('Hiace', 'ハイエース', '海狮', '海獅')),
    ('skyline', ('Skyline', 'スカイライン', '天际线', '天際線')),
    ('fairladyz', ('Fairlady Z', 'フェアレディZ')),
    ('silvia', ('Silvia', 'シルビア')),
    ('bluebird', ('Bluebird', 'ブルーバード', '蓝鸟', '藍鳥')),
    ('cedric', ('Cedric', 'セドリック')),
    ('sunny', ('Sunny', 'サニー', '阳光', '陽光')),
    ('civic', ('Civic', 'シビック', '思域')),
    ('accord', ('Accord', 'アコード', '雅阁', '雅閣')),
    ('fit', ('Fit', 'フィット', '飞度', '飛度')),
    ('integra', ('Integra', 'インテグラ')),
    ('impreza', ('Impreza', 'インプレッサ', '翼豹')),
    ('forester', ('Forester', 'フォレスター', '森林人')),
    ('lancer', ('Lancer', 'ランサー', '蓝瑟', '藍瑟')),
    ('demio', ('Demio', 'デミオ')),
    ('axela', ('Axela', 'アクセラ', '昂克赛拉', '昂克賽拉')),
    ('atenza', ('Atenza', 'アテンザ', '阿特兹', '阿特茲')),
    ('swift', ('Swift', 'スイフト', '雨燕')),
    ('jimny', ('Jimny', 'ジムニー', '吉姆尼')),
    ('taxi', ('Taxi', 'タクシー', '出租车', '出租車')),
    ('coupe', ('Coupe', 'クーペ')),
    ('patrolcar', ('Patrol Car', 'パトロールカー', '警车', '警車')),
)


def compact(value):
    return ''.join(c for c in unicodedata.normalize('NFKC', str(value or '')).casefold() if c.isalnum() or c == 'ー')


SPELLINGS = {compact(alias): key for key, names in ALIASES for alias in names}
PATTERN = re.compile('|'.join(re.escape(alias) for alias in sorted(SPELLINGS, key=len, reverse=True)))


def canonical(value):
    return PATTERN.sub(lambda match: ' ' + SPELLINGS[match[0]] + ' ', compact(value))


def matches_car(row, query):
    terms = canonical(query).split()
    if not terms:
        return False
    fields = ['number', 'name_original', 'name_display', 'brand']
    if not str(row.get('source_locator') or '').startswith('edition:'):
        fields.append('source_locator')
    # Keep field boundaries so a query cannot match across unrelated fields.
    values = [value for field in fields for value in (compact(row.get(field)), compact(canonical(row.get(field))))]
    return all(any(term in value for value in values) for term in terms)
