from .kugou import KuGouPlatform
from .netease import NetEasePlatform
from .bilibili import BilibiliPlatform

PLATFORMS = {
    "kugou": KuGouPlatform,
    "netease": NetEasePlatform,
    "bilibili": BilibiliPlatform,
}
