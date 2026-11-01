from .kugou import KuGouPlatform
from .netease import NetEasePlatform
from .bilibili import BilibiliPlatform
from .qqmusic import QQMusicPlatform

PLATFORMS = {
    "kugou": KuGouPlatform,
    "netease": NetEasePlatform,
    "bilibili": BilibiliPlatform,
    "qqmusic": QQMusicPlatform,
}
