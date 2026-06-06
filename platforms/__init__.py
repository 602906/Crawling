from .kugou import KuGouPlatform
from .netease import NetEasePlatform
from .qqmusic import QQMusicPlatform
from .bilibili import BilibiliPlatform

PLATFORMS = {
    "kugou": KuGouPlatform,
    "netease": NetEasePlatform,
    "qqmusic": QQMusicPlatform,
    "bilibili": BilibiliPlatform,
}
