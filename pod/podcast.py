import dataclasses
from pathlib import Path
import urllib.request
from typing import NamedTuple, Optional, TypedDict

from . import config

logger = config.get_logger(__name__)
Segment = TypedDict("Segment", {"text": str, "start": float, "end": float})
MAX_FILE = 300 * 1024 * 1024 #300mb


@dataclasses.dataclass
class EpisodeMetadata:
    # The publish date of the episode as specified by the publisher
    publish_date: str
    # Hash the guid into something appropriate for filenames.
    guid_hash: str
    
    transcribed: bool
    # Link to audio file for episode. Typically an .mp3 file.
    original_download_link: str
    # Used to detect non-English podcasts.
    language: Optional[str] = None


class DownloadResult(NamedTuple):
    data: bytes
    # Helpful to store and transmit when uploading to cloud bucket.
    content_type: str


def download_file(url: str) -> DownloadResult:
    req = urllib.request.Request(
        url,
        data=None,
        # Set a user agent to avoid 403 response from some podcast audio servers.
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_9_3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/35.0.1916.47 Safari/537.36"
        },
    )
    with urllib.request.urlopen(req) as resp:
        length = resp.headers['content-length']
        logger.info(f"download file#{url}, size#{length}")
        if int(length) > MAX_FILE:
            raise ValueError(f"Files larger than {MAX_FILE} are not supported.")

        return DownloadResult(
            data=resp.read(),
            content_type=resp.headers["content-type"],
        )


def sizeof_fmt(num, suffix="B") -> str:
    for unit in ["", "Ki", "Mi", "Gi", "Ti", "Pi", "Ei", "Zi"]:
        if abs(num) < 1024.0:
            return "%3.1f%s%s" % (num, unit, suffix)
        num /= 1024.0
    return "%.1f%s%s" % (num, "Yi", suffix)


def store_original_audio(
    url: str, destination: Path, overwrite: bool = False
) -> None:
    if destination.exists():
        if overwrite:
            logger.info(
                f"Audio file exists at {destination} but overwrite option is specified."
            )
        else:
            logger.info(
                f"Audio file exists at {destination}, skipping download."
            )
            return

    podcast_download_result = download_file(url=url)
    humanized_bytes_str = sizeof_fmt(num=len(podcast_download_result.data))
    logger.info(f"Downloaded {humanized_bytes_str} episode from URL.")
    with open(destination, "wb") as f:
        f.write(podcast_download_result.data)
    logger.info(f"Stored audio episode at {destination}.")


def coalesce_short_transcript_segments(
    segments: list[Segment],
) -> list[Segment]:
    """
    Some extracted transcript segments from openai/whisper are really short, like even just one word.
    This function accepts a minimum segment length and combines short segments until the minimum is reached.
    """
    minimum_transcript_len = 200  # About 2 sentences.
    previous = None
    long_enough_segments = []
    for current in segments:
        if previous is None:
            previous = current
        elif len(previous["text"]) < minimum_transcript_len:
            previous = _merge_segments(left=previous, right=current)
        else:
            long_enough_segments.append(previous)
            previous = current
    if previous:
        long_enough_segments.append(previous)
    return long_enough_segments


def _merge_segments(left: Segment, right: Segment) -> Segment:
    return {
        "text": left["text"] + " " + right["text"],
        "start": left["start"],
        "end": right["end"],
    }
