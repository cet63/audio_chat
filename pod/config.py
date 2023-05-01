import dataclasses
import logging
from pathlib import Path


@dataclasses.dataclass
class ModelSpec:
    name: str
    params: str
    relative_speed: int  # Higher is faster


def get_logger(name, level=logging.INFO):
    logger = logging.getLogger(name)
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(levelname)s: %(asctime)s: %(name)s  %(message)s")
    )
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False  # Prevent the modal client from double-logging.
    return logger


CACHE_DIR = "/cache"
# Where downloaded audios are stored, by guid hash.
# Mostly .mp3 files 50-100MiB.
RAW_AUDIO_DIR = Path(CACHE_DIR, "raw_audio")
# stores metadata of audios as JSON.
METADATA_DIR = Path(CACHE_DIR, "ep_metadata")

# Completed episode transcriptions. Stored as flat files with
# files structured as '{guid_hash}.json'.
TRANSCRIPTIONS_DIR = Path(CACHE_DIR, "transcriptions")

# stores vector indexes
VECTORINDEX_DIR = Path(CACHE_DIR, "index")
# stores summaries
SUMMARY_DIR = Path(CACHE_DIR, "summary")

# Location of modal checkpoint.
MODEL_DIR = Path(CACHE_DIR, "model")
# Location of web frontend assets.
ASSETS_PATH = Path(__file__).parent / "frontend" / "dist"

transcripts_per_podcast_limit = 2

supported_whisper_models = {
    "tiny.en": ModelSpec(name="tiny.en", params="39M", relative_speed=32),
    # Takes around 3-10 minutes to transcribe a podcast, depending on length.
    "base.en": ModelSpec(name="base.en", params="74M", relative_speed=16),
    "small.en": ModelSpec(name="small.en", params="244M", relative_speed=6),
    "medium.en": ModelSpec(name="medium.en", params="769M", relative_speed=2),
    # Very slow. Will take around 45 mins to 1.5 hours to transcribe.
    #"large": ModelSpec(name="large", params="1550M", relative_speed=1),

    "base": ModelSpec(name="base", params="74M", relative_speed=16),
    "small": ModelSpec(name="small", params="244M", relative_speed=6),
    "medium": ModelSpec(name="medium", params="769M", relative_speed=2),
    "large": ModelSpec(name="large-v2", params="1550M", relative_speed=1),
}

DEFAULT_MODEL = supported_whisper_models["small"]
